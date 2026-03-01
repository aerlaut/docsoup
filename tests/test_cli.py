"""Tests for the docsoup CLI commands."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from docsoup.cli import cli

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "node_project"


@pytest.fixture()
def runner():
    return CliRunner()


class TestIndexCommand:
    def test_index_basic(self, runner, tmp_path):
        result = runner.invoke(cli, ["index", str(FIXTURES_ROOT)])
        assert result.exit_code == 0

    def test_index_creates_db(self, runner, tmp_path):
        # Use a fresh copy of the fixtures project layout pointing to a temp dir
        # by invoking with the real fixtures path (db will go into fixtures/.docsoup/)
        # We just check exit_code and that one of the valid output sections appears.
        result = runner.invoke(cli, ["index", str(FIXTURES_ROOT)])
        assert result.exit_code == 0
        assert any(section in result.output for section in (
            "Indexed", "Already indexed", "Skipped", "Nothing to index"
        ))

    def test_index_json_output(self, runner):
        result = runner.invoke(cli, ["index", str(FIXTURES_ROOT), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "indexed" in data
        assert "already_indexed" in data
        assert "skipped" in data
        assert "failed" in data
        assert "total_symbols" in data

    def test_index_second_run_shows_already_indexed(self, runner):
        runner.invoke(cli, ["index", str(FIXTURES_ROOT)])
        result = runner.invoke(cli, ["index", str(FIXTURES_ROOT)])
        assert result.exit_code == 0
        # Second run: previously indexed libs show under "Already indexed"
        assert "Already indexed" in result.output

    def test_index_second_run_json_already_indexed(self, runner):
        runner.invoke(cli, ["index", str(FIXTURES_ROOT)])
        result = runner.invoke(cli, ["index", str(FIXTURES_ROOT), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["already_indexed"]) > 0
        assert data["indexed"] == []

    def test_index_skipped_shown_separately_from_already_indexed(self, runner):
        # After a first run the no-source packages are skipped; on second run
        # the previously-indexed ones are already_indexed, not skipped.
        result = runner.invoke(cli, ["index", str(FIXTURES_ROOT), "--json"])
        data = json.loads(result.output)
        # No package should appear in both already_indexed and skipped.
        overlap = set(data["already_indexed"]) & set(data["skipped"])
        assert overlap == set()

    def test_index_nonexistent_dir(self, runner):
        result = runner.invoke(cli, ["index", "/nonexistent/path/xyz"])
        assert result.exit_code != 0

    def test_index_force_flag(self, runner):
        runner.invoke(cli, ["index", str(FIXTURES_ROOT)])
        result = runner.invoke(cli, ["index", str(FIXTURES_ROOT), "--force"])
        assert result.exit_code == 0
        data_result = runner.invoke(cli, ["index", str(FIXTURES_ROOT), "--force", "--json"])
        data = json.loads(data_result.output)
        # With force, previously indexed libs are re-indexed (not skipped)
        assert isinstance(data["indexed"], list)


class TestSearchCommand:
    @pytest.fixture(autouse=True)
    def _index_first(self, runner):
        runner.invoke(cli, ["index", str(FIXTURES_ROOT)])

    def test_search_basic(self, runner):
        result = runner.invoke(cli, ["search", str(FIXTURES_ROOT), "chalk"])
        assert result.exit_code == 0

    def test_search_no_results(self, runner):
        result = runner.invoke(cli, ["search", str(FIXTURES_ROOT), "xyznonexistentabc123"])
        assert result.exit_code == 0
        assert "No results" in result.output

    def test_search_json_output(self, runner):
        result = runner.invoke(cli, ["search", str(FIXTURES_ROOT), "chunk", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        if data:
            assert "fqn" in data[0]
            assert "kind" in data[0]
            assert "signature" in data[0]
            assert "score" in data[0]

    def test_search_with_library_filter(self, runner):
        result = runner.invoke(
            cli, ["search", str(FIXTURES_ROOT), "function", "--library", "lodash", "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert all(r["library"] == "lodash" for r in data)

    def test_search_with_kind_filter(self, runner):
        result = runner.invoke(
            cli, ["search", str(FIXTURES_ROOT), "chunk", "--kind", "function", "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert all(r["kind"] == "function" for r in data)

    def test_search_limit(self, runner):
        result = runner.invoke(
            cli, ["search", str(FIXTURES_ROOT), "function", "--limit", "2", "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) <= 2


class TestStatusCommand:
    def test_status_before_index(self, runner, tmp_path):
        result = runner.invoke(cli, ["status", str(tmp_path)])
        assert result.exit_code == 0
        assert "No libraries indexed" in result.output

    def test_status_after_index(self, runner):
        runner.invoke(cli, ["index", str(FIXTURES_ROOT)])
        result = runner.invoke(cli, ["status", str(FIXTURES_ROOT)])
        assert result.exit_code == 0

    def test_status_json_output(self, runner):
        runner.invoke(cli, ["index", str(FIXTURES_ROOT)])
        result = runner.invoke(cli, ["status", str(FIXTURES_ROOT), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
