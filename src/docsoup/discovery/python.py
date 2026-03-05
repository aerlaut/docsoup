"""Python dependency discoverer — reads pyproject.toml / requirements.txt and resolves .venv."""

from __future__ import annotations

import logging
import re
import tomllib
from pathlib import Path

from docsoup.discovery.base import DependencyDiscoverer
from docsoup.models import Dependency

logger = logging.getLogger(__name__)

# Matches the package name portion of a PEP 508 requirement string.
# Captures everything up to the first version specifier, extra, or whitespace.
# e.g. "requests>=2.28" → "requests", "click[testing]~=8.1" → "click"
_PEP508_NAME_RE = re.compile(r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)")

# Characters that separate a package name from its version constraint.
_CONSTRAINT_CHARS = re.compile(r"[>=<!~\[\s;@]")


def _normalise(name: str) -> str:
    """Normalise a PyPI package name per PEP 503: lowercase, collapse separators to '_'."""
    return re.sub(r"[-_.]+", "_", name).lower()


def _parse_pep508_name(spec: str) -> str | None:
    """Extract the bare package name from a PEP 508 requirement string."""
    spec = spec.strip()
    if not spec:
        return None
    m = _PEP508_NAME_RE.match(spec)
    return m.group(1) if m else None


class PythonDiscoverer(DependencyDiscoverer):
    """
    Discovers Python dependencies for a project that uses a ``.venv`` virtual environment.

    Reads dependency names from ``pyproject.toml`` (PEP 621 and Poetry layouts) and/or
    ``requirements.txt``, then resolves each name to its installed location inside
    ``.venv`` by scanning ``dist-info`` metadata directories.

    Raises:
        RuntimeError: If no ``.venv`` directory exists at *project_root*, or if the
            site-packages directory cannot be located inside it.
    """

    # ------------------------------------------------------------------
    # DependencyDiscoverer interface
    # ------------------------------------------------------------------

    def discover(self, project_root: Path) -> list[Dependency]:
        venv_path = project_root / ".venv"
        if not venv_path.is_dir():
            raise RuntimeError(
                f"No .venv found at {venv_path} — "
                "create a virtual environment first (e.g. `python -m venv .venv`)"
            )

        site_packages = self._find_site_packages(venv_path)

        names = self._collect_package_names(project_root)
        if not names:
            logger.debug("No dependency names found in %s — returning empty list", project_root)
            return []

        dist_map = self._build_dist_map(site_packages)

        deps: list[Dependency] = []
        for raw_name in names:
            dep = self._resolve(raw_name, site_packages, dist_map)
            if dep is not None:
                deps.append(dep)

        logger.debug("Discovered %d Python dependencies in %s", len(deps), project_root)
        return deps

    # ------------------------------------------------------------------
    # .venv helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_site_packages(venv_path: Path) -> Path:
        """Locate the site-packages directory inside *venv_path*.

        Handles both Unix (``.venv/lib/pythonX.Y/site-packages``) and
        Windows (``.venv/Lib/site-packages``) layouts.

        Raises:
            RuntimeError: If no site-packages directory can be found.
        """
        # Unix: .venv/lib/python3.x/site-packages
        for candidate in sorted((venv_path / "lib").glob("python*/site-packages")):
            if candidate.is_dir():
                return candidate

        # Windows: .venv/Lib/site-packages
        win_candidate = venv_path / "Lib" / "site-packages"
        if win_candidate.is_dir():
            return win_candidate

        raise RuntimeError(
            f"Cannot locate site-packages inside {venv_path}. "
            "The virtual environment may be incomplete."
        )

    # ------------------------------------------------------------------
    # Manifest parsing
    # ------------------------------------------------------------------

    def _collect_package_names(self, project_root: Path) -> list[str]:
        """Collect unique raw package names from all recognised manifest files."""
        seen: dict[str, None] = {}  # ordered set

        pyproject = project_root / "pyproject.toml"
        if pyproject.exists():
            for name in self._parse_pyproject(pyproject):
                seen[name] = None

        requirements = project_root / "requirements.txt"
        if requirements.exists():
            for name in self._parse_requirements(requirements):
                seen[name] = None

        return list(seen)

    @staticmethod
    def _parse_pyproject(path: Path) -> list[str]:
        """Extract package names from a ``pyproject.toml`` file.

        Supports:
        - PEP 621: ``[project] dependencies``
        - Poetry:  ``[tool.poetry.dependencies]``
        """
        try:
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        except (tomllib.TOMLDecodeError, OSError) as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return []

        names: list[str] = []

        # PEP 621 — list of PEP 508 strings
        project_deps = data.get("project", {}).get("dependencies", [])
        for spec in project_deps:
            name = _parse_pep508_name(str(spec))
            if name:
                names.append(name)

        # Poetry — dict of {name: constraint}; skip the "python" pseudo-dep
        poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        for name in poetry_deps:
            if name.lower() == "python":
                continue
            names.append(name)

        return names

    @staticmethod
    def _parse_requirements(path: Path) -> list[str]:
        """Extract package names from a ``requirements.txt`` file."""
        names: list[str] = []
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return []

        for raw_line in text.splitlines():
            line = raw_line.strip()
            # Skip blank lines, comments, and pip option flags
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            # Strip inline comments
            line = line.split("#")[0].strip()
            if not line:
                continue
            name = _parse_pep508_name(line)
            if name:
                names.append(name)

        return names

    # ------------------------------------------------------------------
    # dist-info scanning & package resolution
    # ------------------------------------------------------------------

    def _build_dist_map(self, site_packages: Path) -> dict[str, "_DistInfo"]:
        """Scan ``site-packages`` and build a normalised-name → _DistInfo map."""
        dist_map: dict[str, _DistInfo] = {}

        for dist_info_dir in site_packages.glob("*.dist-info"):
            if not dist_info_dir.is_dir():
                continue

            metadata_path = dist_info_dir / "METADATA"
            if not metadata_path.exists():
                continue

            canonical_name, version = _read_name_version(metadata_path)
            if not canonical_name:
                continue

            top_level_names = _read_top_level(dist_info_dir)
            if not top_level_names:
                # Fall back to the normalised PyPI name as the importable name
                top_level_names = [re.sub(r"[-_.]+", "_", canonical_name).lower()]

            key = _normalise(canonical_name)
            dist_map[key] = _DistInfo(
                canonical_name=canonical_name,
                version=version,
                top_level_names=top_level_names,
            )

        return dist_map

    def _resolve(
        self,
        raw_name: str,
        site_packages: Path,
        dist_map: dict[str, "_DistInfo"],
    ) -> Dependency | None:
        """Resolve *raw_name* to an installed :class:`~docsoup.models.Dependency`."""
        key = _normalise(raw_name)
        info = dist_map.get(key)

        if info is None:
            logger.debug("Package %r not found in site-packages — skipping", raw_name)
            return None

        # Use the first importable top-level name as the package directory.
        for top_name in info.top_level_names:
            pkg_dir = site_packages / top_name
            if pkg_dir.is_dir():
                return Dependency(
                    name=info.canonical_name,
                    version=info.version,
                    path=pkg_dir.resolve(),
                    ecosystem="python",
                )

        logger.debug(
            "Package %r: dist-info found but source directory missing — skipping", raw_name
        )
        return None


# ------------------------------------------------------------------
# Internal data class
# ------------------------------------------------------------------

class _DistInfo:
    __slots__ = ("canonical_name", "version", "top_level_names")

    def __init__(
        self,
        canonical_name: str,
        version: str,
        top_level_names: list[str],
    ) -> None:
        self.canonical_name = canonical_name
        self.version = version
        self.top_level_names = top_level_names


# ------------------------------------------------------------------
# Pure utility functions
# ------------------------------------------------------------------

def _read_name_version(metadata_path: Path) -> tuple[str, str]:
    """Parse ``Name:`` and ``Version:`` from a dist-info METADATA file."""
    name = ""
    version = "unknown"
    try:
        for line in metadata_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Name:"):
                name = line[5:].strip()
            elif line.startswith("Version:"):
                version = line[8:].strip()
            if name and version != "unknown":
                break
    except OSError as exc:
        logger.warning("Failed to read %s: %s", metadata_path, exc)
    return name, version


def _read_top_level(dist_info_dir: Path) -> list[str]:
    """Return importable names from ``top_level.txt``, or an empty list if absent."""
    top_level_path = dist_info_dir / "top_level.txt"
    if not top_level_path.exists():
        return []
    try:
        return [
            line.strip()
            for line in top_level_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except OSError as exc:
        logger.warning("Failed to read %s: %s", top_level_path, exc)
        return []
