"""tomd: a local wrapper around MarkItDown."""

from __future__ import annotations

__all__ = ["__version__"]


def __getattr__(name: str) -> str:
    """Resolve ``__version__`` on first access.

    Reading the installed version costs an ``importlib.metadata`` import, about
    20 ms of the CLI's 53 ms startup, and only ``--version`` ever needs it.
    Deferring it keeps that cost off every ordinary conversion.

    Args:
        name: Attribute being looked up.

    Returns:
        The distribution version, or ``0.0.0+unknown`` when tomd is being run
        from a source tree rather than an installed distribution.

    Raises:
        AttributeError: For any other attribute name.
    """
    if name == "__version__":
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("tomd")
        except PackageNotFoundError:  # pragma: no cover - only from a source tree
            return "0.0.0+unknown"
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
