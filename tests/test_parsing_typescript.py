"""Tests for TypeScriptExtractor."""

from pathlib import Path

import pytest

from docsoup.models import Dependency
from docsoup.parsing.typescript import TypeScriptExtractor

FIXTURES_DTS = Path(__file__).parent / "fixtures" / "dts"
NODE_FIXTURES = Path(__file__).parent / "fixtures" / "node_project" / "node_modules"


def make_dep(name: str, path: Path, version: str = "1.0.0") -> Dependency:
    return Dependency(name=name, version=version, path=path, ecosystem="node")


class TestCanExtract:
    def setup_method(self):
        self.extractor = TypeScriptExtractor()

    def test_can_extract_when_dts_exists(self):
        dep = make_dep("chalk", NODE_FIXTURES / "chalk")
        assert self.extractor.can_extract(dep) is True

    def test_cannot_extract_no_dts(self):
        dep = make_dep("typescript", NODE_FIXTURES / "typescript")
        # typescript fixture has no .d.ts entry point
        assert self.extractor.can_extract(dep) is False

    def test_cannot_extract_non_node_ecosystem(self):
        dep = Dependency(
            name="serde", version="1.0", path=NODE_FIXTURES / "chalk", ecosystem="rust"
        )
        assert self.extractor.can_extract(dep) is False


class TestExtractFunctions:
    def setup_method(self):
        self.extractor = TypeScriptExtractor()
        self.dep = make_dep("mylib", FIXTURES_DTS)
        # Override entry to our rich fixture
        self._patch_entry(FIXTURES_DTS / "simple.d.ts")

    def _patch_entry(self, path: Path):
        """Create a minimal package.json pointing at our test .d.ts."""
        import json
        pkg_json = FIXTURES_DTS / "package.json"
        pkg_json.write_text(json.dumps({"name": "mylib", "version": "1.0.0", "types": "simple.d.ts"}))
        self.dep = make_dep("mylib", FIXTURES_DTS)

    def teardown_method(self):
        pkg_json = FIXTURES_DTS / "package.json"
        if pkg_json.exists():
            pkg_json.unlink()

    def _symbols_by_name(self):
        symbols = self.extractor.extract(self.dep)
        return {s.name: s for s in symbols}

    def test_extracts_functions(self):
        syms = self._symbols_by_name()
        assert "add" in syms
        assert "subtract" in syms
        assert "noop" in syms

    def test_function_kind(self):
        syms = self._symbols_by_name()
        assert syms["add"].kind == "function"

    def test_function_fqn(self):
        syms = self._symbols_by_name()
        assert syms["add"].fqn == "mylib:add"

    def test_function_with_jsdoc(self):
        syms = self._symbols_by_name()
        assert syms["add"].docstring is not None
        assert "Adds two numbers" in syms["add"].docstring

    def test_function_with_line_comment(self):
        syms = self._symbols_by_name()
        # noop has a "// No JSDoc" comment before it
        assert syms["noop"].docstring is not None
        assert "No JSDoc" in syms["noop"].docstring

    def test_function_library_fields(self):
        syms = self._symbols_by_name()
        sym = syms["add"]
        assert sym.library == "mylib"
        assert sym.library_version == "1.0.0"

    def test_function_signature_not_empty(self):
        syms = self._symbols_by_name()
        assert "add" in syms["add"].signature
        assert "number" in syms["add"].signature

    def test_function_line_number(self):
        syms = self._symbols_by_name()
        # add is on line 7 (1-indexed) in simple.d.ts
        assert syms["add"].line_number >= 1


class TestExtractClasses:
    def setup_method(self):
        import json
        pkg_json = FIXTURES_DTS / "package.json"
        pkg_json.write_text(json.dumps({"name": "mylib", "version": "1.0.0", "types": "simple.d.ts"}))
        self.extractor = TypeScriptExtractor()
        self.dep = make_dep("mylib", FIXTURES_DTS)

    def teardown_method(self):
        pkg_json = FIXTURES_DTS / "package.json"
        if pkg_json.exists():
            pkg_json.unlink()

    def _all_symbols(self):
        return self.extractor.extract(self.dep)

    def test_extracts_class(self):
        names = {s.name for s in self._all_symbols()}
        assert "EventEmitter" in names

    def test_class_kind(self):
        syms = {s.name: s for s in self._all_symbols()}
        assert syms["EventEmitter"].kind == "class"

    def test_extracts_class_methods(self):
        names = {s.name for s in self._all_symbols()}
        assert "on" in names
        assert "off" in names
        assert "emit" in names

    def test_method_fqn(self):
        syms = {s.fqn: s for s in self._all_symbols()}
        assert "mylib:EventEmitter.on" in syms

    def test_method_jsdoc(self):
        syms = {s.fqn: s for s in self._all_symbols()}
        assert syms["mylib:EventEmitter.on"].docstring is not None
        assert "Register" in syms["mylib:EventEmitter.on"].docstring


class TestExtractOtherKinds:
    def setup_method(self):
        import json
        pkg_json = FIXTURES_DTS / "package.json"
        pkg_json.write_text(json.dumps({"name": "mylib", "version": "1.0.0", "types": "simple.d.ts"}))
        self.extractor = TypeScriptExtractor()
        self.dep = make_dep("mylib", FIXTURES_DTS)

    def teardown_method(self):
        pkg_json = FIXTURES_DTS / "package.json"
        if pkg_json.exists():
            pkg_json.unlink()

    def _syms_by_name(self):
        return {s.name: s for s in self.extractor.extract(self.dep)}

    def test_extracts_interface(self):
        syms = self._syms_by_name()
        assert "Config" in syms
        assert syms["Config"].kind == "interface"

    def test_extracts_type_alias(self):
        syms = self._syms_by_name()
        assert "ID" in syms
        assert syms["ID"].kind == "type"

    def test_extracts_enum(self):
        syms = self._syms_by_name()
        assert "LogLevel" in syms
        assert syms["LogLevel"].kind == "enum"

    def test_extracts_constants(self):
        syms = self._syms_by_name()
        assert "VERSION" in syms
        assert syms["VERSION"].kind == "variable"


class TestAmbientModules:
    """Symbols inside `declare module '...' { ... }` blocks are extracted."""

    def setup_method(self):
        import json
        pkg_json = FIXTURES_DTS / "package.json"
        pkg_json.write_text(json.dumps({"name": "myambient", "version": "2.0.0", "types": "ambient.d.ts"}))
        self.extractor = TypeScriptExtractor()
        self.dep = make_dep("myambient", FIXTURES_DTS, version="2.0.0")

    def teardown_method(self):
        pkg_json = FIXTURES_DTS / "package.json"
        if pkg_json.exists():
            pkg_json.unlink()

    def _syms_by_name(self):
        return {s.name: s for s in self.extractor.extract(self.dep)}

    def test_extracts_function_from_ambient_module(self):
        syms = self._syms_by_name()
        assert "mount" in syms
        assert syms["mount"].kind == "function"

    def test_extracts_multiple_functions_from_ambient_module(self):
        syms = self._syms_by_name()
        assert "unmount" in syms

    def test_extracts_interface_from_ambient_module(self):
        syms = self._syms_by_name()
        assert "MountOptions" in syms
        assert syms["MountOptions"].kind == "interface"

    def test_extracts_type_from_ambient_module(self):
        syms = self._syms_by_name()
        assert "ComponentType" in syms
        assert syms["ComponentType"].kind == "type"

    def test_jsdoc_preserved_in_ambient_module(self):
        syms = self._syms_by_name()
        assert syms["mount"].docstring is not None
        assert "Mounts" in syms["mount"].docstring

    def test_extracts_symbols_from_multiple_ambient_modules(self):
        """Both `declare module 'myambient'` and `declare module 'myambient/utils'` are traversed."""
        syms = self._syms_by_name()
        assert "noop" in syms
        assert "VERSION" in syms

    def test_fqn_uses_dep_name(self):
        syms = self._syms_by_name()
        assert syms["mount"].fqn == "myambient:mount"


class TestEntryResolution:
    def setup_method(self):
        self.extractor = TypeScriptExtractor()

    def test_resolves_types_field(self):
        """chalk fixture uses 'types' field in package.json."""
        dep = make_dep("chalk", NODE_FIXTURES / "chalk", version="5.3.0")
        assert self.extractor.can_extract(dep) is True
        symbols = self.extractor.extract(dep)
        assert len(symbols) > 0

    def test_resolves_typings_field(self):
        """lodash fixture uses 'typings' field in package.json."""
        dep = make_dep("lodash", NODE_FIXTURES / "lodash", version="4.17.21")
        assert self.extractor.can_extract(dep) is True
        symbols = self.extractor.extract(dep)
        assert len(symbols) > 0

    def test_resolves_exports_map_types_field(self):
        """Package with only exports['.']['types'] — no top-level types/typings field."""
        dep = make_dep("exports-only", NODE_FIXTURES / "exports-only", version="1.0.0")
        assert self.extractor.can_extract(dep) is True
        symbols = self.extractor.extract(dep)
        names = {s.name for s in symbols}
        assert "greet" in names
        assert "Greeting" in names

    def test_returns_empty_for_no_dts(self):
        dep = make_dep("typescript", NODE_FIXTURES / "typescript")
        symbols = self.extractor.extract(dep)
        assert symbols == []
