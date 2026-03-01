"""SQLite FTS5 index backend — BM25-ranked full-text search over symbols."""

from __future__ import annotations

import sqlite3
import logging
from pathlib import Path

from docsoup.indexing.base import Index
from docsoup.models import SearchResult, Symbol

logger = logging.getLogger(__name__)

# Schema version — bump this when the schema changes to trigger a full rebuild.
_SCHEMA_VERSION = 1

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS indexed_libraries (
    name          TEXT NOT NULL,
    version       TEXT NOT NULL,
    symbol_count  INTEGER NOT NULL DEFAULT 0,
    indexed_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (name, version)
);

CREATE TABLE IF NOT EXISTS symbols (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    library         TEXT NOT NULL,
    library_version TEXT NOT NULL,
    name            TEXT NOT NULL,
    fqn             TEXT NOT NULL,
    kind            TEXT NOT NULL,
    signature       TEXT NOT NULL,
    source          TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    line_number     INTEGER NOT NULL,
    docstring       TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    name,
    fqn,
    signature,
    docstring,
    source,
    content='symbols',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 1'
);

-- Keep FTS in sync with the symbols table.
CREATE TRIGGER IF NOT EXISTS symbols_ai AFTER INSERT ON symbols BEGIN
    INSERT INTO symbols_fts(rowid, name, fqn, signature, docstring, source)
    VALUES (new.id, new.name, new.fqn, new.signature, new.docstring, new.source);
END;

CREATE TRIGGER IF NOT EXISTS symbols_ad AFTER DELETE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, name, fqn, signature, docstring, source)
    VALUES ('delete', old.id, old.name, old.fqn, old.signature, old.docstring, old.source);
END;
"""


class SqliteIndex(Index):
    """
    Persistent BM25 full-text search index backed by a SQLite FTS5 virtual table.

    The database is stored at ``<db_path>`` (a file path).  Pass
    ``db_path=":memory:"`` for an in-memory database (useful in tests).

    The FTS5 index covers: symbol name, FQN, signature, docstring, source.
    Results are ranked by BM25 (lower raw score = higher relevance in SQLite).
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn = self._connect()
        self._apply_schema()

    # ------------------------------------------------------------------
    # Index interface
    # ------------------------------------------------------------------

    def add_symbols(self, symbols: list[Symbol]) -> None:
        if not symbols:
            return

        # Determine the library from the first symbol; all symbols in a batch
        # are expected to share the same library (upsert semantics: clear first).
        library = symbols[0].library
        version = symbols[0].library_version
        self.clear(library)

        rows = [
            (
                s.library,
                s.library_version,
                s.name,
                s.fqn,
                s.kind,
                s.signature,
                s.source,
                s.file_path,
                s.line_number,
                s.docstring,
            )
            for s in symbols
        ]

        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO symbols
                    (library, library_version, name, fqn, kind,
                     signature, source, file_path, line_number, docstring)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self._conn.execute(
                """
                INSERT INTO indexed_libraries (name, version, symbol_count)
                VALUES (?, ?, ?)
                ON CONFLICT(name, version) DO UPDATE SET
                    symbol_count = excluded.symbol_count,
                    indexed_at   = datetime('now')
                """,
                (library, version, len(symbols)),
            )

        logger.debug("Indexed %d symbols for %s@%s", len(symbols), library, version)

    def search(
        self,
        query: str,
        *,
        library: str | None = None,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        if not query or not query.strip():
            return []

        # Build WHERE clause extensions.
        filters: list[str] = []
        params: list = []

        if library:
            filters.append("s.library = ?")
            params.append(library)
        if kind:
            filters.append("s.kind = ?")
            params.append(kind)

        filter_sql = ("AND " + " AND ".join(filters)) if filters else ""

        # FTS5 MATCH with BM25 ranking.  SQLite BM25 returns negative values;
        # we negate to get a positive score where higher = more relevant.
        sql = f"""
            SELECT
                s.library, s.library_version, s.name, s.fqn, s.kind,
                s.signature, s.source, s.file_path, s.line_number, s.docstring,
                -bm25(symbols_fts) AS score
            FROM symbols_fts
            JOIN symbols s ON s.id = symbols_fts.rowid
            WHERE symbols_fts MATCH ?
            {filter_sql}
            ORDER BY score DESC
            LIMIT ?
        """

        try:
            cur = self._conn.execute(sql, [self._fts_query(query)] + params + [limit])
        except sqlite3.OperationalError as exc:
            # Invalid FTS query syntax — return empty rather than crashing.
            logger.warning("FTS query error for %r: %s", query, exc)
            return []

        results: list[SearchResult] = []
        for row in cur.fetchall():
            (lib, lib_ver, name, fqn, kind_val,
             sig, src, fp, ln, doc, score) = row

            sym = Symbol(
                name=name,
                fqn=fqn,
                library=lib,
                library_version=lib_ver,
                kind=kind_val,
                signature=sig,
                source=src,
                file_path=fp,
                line_number=ln,
                docstring=doc,
            )
            results.append(SearchResult(symbol=sym, score=score))

        return results

    def clear(self, library: str | None = None) -> None:
        with self._conn:
            if library is None:
                self._conn.execute("DELETE FROM symbols")
                self._conn.execute("DELETE FROM indexed_libraries")
            else:
                self._conn.execute("DELETE FROM symbols WHERE library = ?", (library,))
                self._conn.execute("DELETE FROM indexed_libraries WHERE name = ?", (library,))

    def get_indexed_libraries(self) -> list[dict]:
        cur = self._conn.execute(
            "SELECT name, version, symbol_count, indexed_at FROM indexed_libraries ORDER BY name"
        )
        return [
            {
                "name": row[0],
                "version": row[1],
                "symbol_count": row[2],
                "indexed_at": row[3],
            }
            for row in cur.fetchall()
        ]

    def is_library_indexed(self, name: str, version: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM indexed_libraries WHERE name = ? AND version = ?",
            (name, version),
        )
        return cur.fetchone() is not None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _apply_schema(self) -> None:
        with self._conn:
            self._conn.executescript(_DDL)
            # Record schema version.
            self._conn.execute(
                "INSERT OR IGNORE INTO schema_meta VALUES ('version', ?)",
                (str(_SCHEMA_VERSION),),
            )

    @staticmethod
    def _fts_query(raw: str) -> str:
        """
        Convert a plain text query into an FTS5 query string.

        Each whitespace-separated token is searched as a prefix match so that
        partial words still find results (e.g. "useState" matches "useStateful").
        Tokens containing FTS5 special characters are quoted.
        """
        tokens = raw.strip().split()
        parts: list[str] = []
        for token in tokens:
            # Quote tokens that look like they contain special FTS5 chars.
            if any(c in token for c in ('"', "'", "*", ":", "-", "^", "+")):
                parts.append(f'"{token}"')
            else:
                parts.append(f'"{token}"*')
        return " ".join(parts)

    def close(self) -> None:
        """Explicitly close the database connection."""
        self._conn.close()
