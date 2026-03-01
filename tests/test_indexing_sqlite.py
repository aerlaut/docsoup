"""Tests for SqliteIndex."""

import pytest

from docsoup.indexing.sqlite_index import SqliteIndex
from docsoup.models import Symbol


def make_symbol(
    name: str = "myFunc",
    library: str = "mylib",
    version: str = "1.0.0",
    kind: str = "function",
    signature: str = "",
    docstring: str | None = None,
) -> Symbol:
    sig = signature or f"function {name}(): void"
    return Symbol(
        name=name,
        fqn=f"{library}:{name}",
        library=library,
        library_version=version,
        kind=kind,
        signature=sig,
        source=sig,
        file_path="index.d.ts",
        line_number=1,
        docstring=docstring,
    )


@pytest.fixture()
def index() -> SqliteIndex:
    """In-memory SQLite index, fresh for each test."""
    idx = SqliteIndex(db_path=":memory:")
    yield idx
    idx.close()


class TestAddAndRetrieve:
    def test_add_and_search_basic(self, index):
        index.add_symbols([make_symbol("createRouter")])
        results = index.search("createRouter")
        assert len(results) == 1
        assert results[0].symbol.name == "createRouter"

    def test_score_is_positive(self, index):
        index.add_symbols([make_symbol("createRouter")])
        results = index.search("createRouter")
        assert results[0].score > 0

    def test_search_by_partial_name(self, index):
        index.add_symbols([make_symbol("createRouter"), make_symbol("createHandler")])
        results = index.search("create")
        names = {r.symbol.name for r in results}
        assert "createRouter" in names
        assert "createHandler" in names

    def test_search_in_docstring(self, index):
        sym = make_symbol("useState", docstring="React hook for managing state")
        index.add_symbols([sym])
        results = index.search("managing state")
        assert any(r.symbol.name == "useState" for r in results)

    def test_search_in_signature(self, index):
        sym = make_symbol("chunk", signature="function chunk<T>(array: T[], size: number): T[][]")
        index.add_symbols([sym])
        results = index.search("chunk array")
        assert any(r.symbol.name == "chunk" for r in results)

    def test_returns_empty_for_no_match(self, index):
        index.add_symbols([make_symbol("createRouter")])
        results = index.search("nonexistentxyzabc")
        assert results == []

    def test_empty_query_returns_empty(self, index):
        index.add_symbols([make_symbol("createRouter")])
        assert index.search("") == []
        assert index.search("   ") == []


class TestFiltering:
    def test_filter_by_library(self, index):
        index.add_symbols([make_symbol("fn", library="libA")])
        index.add_symbols([make_symbol("fn", library="libB")])
        results = index.search("fn", library="libA")
        assert all(r.symbol.library == "libA" for r in results)

    def test_filter_by_kind(self, index):
        index.add_symbols([
            make_symbol("MyClass", kind="class"),
            make_symbol("myFunc", kind="function"),
        ])
        results = index.search("my", kind="class")
        assert all(r.symbol.kind == "class" for r in results)

    def test_filter_by_library_and_kind(self, index):
        index.add_symbols([
            make_symbol("MyClass", library="libA", kind="class"),
            make_symbol("myFunc", library="libA", kind="function"),
            make_symbol("MyClass", library="libB", kind="class"),
        ])
        results = index.search("my", library="libA", kind="class")
        assert len(results) == 1
        assert results[0].symbol.library == "libA"
        assert results[0].symbol.kind == "class"


class TestRanking:
    def test_more_relevant_result_ranks_higher(self, index):
        """Exact name match should rank above a match only in source."""
        index.add_symbols([
            make_symbol(
                "useState",
                signature="function useState(): void",
                docstring="Some hook",
            ),
            make_symbol(
                "unrelated",
                signature="function unrelated(useState: string): void",
                docstring=None,
            ),
        ])
        results = index.search("useState")
        assert results[0].symbol.name == "useState"

    def test_limit_is_respected(self, index):
        symbols = [make_symbol(f"func{i}") for i in range(20)]
        index.add_symbols(symbols)
        results = index.search("func", limit=5)
        assert len(results) <= 5


class TestClear:
    def test_clear_all(self, index):
        index.add_symbols([make_symbol("fn", library="libA")])
        index.add_symbols([make_symbol("fn", library="libB")])
        index.clear()
        assert index.search("fn") == []
        assert index.get_indexed_libraries() == []

    def test_clear_specific_library(self, index):
        index.add_symbols([make_symbol("fn", library="libA")])
        index.add_symbols([make_symbol("fn", library="libB")])
        index.clear(library="libA")
        results = index.search("fn")
        assert all(r.symbol.library == "libB" for r in results)

    def test_clear_removes_from_metadata(self, index):
        index.add_symbols([make_symbol("fn", library="libA")])
        index.clear(library="libA")
        libs = index.get_indexed_libraries()
        assert not any(lib["name"] == "libA" for lib in libs)


class TestMetadata:
    def test_get_indexed_libraries(self, index):
        index.add_symbols([make_symbol("fn", library="express", version="4.18.0")])
        libs = index.get_indexed_libraries()
        assert len(libs) == 1
        assert libs[0]["name"] == "express"
        assert libs[0]["version"] == "4.18.0"
        assert libs[0]["symbol_count"] == 1

    def test_symbol_count_is_accurate(self, index):
        syms = [make_symbol(f"fn{i}") for i in range(5)]
        index.add_symbols(syms)
        libs = index.get_indexed_libraries()
        assert libs[0]["symbol_count"] == 5

    def test_is_library_indexed_true(self, index):
        index.add_symbols([make_symbol("fn", library="react", version="18.2.0")])
        assert index.is_library_indexed("react", "18.2.0") is True

    def test_is_library_indexed_false_wrong_version(self, index):
        index.add_symbols([make_symbol("fn", library="react", version="18.2.0")])
        assert index.is_library_indexed("react", "17.0.0") is False

    def test_is_library_indexed_false_unknown(self, index):
        assert index.is_library_indexed("nonexistent", "1.0.0") is False


class TestUpsert:
    def test_re_adding_library_replaces_symbols(self, index):
        """Adding symbols for an already-indexed library replaces, not appends."""
        index.add_symbols([make_symbol("oldFunc", library="mylib", version="1.0.0")])
        index.add_symbols([make_symbol("newFunc", library="mylib", version="2.0.0")])
        results = index.search("Func")
        names = {r.symbol.name for r in results}
        assert "newFunc" in names
        assert "oldFunc" not in names

    def test_upsert_updates_symbol_count(self, index):
        index.add_symbols([make_symbol("fn1", library="mylib", version="1.0.0")])
        index.add_symbols(
            [make_symbol("fn1", library="mylib", version="2.0.0"),
             make_symbol("fn2", library="mylib", version="2.0.0")]
        )
        libs = index.get_indexed_libraries()
        assert libs[0]["symbol_count"] == 2


class TestPersistence:
    def test_data_persists_to_disk(self, tmp_path):
        db_path = tmp_path / "test.db"
        idx = SqliteIndex(db_path=db_path)
        idx.add_symbols([make_symbol("persistedFunc")])
        idx.close()

        idx2 = SqliteIndex(db_path=db_path)
        results = idx2.search("persistedFunc")
        assert len(results) == 1
        idx2.close()
