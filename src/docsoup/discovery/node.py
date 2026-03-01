"""Node.js dependency discoverer — reads package.json and resolves node_modules."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from docsoup.discovery.base import DependencyDiscoverer
from docsoup.models import Dependency

logger = logging.getLogger(__name__)

# Sections of package.json that list dependencies to index.
_DEP_SECTIONS = ("dependencies", "devDependencies", "peerDependencies")


class NodeDiscoverer(DependencyDiscoverer):
    """
    Discovers Node.js dependencies from a ``package.json`` manifest.

    Resolves each dependency to its directory inside ``node_modules/``.
    Only dependencies that are actually installed on disk are returned —
    entries present in ``package.json`` but absent from ``node_modules/``
    are silently skipped with a debug log.

    Args:
        include_dev: When True (default), also discover ``devDependencies``.
        include_peer: When True (default False), also discover
            ``peerDependencies``.
    """

    def __init__(self, *, include_dev: bool = True, include_peer: bool = False) -> None:
        self._sections = list(_DEP_SECTIONS[:2] if include_dev else _DEP_SECTIONS[:1])
        if include_peer:
            self._sections.append("peerDependencies")

    # ------------------------------------------------------------------
    # DependencyDiscoverer interface
    # ------------------------------------------------------------------

    def discover(self, project_root: Path) -> list[Dependency]:
        manifest_path = project_root / "package.json"
        if not manifest_path.exists():
            logger.debug("No package.json found at %s — skipping", project_root)
            return []

        manifest = self._load_json(manifest_path)
        if manifest is None:
            return []

        # Collect unique package names across requested sections (order stable).
        seen: dict[str, None] = {}
        for section in self._sections:
            for name in manifest.get(section, {}):
                seen[name] = None

        node_modules = project_root / "node_modules"
        deps: list[Dependency] = []

        for name in seen:
            dep = self._resolve(name, node_modules)
            if dep is not None:
                deps.append(dep)

        logger.debug("Discovered %d dependencies in %s", len(deps), project_root)
        return deps

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve(self, name: str, node_modules: Path) -> Dependency | None:
        """Resolve *name* to an installed ``Dependency`` or return None."""
        pkg_dir = node_modules / name
        pkg_json_path = pkg_dir / "package.json"

        if not pkg_dir.is_dir():
            logger.debug("Package %r not found in %s — skipping", name, node_modules)
            return None

        version = "unknown"
        if pkg_json_path.exists():
            meta = self._load_json(pkg_json_path)
            if meta:
                version = meta.get("version", "unknown")

        return Dependency(
            name=name,
            version=version,
            path=pkg_dir.resolve(),
            ecosystem="node",
        )

    @staticmethod
    def _load_json(path: Path) -> dict | None:
        try:
            with path.open(encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return None
