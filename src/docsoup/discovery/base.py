"""Abstract base class for dependency discoverers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from docsoup.models import Dependency


class DependencyDiscoverer(ABC):
    """
    Discovers the dependencies of a project and resolves their locations on disk.

    Implement this class to add support for a new ecosystem (e.g. Python, Rust).
    """

    @abstractmethod
    def discover(self, project_root: Path) -> list[Dependency]:
        """
        Read the project manifest at *project_root* and return resolved dependencies.

        Args:
            project_root: Absolute path to the root of the project being analysed.

        Returns:
            A list of :class:`~docsoup.models.Dependency` objects. Returns an empty
            list when no recognised manifest exists.
        """
