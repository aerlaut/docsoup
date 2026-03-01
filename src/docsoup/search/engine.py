"""Search engine — orchestrates discovery, parsing, and indexing."""

from __future__ import annotations

import logging
from pathlib import Path

from docsoup.discovery.base import DependencyDiscoverer
from docsoup.indexing.base import Index
from docsoup.models import IndexReport, SearchResult
from docsoup.parsing.base import SymbolExtractor

logger = logging.getLogger(__name__)


class SearchEngine:
    """
    Wires together a :class:`DependencyDiscoverer`, one or more
    :class:`SymbolExtractor` instances, and an :class:`Index` backend.

    Dependency injection keeps the engine decoupled from any specific
    ecosystem, parser, or storage technology.

    Args:
        discoverer:  Finds the project's dependencies.
        extractors:  Ordered list of extractors tried for each dependency.
                     The first extractor for which ``can_extract`` returns
                     True is used; the rest are skipped.
        index:       Storage and search backend.
    """

    def __init__(
        self,
        discoverer: DependencyDiscoverer,
        extractors: list[SymbolExtractor],
        index: Index,
    ) -> None:
        self._discoverer = discoverer
        self._extractors = extractors
        self._index = index

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_project(self, project_root: Path, *, force: bool = False) -> IndexReport:
        """
        Index all dependencies of the project at *project_root*.

        Dependencies whose name+version are already in the index are skipped
        unless *force* is True.

        Args:
            project_root: Absolute path to the project to analyse.
            force:        Re-index libraries that are already up-to-date.

        Returns:
            An :class:`~docsoup.models.IndexReport` summarising the run.
        """
        report = IndexReport()
        deps = self._discoverer.discover(project_root)

        if not deps:
            logger.info("No dependencies discovered in %s", project_root)
            return report

        for dep in deps:
            if not force and self._index.is_library_indexed(dep.name, dep.version):
                logger.debug("Skipping %s@%s (already indexed)", dep.name, dep.version)
                report.already_indexed.append(dep.name)
                continue

            extractor = self._find_extractor(dep)
            if extractor is None:
                logger.debug("No extractor for %s — skipping", dep.name)
                report.skipped.append(dep.name)
                continue

            try:
                symbols = extractor.extract(dep)
                if symbols:
                    self._index.add_symbols(symbols)
                    report.indexed.append(dep.name)
                    report.total_symbols += len(symbols)
                    logger.info(
                        "Indexed %s@%s (%d symbols)", dep.name, dep.version, len(symbols)
                    )
                else:
                    logger.debug("No symbols extracted from %s — skipping", dep.name)
                    report.skipped.append(dep.name)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to index %s: %s", dep.name, exc)
                report.failed.append((dep.name, str(exc)))

        return report

    def search(
        self,
        query: str,
        *,
        library: str | None = None,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """
        Search indexed symbols and return ranked results.

        Args:
            query:   Natural-language or keyword query.
            library: Optional filter — restrict to a specific package.
            kind:    Optional filter — one of 'function', 'class', etc.
            limit:   Maximum number of results.
        """
        return self._index.search(query, library=library, kind=kind, limit=limit)

    def status(self) -> list[dict]:
        """
        Return metadata for all currently indexed libraries.

        Each dict has: ``name``, ``version``, ``symbol_count``, ``indexed_at``.
        """
        return self._index.get_indexed_libraries()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_extractor(self, dep) -> SymbolExtractor | None:
        for extractor in self._extractors:
            if extractor.can_extract(dep):
                return extractor
        return None
