"""Tests for the docsoup CLI commands."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from docsoup.cli import cli

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "node_project"
PYTHON_FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "python_project"


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


# ---------------------------------------------------------------------------
# --ecosystem flag
# ---------------------------------------------------------------------------

class TestEcosystemFlag:
    """Tests for the --ecosystem / -e option on index, search, and status."""

    # --- index: default is still node ---

    def test_index_default_ecosystem_is_node(self, runner):
        result = runner.invoke(cli, ["index", str(FIXTURES_ROOT), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        # Node fixture has known packages; result structure is valid
        assert "indexed" in data

    def test_index_explicit_node_ecosystem(self, runner):
        result = runner.invoke(cli, ["index", str(FIXTURES_ROOT), "--ecosystem", "node", "--json"])
        assert result.exit_code == 0

    # --- index: python ecosystem ---

    def test_index_python_ecosystem_succeeds(self, runner):
        result = runner.invoke(
            cli, ["index", str(PYTHON_FIXTURES_ROOT), "--ecosystem", "python", "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "indexed" in data

    def test_index_python_ecosystem_short_flag(self, runner):
        result = runner.invoke(
            cli, ["index", str(PYTHON_FIXTURES_ROOT), "-e", "python", "--json"]
        )
        assert result.exit_code == 0

    def test_index_python_discovers_packages(self, runner):
        result = runner.invoke(
            cli, ["index", str(PYTHON_FIXTURES_ROOT), "--ecosystem", "python", "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        all_names = data["indexed"] + data["already_indexed"] + data["skipped"]
        # requests and click are installed in the fixture's .venv
        assert any(name.lower() in ("requests", "click") for name in all_names)

    def test_index_python_raises_without_venv(self, runner, tmp_path):
        """A Python project without a .venv raises a clear error."""
        (tmp_path / "requirements.txt").write_text("requests\n")
        result = runner.invoke(
            cli, ["index", str(tmp_path), "--ecosystem", "python"]
        )
        # RuntimeError from PythonDiscoverer propagates as a non-zero exit or error output
        assert result.exit_code != 0 or "venv" in result.output.lower() or (
            result.exception is not None
        )

    # --- invalid ecosystem value ---

    def test_index_invalid_ecosystem_rejected(self, runner):
        result = runner.invoke(
            cli, ["index", str(FIXTURES_ROOT), "--ecosystem", "rust"]
        )
        assert result.exit_code != 0

    # --- search: ecosystem flag forwarded ---

    def test_search_accepts_ecosystem_flag(self, runner):
        runner.invoke(cli, ["index", str(FIXTURES_ROOT)])
        result = runner.invoke(
            cli, ["search", str(FIXTURES_ROOT), "chunk", "--ecosystem", "node", "--json"]
        )
        assert result.exit_code == 0

    def test_search_invalid_ecosystem_rejected(self, runner):
        result = runner.invoke(
            cli, ["search", str(FIXTURES_ROOT), "chunk", "--ecosystem", "cobol"]
        )
        assert result.exit_code != 0

    # --- status: ecosystem flag forwarded ---

    def test_status_accepts_ecosystem_flag(self, runner):
        runner.invoke(cli, ["index", str(FIXTURES_ROOT)])
        result = runner.invoke(
            cli, ["status", str(FIXTURES_ROOT), "--ecosystem", "node"]
        )
        assert result.exit_code == 0

    def test_status_invalid_ecosystem_rejected(self, runner):
        result = runner.invoke(
            cli, ["status", str(FIXTURES_ROOT), "--ecosystem", "brainfuck"]
        )
        assert result.exit_code != 0
