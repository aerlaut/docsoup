"""Tests for PythonDiscoverer."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from docsoup.discovery.python import PythonDiscoverer, _normalise, _parse_pep508_name

FIXTURES = Path(__file__).parent / "fixtures" / "python_project"
SITE_PACKAGES = FIXTURES / ".venv" / "lib" / "python3.12" / "site-packages"


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

class TestNormalise:
    def test_lowercase(self):
        assert _normalise("Requests") == "requests"

    def test_hyphens_to_underscores(self):
        assert _normalise("my-package") == "my_package"

    def test_dots_to_underscores(self):
        assert _normalise("zope.interface") == "zope_interface"

    def test_consecutive_separators(self):
        assert _normalise("my--pkg") == "my_pkg"

    def test_mixed(self):
        assert _normalise("My-Package.Name") == "my_package_name"


class TestParsePep508Name:
    def test_bare_name(self):
        assert _parse_pep508_name("requests") == "requests"

    def test_with_version_gte(self):
        assert _parse_pep508_name("requests>=2.28") == "requests"

    def test_with_version_eq(self):
        assert _parse_pep508_name("click==8.1.7") == "click"

    def test_with_extras(self):
        assert _parse_pep508_name("click[testing]") == "click"

    def test_with_tilde_eq(self):
        assert _parse_pep508_name("Django~=4.2") == "Django"

    def test_with_env_marker(self):
        assert _parse_pep508_name("requests>=2.0; python_version>='3.6'") == "requests"

    def test_empty_string_returns_none(self):
        assert _parse_pep508_name("") is None

    def test_whitespace_only_returns_none(self):
        assert _parse_pep508_name("   ") is None


# ---------------------------------------------------------------------------
# Integration tests against fixture project
# ---------------------------------------------------------------------------

class TestPythonDiscoverer:
    def setup_method(self):
        self.discoverer = PythonDiscoverer()

    # --- .venv detection ---

    def test_raises_when_no_venv(self, tmp_path):
        with pytest.raises(RuntimeError, match=r"\.venv"):
            self.discoverer.discover(tmp_path)

    def test_raises_with_helpful_message(self, tmp_path):
        with pytest.raises(RuntimeError, match="virtual environment"):
            self.discoverer.discover(tmp_path)

    # --- basic discovery ---

    def test_discovers_requests(self):
        deps = self.discoverer.discover(FIXTURES)
        names = {d.name for d in deps}
        assert "requests" in names

    def test_discovers_click(self):
        deps = self.discoverer.discover(FIXTURES)
        names = {d.name for d in deps}
        assert "click" in names

    # --- version resolution ---

    def test_resolves_correct_version_requests(self):
        deps = self.discoverer.discover(FIXTURES)
        req = next(d for d in deps if d.name == "requests")
        assert req.version == "2.28.2"

    def test_resolves_correct_version_click(self):
        deps = self.discoverer.discover(FIXTURES)
        click = next(d for d in deps if d.name == "click")
        assert click.version == "8.1.7"

    # --- path resolution ---

    def test_resolves_path_to_disk_location(self):
        deps = self.discoverer.discover(FIXTURES)
        req = next(d for d in deps if d.name == "requests")
        assert req.path.is_dir()
        assert req.path.name == "requests"

    def test_path_is_absolute(self):
        deps = self.discoverer.discover(FIXTURES)
        for dep in deps:
            assert dep.path.is_absolute()

    # --- ecosystem field ---

    def test_ecosystem_is_python(self):
        deps = self.discoverer.discover(FIXTURES)
        assert all(d.ecosystem == "python" for d in deps)

    # --- name mismatch (Pillow → PIL) ---

    def test_skips_packages_not_in_manifest(self):
        """Pillow is installed in the fixture but not in pyproject.toml/requirements.txt."""
        deps = self.discoverer.discover(FIXTURES)
        names = {d.name for d in deps}
        assert "Pillow" not in names

    # --- uninstalled packages are silently skipped ---

    def test_skips_packages_not_installed(self):
        """pytest is in requirements.txt but has no dist-info in the fixture."""
        deps = self.discoverer.discover(FIXTURES)
        names = {d.name for d in deps}
        assert "pytest" not in names

    # --- no duplicates ---

    def test_no_duplicate_packages(self):
        """requests appears in both pyproject.toml and requirements.txt — only once returned."""
        deps = self.discoverer.discover(FIXTURES)
        names = [d.name for d in deps]
        assert len(names) == len(set(names))

    # --- malformed pyproject.toml ---

    def test_handles_malformed_pyproject_gracefully(self, tmp_path):
        venv = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
        venv.mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text("not valid toml {{{{")
        deps = self.discoverer.discover(tmp_path)
        assert deps == []

    # --- requirements.txt only ---

    def test_discovers_from_requirements_only(self, tmp_path):
        venv = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
        venv.mkdir(parents=True)
        # Install a fake package
        (venv / "mypkg-1.0.0.dist-info").mkdir()
        (venv / "mypkg-1.0.0.dist-info" / "METADATA").write_text(
            "Name: mypkg\nVersion: 1.0.0\n"
        )
        (venv / "mypkg-1.0.0.dist-info" / "top_level.txt").write_text("mypkg\n")
        (venv / "mypkg").mkdir()
        (tmp_path / "requirements.txt").write_text("mypkg==1.0.0\n")
        deps = self.discoverer.discover(tmp_path)
        assert len(deps) == 1
        assert deps[0].name == "mypkg"
        assert deps[0].version == "1.0.0"

    # --- pyproject.toml only ---

    def test_discovers_from_pyproject_only(self, tmp_path):
        venv = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
        venv.mkdir(parents=True)
        (venv / "mypkg-2.0.0.dist-info").mkdir()
        (venv / "mypkg-2.0.0.dist-info" / "METADATA").write_text(
            "Name: mypkg\nVersion: 2.0.0\n"
        )
        (venv / "mypkg-2.0.0.dist-info" / "top_level.txt").write_text("mypkg\n")
        (venv / "mypkg").mkdir()
        (tmp_path / "pyproject.toml").write_text(
            '[project]\ndependencies = ["mypkg>=2.0"]\n'
        )
        deps = self.discoverer.discover(tmp_path)
        assert len(deps) == 1
        assert deps[0].name == "mypkg"

    # --- name normalisation (Pillow → PIL) ---

    def test_resolves_package_with_different_importable_name(self, tmp_path):
        """Pillow installs into PIL/ — top_level.txt maps it correctly."""
        venv = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
        venv.mkdir(parents=True)
        (venv / "Pillow-9.4.0.dist-info").mkdir()
        (venv / "Pillow-9.4.0.dist-info" / "METADATA").write_text(
            "Name: Pillow\nVersion: 9.4.0\n"
        )
        (venv / "Pillow-9.4.0.dist-info" / "top_level.txt").write_text("PIL\n")
        (venv / "PIL").mkdir()
        (tmp_path / "requirements.txt").write_text("Pillow==9.4.0\n")
        deps = self.discoverer.discover(tmp_path)
        assert len(deps) == 1
        pil = deps[0]
        assert pil.name == "Pillow"
        assert pil.path.name == "PIL"

    # --- no manifest files → empty ---

    def test_returns_empty_when_no_manifest(self, tmp_path):
        venv = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
        venv.mkdir(parents=True)
        deps = self.discoverer.discover(tmp_path)
        assert deps == []

    # --- dist-info missing version field ---

    def test_uses_unknown_when_version_missing(self, tmp_path):
        venv = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
        venv.mkdir(parents=True)
        (venv / "mypkg-0.0.0.dist-info").mkdir()
        (venv / "mypkg-0.0.0.dist-info" / "METADATA").write_text("Name: mypkg\n")
        (venv / "mypkg-0.0.0.dist-info" / "top_level.txt").write_text("mypkg\n")
        (venv / "mypkg").mkdir()
        (tmp_path / "requirements.txt").write_text("mypkg\n")
        deps = self.discoverer.discover(tmp_path)
        assert deps[0].version == "unknown"

    # --- Poetry-style pyproject.toml ---

    def test_discovers_poetry_dependencies(self, tmp_path):
        venv = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
        venv.mkdir(parents=True)
        (venv / "flask-3.0.0.dist-info").mkdir()
        (venv / "flask-3.0.0.dist-info" / "METADATA").write_text(
            "Name: Flask\nVersion: 3.0.0\n"
        )
        (venv / "flask-3.0.0.dist-info" / "top_level.txt").write_text("flask\n")
        (venv / "flask").mkdir()
        (tmp_path / "pyproject.toml").write_text(
            "[tool.poetry.dependencies]\n"
            'python = "^3.11"\n'
            'Flask = "^3.0"\n'
        )
        deps = self.discoverer.discover(tmp_path)
        assert len(deps) == 1
        assert deps[0].name == "Flask"

    def test_poetry_skips_python_pseudo_dep(self, tmp_path):
        venv = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
        venv.mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text(
            "[tool.poetry.dependencies]\n"
            'python = "^3.11"\n'
        )
        # No packages installed — "python" should be silently ignored, not cause an error
        deps = self.discoverer.discover(tmp_path)
        assert deps == []

    # --- Windows-style venv layout ---

    def test_finds_windows_site_packages(self, tmp_path):
        win_site = tmp_path / ".venv" / "Lib" / "site-packages"
        win_site.mkdir(parents=True)
        (win_site / "mypkg-1.0.0.dist-info").mkdir()
        (win_site / "mypkg-1.0.0.dist-info" / "METADATA").write_text(
            "Name: mypkg\nVersion: 1.0.0\n"
        )
        (win_site / "mypkg-1.0.0.dist-info" / "top_level.txt").write_text("mypkg\n")
        (win_site / "mypkg").mkdir()
        (tmp_path / "requirements.txt").write_text("mypkg==1.0.0\n")
        deps = self.discoverer.discover(tmp_path)
        assert len(deps) == 1
        assert deps[0].name == "mypkg"

    # --- site-packages missing inside .venv ---

    def test_raises_when_site_packages_missing(self, tmp_path):
        (tmp_path / ".venv").mkdir()
        (tmp_path / "requirements.txt").write_text("requests\n")
        with pytest.raises(RuntimeError, match="site-packages"):
            self.discoverer.discover(tmp_path)
