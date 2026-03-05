"""A simple module for testing Python symbol extraction."""

from __future__ import annotations

VERSION: str = "1.0.0"
_PRIVATE_CONST: int = 42

MAX_RETRIES: int = 3


def add(x: int, y: int) -> int:
    """Add two numbers together.

    Args:
        x: First operand.
        y: Second operand.

    Returns:
        The sum of x and y.
    """
    return x + y


def subtract(x: int, y: int) -> int:
    """Subtract y from x."""
    return x - y


def _private_helper() -> None:
    """This should not be exported (starts with _)."""


async def fetch(url: str, timeout: float = 30.0) -> bytes:
    """Fetch content from a URL asynchronously."""
    ...


class EventEmitter:
    """A simple event emitter class."""

    def __init__(self, max_listeners: int = 10) -> None:
        """Initialise the emitter with a listener cap."""
        self._listeners: dict = {}
        self._max = max_listeners

    def on(self, event: str, callback) -> None:
        """Register a callback for an event."""
        ...

    def off(self, event: str, callback) -> None:
        """Remove a callback from an event."""
        ...

    def emit(self, event: str, *args) -> None:
        """Emit an event, calling all registered callbacks."""
        ...

    def _internal(self) -> None:
        """Private method — should not be emitted as a symbol."""


class _PrivateClass:
    """This class should be excluded (starts with _)."""

    def method(self) -> None:
        ...
