"""Tests for SearchEngine — integration tests using real fixtures."""

from pathlib import Path

import pytest

from docsoup.discovery.node import NodeDiscoverer
from docsoup.indexing.sqlite_index import SqliteIndex
from docsoup.models import Dependency, Symbol
from docsoup.parsing.typescript import TypeScriptExtractor
from docsoup.search.engine import SearchEngine

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "node_project"


@pytest.fixture()
def engine() -> SearchEngine:
    return SearchEngine(
        discoverer=NodeDiscoverer(),
        extractors=[TypeScriptExtractor()],
        index=SqliteIndex(db_path=":memory:"),
    )


class TestIndexProject:
    def test_indexes_packages_with_dts(self, engine):
        report = engine.index_project(FIXTURES_ROOT)
        assert "chalk" in report.indexed or "lodash" in report.indexed

    def test_skips_packages_without_dts(self, engine):
        report = engine.index_project(FIXTURES_ROOT)
        # typescript fixture has no .d.ts file — no extractor matches it
        assert "typescript" in report.skipped
        assert "typescript" not in report.already_indexed

    def test_returns_symbol_count(self, engine):
        report = engine.index_project(FIXTURES_ROOT)
        assert report.total_symbols > 0

    def test_incremental_already_indexed(self, engine):
        engine.index_project(FIXTURES_ROOT)
        report2 = engine.index_project(FIXTURES_ROOT)
        # Second run: already-indexed libs go to already_indexed, not skipped.
        assert report2.indexed == []
        assert len(report2.already_indexed) > 0

    def test_incremental_already_indexed_not_in_skipped(self, engine):
        first = engine.index_project(FIXTURES_ROOT)
        report2 = engine.index_project(FIXTURES_ROOT)
        # Packages indexed on the first run must not appear in skipped on the second.
        for name in first.indexed:
            assert name not in report2.skipped
            assert name in report2.already_indexed

    def test_force_reindexes(self, engine):
        engine.index_project(FIXTURES_ROOT)
        report2 = engine.index_project(FIXTURES_ROOT, force=True)
        # Second run with force: same packages re-indexed.
        assert len(report2.indexed) > 0

    def test_failed_packages_reported(self, tmp_path):
        """An extractor that raises an exception should be recorded in failed."""
        from docsoup.discovery.base import DependencyDiscoverer
        from docsoup.parsing.base import SymbolExtractor

        class BrokenDiscoverer(DependencyDiscoverer):
            def discover(self, root):
                return [Dependency("broken", "1.0.0", root / "nonexistent", "node")]

        class BrokenExtractor(SymbolExtractor):
            def can_extract(self, dep):
                return True
            def extract(self, dep):
                raise RuntimeError("intentional failure")

        eng = SearchEngine(
            discoverer=BrokenDiscoverer(),
            extractors=[BrokenExtractor()],
            index=SqliteIndex(db_path=":memory:"),
        )
        report = eng.index_project(tmp_path)
        assert len(report.failed) == 1
        assert report.failed[0][0] == "broken"

    def test_empty_project_returns_empty_report(self, engine, tmp_path):
        report = engine.index_project(tmp_path)
        assert report.indexed == []
        assert report.already_indexed == []
        assert report.skipped == []
        assert report.failed == []


class TestSearch:
    @pytest.fixture(autouse=True)
    def populated_engine(self, engine):
        engine.index_project(FIXTURES_ROOT)
        self.engine = engine

    def test_search_returns_results(self):
        results = self.engine.search("chalk")
        assert len(results) > 0

    def test_search_filter_by_library(self):
        results = self.engine.search("function", library="chalk")
        assert all(r.symbol.library == "chalk" for r in results)

    def test_search_filter_by_kind(self):
        results = self.engine.search("function", kind="interface")
        assert all(r.symbol.kind == "interface" for r in results)

    def test_search_no_match_returns_empty(self):
        results = self.engine.search("xyznonexistent12345")
        assert results == []


class TestStatus:
    def test_status_empty_before_indexing(self, engine):
        libs = engine.status()
        assert libs == []

    def test_status_after_indexing(self, engine):
        engine.index_project(FIXTURES_ROOT)
        libs = engine.status()
        assert len(libs) > 0
        lib_names = {lib["name"] for lib in libs}
        assert "chalk" in lib_names or "lodash" in lib_names

    def test_status_has_required_fields(self, engine):
        engine.index_project(FIXTURES_ROOT)
        libs = engine.status()
        for lib in libs:
            assert "name" in lib
            assert "version" in lib
            assert "symbol_count" in lib
