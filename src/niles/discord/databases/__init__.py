"""Database protocols and implementations."""

from typing import Protocol


class Readable[QT, RT](Protocol):
    """Read protocol — query yields a result."""

    def read(self, query: QT) -> RT:
        """Read by query and return a result."""
        ...


class Writable[VT, RT](Protocol):
    """Write protocol — store a value and return a result."""

    def write(self, value: VT) -> RT:
        """Write a value and return a result."""
        ...


class Deletable[QT, RT](Protocol):
    """Delete protocol — remove by query and return a result."""

    def delete(self, query: QT) -> RT:
        """Delete by query and return a result."""
        ...


class Updatable[QT, VT, RT](Protocol):
    """Update protocol — update value by query and return a result."""

    def update(self, query: QT, value: VT) -> RT:
        """Update value by query and return a result."""
        ...
