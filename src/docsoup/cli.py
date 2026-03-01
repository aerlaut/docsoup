"""Command-line interface for docsoup."""

from __future__ import annotations

import json as _json
import logging
import sys
from pathlib import Path

import click

from docsoup.discovery.node import NodeDiscoverer
from docsoup.indexing.sqlite_index import SqliteIndex
from docsoup.parsing.javascript import JavaScriptExtractor
from docsoup.parsing.typescript import TypeScriptExtractor
from docsoup.search.engine import SearchEngine

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_engine(project_root: Path) -> SearchEngine:
    """Build a SearchEngine wired to the default Node/TS/SQLite stack."""
    db_path = project_root / ".docsoup" / "index.db"
    return SearchEngine(
        discoverer=NodeDiscoverer(),
        extractors=[TypeScriptExtractor(), JavaScriptExtractor()],
        index=SqliteIndex(db_path=db_path),
    )


def _resolve_root(project_root: str) -> Path:
    path = Path(project_root).expanduser().resolve()
    if not path.is_dir():
        raise click.BadParameter(f"Not a directory: {path}", param_hint="PROJECT_ROOT")
    return path


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable verbose logging.")
def cli(verbose: bool) -> None:
    """docsoup — index and search dependency code for AI agents."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------

@cli.command("index")
@click.argument("project_root", default=".", metavar="PROJECT_ROOT")
@click.option("--force", "-f", is_flag=True, default=False,
              help="Re-index libraries that are already up-to-date.")
@click.option("--json", "output_json", is_flag=True, default=False,
              help="Output results as JSON.")
def index_cmd(project_root: str, force: bool, output_json: bool) -> None:
    """Index all dependencies of PROJECT_ROOT.

    Reads package.json, resolves node_modules, extracts symbols from TypeScript
    declaration files (.d.ts) or JavaScript source files, and stores them in
    .docsoup/index.db inside PROJECT_ROOT.

    \b
    Examples:
        docsoup index .
        docsoup index /path/to/my-app --force
    """
    root = _resolve_root(project_root)
    engine = _make_engine(root)
    report = engine.index_project(root, force=force)

    if output_json:
        click.echo(_json.dumps({
            "indexed": report.indexed,
            "skipped": report.skipped,
            "failed": [{"name": n, "error": e} for n, e in report.failed],
            "total_symbols": report.total_symbols,
        }, indent=2))
        return

    if report.indexed:
        click.echo(f"✓ Indexed ({report.total_symbols} symbols):")
        for name in report.indexed:
            click.echo(f"  • {name}")
    if report.skipped:
        click.echo(f"↷ Skipped (already indexed or no extractable source):")
        for name in report.skipped:
            click.echo(f"  • {name}")
    if report.failed:
        click.echo(f"✗ Failed:", err=True)
        for name, err in report.failed:
            click.echo(f"  • {name}: {err}", err=True)
    if not report.indexed and not report.failed:
        click.echo("Nothing to index.")


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

@cli.command("search")
@click.argument("project_root", metavar="PROJECT_ROOT")
@click.argument("query")
@click.option("--library", "-l", default=None,
              help="Restrict search to a specific package (e.g. 'react').")
@click.option("--kind", "-k", default=None,
              type=click.Choice(["function", "class", "interface", "type", "enum", "variable", "module"]),
              help="Filter by symbol kind.")
@click.option("--limit", "-n", default=10, show_default=True,
              help="Maximum number of results to return.")
@click.option("--json", "output_json", is_flag=True, default=False,
              help="Output results as JSON.")
def search_cmd(
    project_root: str,
    query: str,
    library: str | None,
    kind: str | None,
    limit: int,
    output_json: bool,
) -> None:
    """Search indexed dependency symbols for QUERY.

    \b
    Examples:
        docsoup search . "create router"
        docsoup search . "useState" --library react --kind function
        docsoup search . "middleware" --library express --limit 5 --json
    """
    root = _resolve_root(project_root)
    engine = _make_engine(root)
    results = engine.search(query, library=library, kind=kind, limit=limit)

    if output_json:
        click.echo(_json.dumps([
            {
                "fqn": r.symbol.fqn,
                "name": r.symbol.name,
                "library": r.symbol.library,
                "library_version": r.symbol.library_version,
                "kind": r.symbol.kind,
                "signature": r.symbol.signature,
                "docstring": r.symbol.docstring,
                "file_path": r.symbol.file_path,
                "line_number": r.symbol.line_number,
                "score": round(r.score, 4),
            }
            for r in results
        ], indent=2))
        return

    if not results:
        click.echo(f"No results for '{query}'.")
        return

    for i, r in enumerate(results, 1):
        sym = r.symbol
        click.echo(f"\n{'─' * 60}")
        click.echo(f"{i}. [{sym.kind.upper()}] {sym.fqn}  (score: {r.score:.4f})")
        click.echo(f"   {sym.library}@{sym.library_version}  {sym.file_path}:{sym.line_number}")
        click.echo(f"\n   {sym.signature}")
        if sym.docstring:
            # Indent and truncate long docstrings for readability.
            doc = sym.docstring[:300] + "…" if len(sym.docstring) > 300 else sym.docstring
            for line in doc.splitlines():
                click.echo(f"   // {line}")
    click.echo(f"\n{'─' * 60}")
    click.echo(f"\n{len(results)} result(s) for '{query}'.")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@cli.command("status")
@click.argument("project_root", default=".", metavar="PROJECT_ROOT")
@click.option("--json", "output_json", is_flag=True, default=False,
              help="Output as JSON.")
def status_cmd(project_root: str, output_json: bool) -> None:
    """Show which libraries are currently indexed for PROJECT_ROOT.

    \b
    Examples:
        docsoup status .
        docsoup status /path/to/my-app --json
    """
    root = _resolve_root(project_root)
    engine = _make_engine(root)
    libs = engine.status()

    if output_json:
        click.echo(_json.dumps(libs, indent=2))
        return

    if not libs:
        click.echo("No libraries indexed yet. Run `docsoup index <project_root>` first.")
        return

    click.echo(f"{'Library':<30} {'Version':<15} {'Symbols':>8}  Indexed at")
    click.echo("─" * 75)
    for lib in libs:
        click.echo(
            f"{lib['name']:<30} {lib['version']:<15} {lib['symbol_count']:>8}"
            f"  {lib.get('indexed_at', 'unknown')}"
        )
    total = sum(lib["symbol_count"] for lib in libs)
    click.echo("─" * 75)
    click.echo(f"{'Total':<30} {'':<15} {total:>8}")
