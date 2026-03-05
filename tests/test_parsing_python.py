"""Tests for PythonExtractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from docsoup.models import Dependency
from docsoup.parsing.python import PythonExtractor

FIXTURES_PY = Path(__file__).parent / "fixtures" / "py"


def make_dep(name: str, path: Path, version: str = "1.0.0") -> Dependency:
    return Dependency(name=name, version=version, path=path, ecosystem="python")


def make_py_dep(path: Path, name: str = "mylib") -> Dependency:
    return make_dep(name, path, version="1.0.0")


# ---------------------------------------------------------------------------
# can_extract
# ---------------------------------------------------------------------------

class TestCanExtract:
    def setup_method(self):
        self.extractor = PythonExtractor()

    def test_can_extract_python_ecosystem_with_py_files(self, tmp_path):
        (tmp_path / "mod.py").write_text("x = 1\n")
        dep = make_dep("pkg", tmp_path)
        assert self.extractor.can_extract(dep) is True

    def test_can_extract_python_ecosystem_with_pyi_files(self, tmp_path):
        (tmp_path / "mod.pyi").write_text("x: int\n")
        dep = make_dep("pkg", tmp_path)
        assert self.extractor.can_extract(dep) is True

    def test_cannot_extract_non_python_ecosystem(self, tmp_path):
        (tmp_path / "mod.py").write_text("x = 1\n")
        dep = Dependency(name="pkg", version="1.0", path=tmp_path, ecosystem="node")
        assert self.extractor.can_extract(dep) is False

    def test_cannot_extract_empty_directory(self, tmp_path):
        dep = make_dep("pkg", tmp_path)
        assert self.extractor.can_extract(dep) is False

    def test_cannot_extract_no_python_files(self, tmp_path):
        (tmp_path / "README.md").write_text("hello\n")
        dep = make_dep("pkg", tmp_path)
        assert self.extractor.can_extract(dep) is False


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

class TestFunctionExtraction:
    def setup_method(self):
        self.extractor = PythonExtractor()
        self.dep = make_py_dep(FIXTURES_PY, "mylib")
        # Point at the simple.py fixture directly by making a temp package dir
        # that contains only simple.py.

    def _extract_from_file(self, filename: str, dep_name: str = "mylib") -> dict:
        tmp = FIXTURES_PY  # Use fixtures dir as the package root
        dep = make_dep(dep_name, tmp)
        # Monkey-patch to only process one file
        symbols = []
        import ast
        from docsoup.parsing.python import _collect_all, _is_exported
        extractor = PythonExtractor()
        source = (FIXTURES_PY / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)
        export_set = _collect_all(tree)
        for node in ast.iter_child_nodes(tree):
            extractor._visit_top_level(node, source, dep, filename, export_set, symbols)
        return {s.name: s for s in symbols}

    def test_extracts_simple_function(self):
        syms = self._extract_from_file("simple.py")
        assert "add" in syms

    def test_extracts_async_function(self):
        syms = self._extract_from_file("simple.py")
        assert "fetch" in syms

    def test_function_kind(self):
        syms = self._extract_from_file("simple.py")
        assert syms["add"].kind == "function"
        assert syms["fetch"].kind == "function"

    def test_function_fqn(self):
        syms = self._extract_from_file("simple.py")
        assert syms["add"].fqn == "mylib:add"

    def test_function_signature_contains_name(self):
        syms = self._extract_from_file("simple.py")
        assert "add" in syms["add"].signature

    def test_function_signature_contains_params(self):
        syms = self._extract_from_file("simple.py")
        assert "x" in syms["add"].signature
        assert "y" in syms["add"].signature

    def test_function_signature_contains_return_type(self):
        syms = self._extract_from_file("simple.py")
        assert "int" in syms["add"].signature

    def test_async_function_signature_prefix(self):
        syms = self._extract_from_file("simple.py")
        assert syms["fetch"].signature.startswith("async def")

    def test_function_docstring(self):
        syms = self._extract_from_file("simple.py")
        assert syms["add"].docstring is not None
        assert "Add two numbers" in syms["add"].docstring

    def test_function_line_number(self):
        syms = self._extract_from_file("simple.py")
        assert syms["add"].line_number >= 1

    def test_function_library_fields(self):
        syms = self._extract_from_file("simple.py")
        assert syms["add"].library == "mylib"
        assert syms["add"].library_version == "1.0.0"

    def test_excludes_private_functions(self):
        syms = self._extract_from_file("simple.py")
        assert "_private_helper" not in syms


# ---------------------------------------------------------------------------
# Classes and methods
# ---------------------------------------------------------------------------

class TestClassExtraction:
    def _extract_from_file(self, filename: str, dep_name: str = "mylib") -> dict:
        import ast
        from docsoup.parsing.python import _collect_all
        dep = make_dep(dep_name, FIXTURES_PY)
        extractor = PythonExtractor()
        source = (FIXTURES_PY / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)
        export_set = _collect_all(tree)
        symbols = []
        for node in ast.iter_child_nodes(tree):
            extractor._visit_top_level(node, source, dep, filename, export_set, symbols)
        return {s.fqn: s for s in symbols}, {s.name: s for s in symbols}

    def test_extracts_class(self):
        _, by_name = self._extract_from_file("simple.py")
        assert "EventEmitter" in by_name

    def test_class_kind(self):
        _, by_name = self._extract_from_file("simple.py")
        assert by_name["EventEmitter"].kind == "class"

    def test_class_fqn(self):
        _, by_name = self._extract_from_file("simple.py")
        assert by_name["EventEmitter"].fqn == "mylib:EventEmitter"

    def test_class_docstring(self):
        _, by_name = self._extract_from_file("simple.py")
        assert by_name["EventEmitter"].docstring is not None
        assert "event emitter" in by_name["EventEmitter"].docstring.lower()

    def test_extracts_class_methods(self):
        by_fqn, _ = self._extract_from_file("simple.py")
        assert "mylib:EventEmitter.on" in by_fqn
        assert "mylib:EventEmitter.off" in by_fqn
        assert "mylib:EventEmitter.emit" in by_fqn

    def test_method_kind(self):
        by_fqn, _ = self._extract_from_file("simple.py")
        assert by_fqn["mylib:EventEmitter.on"].kind == "function"

    def test_method_docstring(self):
        by_fqn, _ = self._extract_from_file("simple.py")
        assert by_fqn["mylib:EventEmitter.on"].docstring is not None

    def test_method_signature_has_class_prefix(self):
        by_fqn, _ = self._extract_from_file("simple.py")
        sig = by_fqn["mylib:EventEmitter.on"].signature
        assert sig.startswith("EventEmitter.")

    def test_init_is_included(self):
        by_fqn, _ = self._extract_from_file("simple.py")
        assert "mylib:EventEmitter.__init__" in by_fqn

    def test_private_methods_excluded(self):
        by_fqn, _ = self._extract_from_file("simple.py")
        assert "mylib:EventEmitter._internal" not in by_fqn

    def test_private_class_excluded(self):
        _, by_name = self._extract_from_file("simple.py")
        assert "_PrivateClass" not in by_name


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

class TestVariableExtraction:
    def _extract_from_file(self, filename: str, dep_name: str = "mylib") -> dict:
        import ast
        from docsoup.parsing.python import _collect_all
        dep = make_dep(dep_name, FIXTURES_PY)
        extractor = PythonExtractor()
        source = (FIXTURES_PY / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)
        export_set = _collect_all(tree)
        symbols = []
        for node in ast.iter_child_nodes(tree):
            extractor._visit_top_level(node, source, dep, filename, export_set, symbols)
        return {s.name: s for s in symbols}

    def test_extracts_annotated_variable(self):
        syms = self._extract_from_file("simple.py")
        assert "VERSION" in syms

    def test_annotated_variable_kind(self):
        syms = self._extract_from_file("simple.py")
        assert syms["VERSION"].kind == "variable"

    def test_annotated_variable_signature_has_type(self):
        syms = self._extract_from_file("simple.py")
        assert "str" in syms["VERSION"].signature

    def test_annotated_variable_fqn(self):
        syms = self._extract_from_file("simple.py")
        assert syms["VERSION"].fqn == "mylib:VERSION"

    def test_private_variable_excluded(self):
        syms = self._extract_from_file("simple.py")
        assert "_PRIVATE_CONST" not in syms


# ---------------------------------------------------------------------------
# __all__ filtering
# ---------------------------------------------------------------------------

class TestAllFiltering:
    def _extract_from_file(self, filename: str, dep_name: str = "mylib") -> dict:
        import ast
        from docsoup.parsing.python import _collect_all
        dep = make_dep(dep_name, FIXTURES_PY)
        extractor = PythonExtractor()
        source = (FIXTURES_PY / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)
        export_set = _collect_all(tree)
        symbols = []
        for node in ast.iter_child_nodes(tree):
            extractor._visit_top_level(node, source, dep, filename, export_set, symbols)
        return {s.name: s for s in symbols}

    def test_includes_symbols_in_all(self):
        syms = self._extract_from_file("with_all.py")
        assert "PublicClass" in syms
        assert "public_func" in syms
        assert "CONSTANT" in syms

    def test_excludes_symbols_not_in_all(self):
        syms = self._extract_from_file("with_all.py")
        assert "unlisted_func" not in syms
        assert "UnlistedClass" not in syms
        assert "NOT_IN_ALL" not in syms

    def test_excludes_hidden_vars_even_if_not_underscored(self):
        syms = self._extract_from_file("with_all.py")
        assert "_HIDDEN" not in syms

    def test_methods_of_all_listed_class_still_extracted(self):
        syms = self._extract_from_file("with_all.py")
        # PublicClass is in __all__ so its public methods should be extracted
        method_fqns = {s.fqn for s in syms.values()}
        assert "mylib:PublicClass.method" in method_fqns

    def test_private_methods_excluded_even_in_all_class(self):
        syms = self._extract_from_file("with_all.py")
        method_fqns = {s.fqn for s in syms.values()}
        assert "mylib:PublicClass._private_method" not in method_fqns


# ---------------------------------------------------------------------------
# .pyi stub preference
# ---------------------------------------------------------------------------

class TestStubPreference:
    def setup_method(self):
        self.extractor = PythonExtractor()

    def test_prefers_pyi_over_py(self, tmp_path):
        """When both .pyi and .py exist, only .pyi files are parsed."""
        (tmp_path / "mod.py").write_text(
            "def from_source() -> None: ...\n"
        )
        (tmp_path / "mod.pyi").write_text(
            "def from_stub() -> None: ...\n"
        )
        dep = make_dep("pkg", tmp_path)
        symbols = self.extractor.extract(dep)
        names = {s.name for s in symbols}
        assert "from_stub" in names
        assert "from_source" not in names

    def test_falls_back_to_py_when_no_pyi(self, tmp_path):
        (tmp_path / "mod.py").write_text(
            "def from_source() -> None: ...\n"
        )
        dep = make_dep("pkg", tmp_path)
        symbols = self.extractor.extract(dep)
        names = {s.name for s in symbols}
        assert "from_source" in names

    def test_parses_pyi_fixture(self):
        """stub.pyi fixture contains connect() and Connection class."""
        dep = make_dep("stubpkg", FIXTURES_PY)
        extractor = PythonExtractor()
        import ast
        from docsoup.parsing.python import _collect_all
        source = (FIXTURES_PY / "stub.pyi").read_text(encoding="utf-8")
        tree = ast.parse(source)
        export_set = _collect_all(tree)
        symbols = []
        for node in ast.iter_child_nodes(tree):
            extractor._visit_top_level(node, source, dep, "stub.pyi", export_set, symbols)
        names = {s.name for s in symbols}
        assert "connect" in names
        assert "Connection" in names


# ---------------------------------------------------------------------------
# Full extract() integration
# ---------------------------------------------------------------------------

class TestExtractIntegration:
    def setup_method(self):
        self.extractor = PythonExtractor()

    def test_extract_single_py_file_package(self, tmp_path):
        (tmp_path / "mymod.py").write_text(
            'def hello(name: str) -> str:\n    """Say hello."""\n    return f"hi {name}"\n'
        )
        dep = make_dep("mymod", tmp_path)
        symbols = self.extractor.extract(dep)
        assert len(symbols) == 1
        assert symbols[0].name == "hello"
        assert symbols[0].kind == "function"
        assert "Say hello" in (symbols[0].docstring or "")

    def test_extract_returns_empty_for_empty_package(self, tmp_path):
        (tmp_path / "__init__.py").touch()
        dep = make_dep("empty", tmp_path)
        symbols = self.extractor.extract(dep)
        assert symbols == []

    def test_extract_handles_syntax_error_gracefully(self, tmp_path):
        (tmp_path / "broken.py").write_text("def foo(:\n")
        dep = make_dep("broken", tmp_path)
        symbols = self.extractor.extract(dep)
        assert symbols == []

    def test_extract_multi_file_package(self, tmp_path):
        (tmp_path / "__init__.py").write_text("from .a import foo\n")
        (tmp_path / "a.py").write_text("def foo() -> None: ...\n")
        (tmp_path / "b.py").write_text("def bar() -> None: ...\n")
        dep = make_dep("mypkg", tmp_path)
        symbols = self.extractor.extract(dep)
        names = {s.name for s in symbols}
        assert "foo" in names
        assert "bar" in names

    def test_relative_file_path_in_symbol(self, tmp_path):
        (tmp_path / "utils.py").write_text("def helper() -> None: ...\n")
        dep = make_dep("mypkg", tmp_path)
        symbols = self.extractor.extract(dep)
        assert symbols[0].file_path == "utils.py"

    def test_nested_module_file_path(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "mod.py").write_text("def deep() -> None: ...\n")
        dep = make_dep("mypkg", tmp_path)
        symbols = self.extractor.extract(dep)
        assert any("sub" in s.file_path for s in symbols)
