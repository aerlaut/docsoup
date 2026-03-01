"""Abstract base class for symbol extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod

from docsoup.models import Dependency, Symbol


class SymbolExtractor(ABC):
    """
    Parses the source files of a dependency and extracts indexable symbols.

    Implement this class to add support for a new language or file type
    (e.g. Python source, Rust crate, JSDoc from .js files).
    """

    @abstractmethod
    def can_extract(self, dependency: Dependency) -> bool:
        """
        Return True if this extractor can handle the given dependency.

        This allows multiple extractors to be registered and selected
        automatically based on ecosystem or file availability.
        """

    @abstractmethod
    def extract(self, dependency: Dependency) -> list[Symbol]:
        """
        Parse the dependency's source files and return extracted symbols.

        Args:
            dependency: The resolved dependency to parse.

        Returns:
            A list of :class:`~docsoup.models.Symbol` objects. Returns an
            empty list when no parseable files are found.
        """
