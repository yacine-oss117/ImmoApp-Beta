"""
Database access protocols for the matcher engine.

These protocols define the contract for database access without coupling
the matcher to any specific database implementation.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Protocol, TypeVar

# Type alias for a generic database row supporting dict-like access
Row = dict[str, object]
S = TypeVar("S", bound="DbSession")


class DbSession(Protocol):
    """
    Protocol for database session operations.

    Wraps a database connection/cursor and provides query execution.
    Implementations must handle row factory for dict-like access.
    """

    def execute(self: S, sql: str, params: Sequence[object] = ()) -> S:
        """Execute a SQL statement with optional parameters."""
        ...

    def executemany(self: S, sql: str, params: Iterable[Sequence[object]]) -> S:
        """Execute a SQL statement against multiple sequences of parameters."""
        ...

    def fetchone(self) -> Row | None:
        """Fetch the next row from the result set."""
        ...

    def fetchall(self) -> list[Row]:
        """Fetch all remaining rows from the result set."""
        ...

    def fetchmany(self, size: int) -> list[Row]:
        """Fetch up to ``size`` rows from the result set."""
        ...

    def commit(self) -> None:
        """Commit the current transaction."""
        ...

    def rollback(self) -> None:
        """Rollback the current transaction."""
        ...

    @property
    def lastrowid(self) -> int | None:
        """Return the last inserted row ID."""
        ...

    @property
    def rowcount(self) -> int:
        """Return the number of rows affected by the last execute."""
        ...


class UnitOfWork(Protocol):
    """
    Protocol for unit of work pattern - manages transaction boundaries.

    Provides atomic transaction context for database operations.
    Commits on success, rolls back on exception, always closes.
    """

    @contextmanager
    def session(self) -> Iterator[DbSession]:
        """
        Start a read-only session and yield a DbSession.

        Implementations may still allow reads + non-committing writes.
        """
        ...

    @contextmanager
    def transaction(self) -> Iterator[DbSession]:
        """
        Start a transaction and yield a DbSession.

        Usage:
            with uow.transaction() as session:
                session.execute("INSERT INTO ...")
                session.commit()
        """
        ...
