"""Tests for JavaScriptExtractor."""

from pathlib import Path

import pytest

from docsoup.models import Dependency
from docsoup.parsing.javascript import JavaScriptExtractor

FIXTURES_JS = Path(__file__).parent / "fixtures" / "js"
NODE_FIXTURES = Path(__file__).parent / "fixtures" / "node_project" / "node_modules"


def make_dep(name: str, path: Path, version: str = "1.0.0") -> Dependency:
    return Dependency(name=name, version=version, path=path, ecosystem="node")


# ---------------------------------------------------------------------------
# can_extract
# ---------------------------------------------------------------------------

class TestCanExtract:
    def setup_method(self):
        self.extractor = JavaScriptExtractor()

    def test_can_extract_js_dep_with_main_field(self):
        dep = make_dep("express", NODE_FIXTURES / "express", version="4.18.2")
        assert self.extractor.can_extract(dep) is True

    def test_can_extract_js_dep_with_index_js_fallback(self, tmp_path):
        """A package with index.js but no main/types field is extractable."""
        (tmp_path / "index.js").write_text("export function foo() {}")
        dep = make_dep("mypkg", tmp_path)
        assert self.extractor.can_extract(dep) is True

    def test_cannot_extract_non_node_ecosystem(self):
        dep = Dependency(
            name="serde", version="1.0", path=NODE_FIXTURES / "express", ecosystem="rust"
        )
        assert self.extractor.can_extract(dep) is False

    def test_cannot_extract_when_no_js_entry(self, tmp_path):
        """A package dir with no JS file returns False."""
        (tmp_path / "package.json").write_text('{"name": "nojspkg", "version": "1.0.0"}')
        dep = make_dep("nojspkg", tmp_path)
        assert self.extractor.can_extract(dep) is False

    def test_can_extract_when_no_package_json(self, tmp_path):
        """Falls back to index.js even without a package.json."""
        (tmp_path / "index.js").write_text("export const X = 1;")
        dep = make_dep("barebone", tmp_path)
        assert self.extractor.can_extract(dep) is True


# ---------------------------------------------------------------------------
# ESM exports
# ---------------------------------------------------------------------------

class TestExtractESMFunctions:
    def setup_method(self):
        import json
        pkg_json = FIXTURES_JS / "package.json"
        pkg_json.write_text(json.dumps({"name": "mylib", "version": "1.0.0", "main": "esm.js"}))
        self.extractor = JavaScriptExtractor()
        self.dep = make_dep("mylib", FIXTURES_JS)

    def teardown_method(self):
        pkg_json = FIXTURES_JS / "package.json"
        if pkg_json.exists():
            pkg_json.unlink()

    def _syms(self):
        return {s.name: s for s in self.extractor.extract(self.dep)}

    def test_extracts_named_functions(self):
        syms = self._syms()
        assert "add" in syms
        assert "subtract" in syms

    def test_function_kind(self):
        syms = self._syms()
        assert syms["add"].kind == "function"
        assert syms["subtract"].kind == "function"

    def test_function_fqn(self):
        syms = self._syms()
        assert syms["add"].fqn == "mylib:add"

    def test_function_jsdoc(self):
        syms = self._syms()
        assert syms["add"].docstring is not None
        assert "Adds two numbers" in syms["add"].docstring

    def test_function_line_comment(self):
        syms = self._syms()
        assert syms["subtract"].docstring is not None
        assert "Simple subtraction" in syms["subtract"].docstring

    def test_function_library_fields(self):
        syms = self._syms()
        sym = syms["add"]
        assert sym.library == "mylib"
        assert sym.library_version == "1.0.0"

    def test_function_signature_not_empty(self):
        syms = self._syms()
        assert "add" in syms["add"].signature

    def test_function_line_number(self):
        syms = self._syms()
        assert syms["add"].line_number >= 1

    def test_default_export_function(self):
        syms = self._syms()
        assert "default" in syms
        assert syms["default"].kind == "function"


class TestExtractESMClasses:
    def setup_method(self):
        import json
        pkg_json = FIXTURES_JS / "package.json"
        pkg_json.write_text(json.dumps({"name": "mylib", "version": "1.0.0", "main": "esm.js"}))
        self.extractor = JavaScriptExtractor()
        self.dep = make_dep("mylib", FIXTURES_JS)

    def teardown_method(self):
        pkg_json = FIXTURES_JS / "package.json"
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

    def test_class_fqn(self):
        syms = {s.name: s for s in self._all_symbols()}
        assert syms["EventEmitter"].fqn == "mylib:EventEmitter"

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


class TestExtractESMVariables:
    def setup_method(self):
        import json
        pkg_json = FIXTURES_JS / "package.json"
        pkg_json.write_text(json.dumps({"name": "mylib", "version": "1.0.0", "main": "esm.js"}))
        self.extractor = JavaScriptExtractor()
        self.dep = make_dep("mylib", FIXTURES_JS)

    def teardown_method(self):
        pkg_json = FIXTURES_JS / "package.json"
        if pkg_json.exists():
            pkg_json.unlink()

    def _syms(self):
        return {s.name: s for s in self.extractor.extract(self.dep)}

    def test_extracts_const(self):
        syms = self._syms()
        assert "VERSION" in syms
        assert syms["VERSION"].kind == "variable"

    def test_extracts_let(self):
        syms = self._syms()
        assert "counter" in syms
        assert syms["counter"].kind == "variable"

    def test_variable_fqn(self):
        syms = self._syms()
        assert syms["VERSION"].fqn == "mylib:VERSION"

    def test_variable_jsdoc(self):
        syms = self._syms()
        assert syms["VERSION"].docstring is not None
        assert "version" in syms["VERSION"].docstring.lower()


# ---------------------------------------------------------------------------
# CommonJS exports
# ---------------------------------------------------------------------------

class TestExtractCommonJS:
    def setup_method(self):
        import json
        pkg_json = FIXTURES_JS / "package.json"
        pkg_json.write_text(json.dumps({"name": "cjslib", "version": "2.0.0", "main": "commonjs.js"}))
        self.extractor = JavaScriptExtractor()
        self.dep = make_dep("cjslib", FIXTURES_JS, version="2.0.0")

    def teardown_method(self):
        pkg_json = FIXTURES_JS / "package.json"
        if pkg_json.exists():
            pkg_json.unlink()

    def _syms(self):
        return {s.name: s for s in self.extractor.extract(self.dep)}

    def test_extracts_from_module_exports_object(self):
        syms = self._syms()
        assert "greet" in syms
        assert "Router" in syms
        assert "VERSION" in syms

    def test_function_kind_from_declaration_lookup(self):
        syms = self._syms()
        assert syms["greet"].kind == "function"

    def test_class_kind_from_declaration_lookup(self):
        syms = self._syms()
        assert syms["Router"].kind == "class"

    def test_variable_kind_from_declaration_lookup(self):
        syms = self._syms()
        assert syms["VERSION"].kind == "variable"

    def test_jsdoc_from_declaration(self):
        """JSDoc on the original declaration should be picked up."""
        syms = self._syms()
        assert syms["greet"].docstring is not None
        assert "Greets" in syms["greet"].docstring

    def test_extracts_module_exports_dot_assignment(self):
        syms = self._syms()
        assert "helper" in syms

    def test_extracts_exports_dot_assignment(self):
        syms = self._syms()
        assert "util" in syms

    def test_fqn_for_cjs_symbol(self):
        syms = self._syms()
        assert syms["greet"].fqn == "cjslib:greet"


# ---------------------------------------------------------------------------
# Entry-point resolution
# ---------------------------------------------------------------------------

class TestEntryResolution:
    def setup_method(self):
        self.extractor = JavaScriptExtractor()

    def test_resolves_main_field(self):
        """express fixture uses 'main' field."""
        dep = make_dep("express", NODE_FIXTURES / "express", version="4.18.2")
        assert self.extractor.can_extract(dep) is True
        symbols = self.extractor.extract(dep)
        assert len(symbols) > 0

    def test_resolves_index_js_fallback(self, tmp_path):
        """No main field → falls back to index.js."""
        (tmp_path / "package.json").write_text('{"name": "pkg", "version": "1.0.0"}')
        (tmp_path / "index.js").write_text("export function hello() {}")
        dep = make_dep("pkg", tmp_path)
        symbols = self.extractor.extract(dep)
        names = {s.name for s in symbols}
        assert "hello" in names

    def test_returns_empty_for_missing_entry(self, tmp_path):
        """Package directory exists but has no JS files → empty list."""
        (tmp_path / "package.json").write_text('{"name": "empty", "version": "1.0.0"}')
        dep = make_dep("empty", tmp_path)
        assert self.extractor.extract(dep) == []

    def test_express_fixture_has_expected_symbols(self):
        dep = make_dep("express", NODE_FIXTURES / "express", version="4.18.2")
        syms = {s.name: s for s in self.extractor.extract(dep)}
        assert "createApplication" in syms
        assert "Router" in syms
        assert "VERSION" in syms

    def test_express_router_methods_extracted(self):
        dep = make_dep("express", NODE_FIXTURES / "express", version="4.18.2")
        fqns = {s.fqn for s in self.extractor.extract(dep)}
        assert "express:Router.get" in fqns
        assert "express:Router.post" in fqns
