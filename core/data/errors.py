"""
Shared domain errors for repository operations.
"""

from __future__ import annotations


class ConflictError(RuntimeError):
    """Raised when an optimistic concurrency check fails."""

    def __init__(
        self,
        message: str,
        current_version: int | None = None,
        current_record: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.current_version = current_version
        self.current_record = current_record


class NotFoundError(RuntimeError):
    """Raised when a requested record is not found for update operations."""
