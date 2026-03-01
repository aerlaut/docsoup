"""Tests for NodeDiscoverer."""

from pathlib import Path

import pytest

from docsoup.discovery.node import NodeDiscoverer

FIXTURES = Path(__file__).parent / "fixtures" / "node_project"


class TestNodeDiscoverer:
    def setup_method(self):
        self.discoverer = NodeDiscoverer()

    def test_discovers_production_deps(self):
        deps = self.discoverer.discover(FIXTURES)
        names = {d.name for d in deps}
        assert "chalk" in names
        assert "lodash" in names

    def test_discovers_dev_deps_by_default(self):
        deps = self.discoverer.discover(FIXTURES)
        names = {d.name for d in deps}
        assert "typescript" in names

    def test_excludes_dev_deps_when_disabled(self):
        discoverer = NodeDiscoverer(include_dev=False)
        deps = discoverer.discover(FIXTURES)
        names = {d.name for d in deps}
        assert "typescript" not in names
        assert "chalk" in names

    def test_resolves_correct_version(self):
        deps = self.discoverer.discover(FIXTURES)
        chalk = next(d for d in deps if d.name == "chalk")
        assert chalk.version == "5.3.0"

        lodash = next(d for d in deps if d.name == "lodash")
        assert lodash.version == "4.17.21"

    def test_resolves_path_to_disk_location(self):
        deps = self.discoverer.discover(FIXTURES)
        chalk = next(d for d in deps if d.name == "chalk")
        assert chalk.path.is_dir()
        assert chalk.path.name == "chalk"

    def test_ecosystem_is_node(self):
        deps = self.discoverer.discover(FIXTURES)
        assert all(d.ecosystem == "node" for d in deps)

    def test_returns_empty_when_no_package_json(self, tmp_path):
        deps = self.discoverer.discover(tmp_path)
        assert deps == []

    def test_skips_packages_not_installed(self, tmp_path):
        """Packages listed in package.json but absent from node_modules are skipped."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text('{"dependencies": {"nonexistent-pkg": "^1.0.0"}}')
        # No node_modules directory at all
        deps = self.discoverer.discover(tmp_path)
        assert deps == []

    def test_handles_malformed_package_json_gracefully(self, tmp_path):
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text("not valid json{{{")
        deps = self.discoverer.discover(tmp_path)
        assert deps == []

    def test_no_duplicate_packages(self):
        """A package listed in both dependencies and devDependencies appears once."""
        deps = self.discoverer.discover(FIXTURES)
        names = [d.name for d in deps]
        assert len(names) == len(set(names))

    def test_dep_with_missing_version_in_pkg_json(self, tmp_path):
        """A package whose own package.json has no 'version' field uses 'unknown'."""
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text('{"dependencies": {"mypkg": "*"}}')
        nm = tmp_path / "node_modules" / "mypkg"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text('{"name": "mypkg"}')
        deps = self.discoverer.discover(tmp_path)
        assert len(deps) == 1
        assert deps[0].version == "unknown"
