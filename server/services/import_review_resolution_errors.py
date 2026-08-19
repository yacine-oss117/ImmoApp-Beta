"""Shared review-resolution execution errors."""

from __future__ import annotations

from dataclasses import dataclass

from server.services.import_review_conflicts import RowConflict


@dataclass(frozen=True)
class ImportReviewConflictError(RuntimeError):
    detail: str
    row_conflicts: list[RowConflict]

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.detail)


__all__ = ["ImportReviewConflictError"]
