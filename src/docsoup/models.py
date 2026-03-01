"""Shared data models used across the docsoup pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Dependency:
    """A resolved project dependency with its location on disk."""

    name: str
    """Package name, e.g. 'react'."""

    version: str
    """Installed version string, e.g. '18.2.0'."""

    path: Path
    """Absolute path to the package directory on disk."""

    ecosystem: str = "node"
    """Originating ecosystem, e.g. 'node', 'python', 'rust'."""


@dataclass
class Symbol:
    """A code symbol extracted from a dependency."""

    name: str
    """Simple symbol name, e.g. 'useState'."""

    fqn: str
    """Fully-qualified name, e.g. 'react:useState' or 'react:Component.render'."""

    library: str
    """Package name this symbol belongs to, e.g. 'react'."""

    library_version: str
    """Version of the package, e.g. '18.2.0'."""

    kind: str
    """
    Symbol kind. One of:
      'function' | 'class' | 'interface' | 'type' | 'enum' | 'variable' | 'module'
    """

    signature: str
    """Full declaration text used as the primary search surface, e.g. the function signature."""

    source: str
    """Complete source text of the declaration (may equal signature for simple types)."""

    file_path: str
    """Path to the source file relative to the package root."""

    line_number: int
    """1-based line number of the declaration start."""

    docstring: str | None = None
    """Extracted JSDoc / documentation comment, if present."""


@dataclass
class SearchResult:
    """A ranked result returned by the search engine."""

    symbol: Symbol
    score: float
    """Relevance score (higher is better). Interpretation depends on the index backend."""


@dataclass
class IndexReport:
    """Summary of an indexing run."""

    indexed: list[str] = field(default_factory=list)
    """Libraries that were (re-)indexed."""

    skipped: list[str] = field(default_factory=list)
    """Libraries skipped because their version was already indexed."""

    failed: list[tuple[str, str]] = field(default_factory=list)
    """Libraries that failed to index, as (name, error_message) pairs."""

    total_symbols: int = 0
    """Total number of symbols added across all indexed libraries."""
