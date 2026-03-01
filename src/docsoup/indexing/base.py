"""Abstract base class for index backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

from docsoup.models import SearchResult, Symbol


class Index(ABC):
    """
    Stores symbols and answers search queries.

    Implement this class to add a new backend (e.g. vector embeddings,
    hybrid BM25+vector, remote search service).
    """

    @abstractmethod
    def add_symbols(self, symbols: list[Symbol]) -> None:
        """
        Persist *symbols* into the index.

        Calling this for a library that is already indexed should replace the
        existing entries for that library (upsert semantics).

        Args:
            symbols: Symbols to store. All symbols in a batch typically belong
                     to the same library, but this is not required.
        """

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        library: str | None = None,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """
        Search the index and return ranked results.

        Args:
            query:   Natural-language or keyword query string.
            library: Optional filter — only return symbols from this package.
            kind:    Optional filter — one of 'function', 'class', 'interface',
                     'type', 'enum', 'variable', 'module'.
            limit:   Maximum number of results to return.

        Returns:
            A list of :class:`~docsoup.models.SearchResult` sorted by
            descending relevance score.
        """

    @abstractmethod
    def clear(self, library: str | None = None) -> None:
        """
        Remove symbols from the index.

        Args:
            library: If given, remove only symbols belonging to this package.
                     If None, clear the entire index.
        """

    @abstractmethod
    def get_indexed_libraries(self) -> list[dict]:
        """
        Return metadata for all currently indexed libraries.

        Each dict contains at minimum:
            - ``name``         (str)  package name
            - ``version``      (str)  indexed version
            - ``symbol_count`` (int)  number of symbols stored
        """

    @abstractmethod
    def is_library_indexed(self, name: str, version: str) -> bool:
        """
        Return True if *name* at *version* is already present in the index.

        Used by the engine to skip unchanged libraries on incremental re-index.
        """
