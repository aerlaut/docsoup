"""Module that defines __all__ to explicitly control exports."""

__all__ = ["PublicClass", "public_func", "CONSTANT"]

CONSTANT: str = "exported"
_HIDDEN: str = "not exported"
NOT_IN_ALL: str = "also not exported"


def public_func(x: int) -> str:
    """A publicly exported function."""
    return str(x)


def unlisted_func() -> None:
    """Not in __all__ — should be excluded."""


class PublicClass:
    """A class listed in __all__."""

    def method(self) -> None:
        """Public method."""

    def _private_method(self) -> None:
        """Private method — excluded."""


class UnlistedClass:
    """Not in __all__ — should be excluded."""
