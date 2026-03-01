"""Tests for shared data models."""

from pathlib import Path

from docsoup.models import Dependency, IndexReport, SearchResult, Symbol


def make_symbol(**kwargs) -> Symbol:
    defaults = dict(
        name="myFunc",
        fqn="mylib:myFunc",
        library="mylib",
        library_version="1.0.0",
        kind="function",
        signature="function myFunc(): void",
        source="function myFunc(): void {}",
        file_path="index.d.ts",
        line_number=1,
        docstring=None,
    )
    defaults.update(kwargs)
    return Symbol(**defaults)


class TestDependency:
    def test_fields(self):
        dep = Dependency(name="react", version="18.2.0", path=Path("/tmp/react"))
        assert dep.name == "react"
        assert dep.version == "18.2.0"
        assert dep.path == Path("/tmp/react")
        assert dep.ecosystem == "node"

    def test_custom_ecosystem(self):
        dep = Dependency(name="serde", version="1.0", path=Path("/tmp/serde"), ecosystem="rust")
        assert dep.ecosystem == "rust"


class TestSymbol:
    def test_fields(self):
        sym = make_symbol()
        assert sym.name == "myFunc"
        assert sym.fqn == "mylib:myFunc"
        assert sym.library == "mylib"
        assert sym.library_version == "1.0.0"
        assert sym.kind == "function"
        assert sym.docstring is None

    def test_with_docstring(self):
        sym = make_symbol(docstring="Does something useful.")
        assert sym.docstring == "Does something useful."


class TestSearchResult:
    def test_fields(self):
        sym = make_symbol()
        result = SearchResult(symbol=sym, score=0.9)
        assert result.symbol is sym
        assert result.score == 0.9


class TestIndexReport:
    def test_defaults(self):
        report = IndexReport()
        assert report.indexed == []
        assert report.already_indexed == []
        assert report.skipped == []
        assert report.failed == []
        assert report.total_symbols == 0

    def test_already_indexed_field(self):
        report = IndexReport(already_indexed=["react", "express"])
        assert report.already_indexed == ["react", "express"]
        assert report.skipped == []

    def test_skipped_field(self):
        report = IndexReport(skipped=["some-css-pkg"])
        assert report.skipped == ["some-css-pkg"]
        assert report.already_indexed == []

    def test_already_indexed_and_skipped_are_independent(self):
        report = IndexReport(already_indexed=["react"], skipped=["some-css-pkg"])
        assert report.already_indexed == ["react"]
        assert report.skipped == ["some-css-pkg"]

    def test_with_data(self):
        report = IndexReport(
            indexed=["express"],
            already_indexed=["react"],
            skipped=["some-css-pkg"],
            failed=[("broken-pkg", "parse error")],
            total_symbols=42,
        )
        assert report.indexed == ["express"]
        assert report.already_indexed == ["react"]
        assert report.skipped == ["some-css-pkg"]
        assert report.failed[0] == ("broken-pkg", "parse error")
        assert report.total_symbols == 42
