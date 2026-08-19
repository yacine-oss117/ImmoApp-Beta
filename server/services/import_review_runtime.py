"""Review overflow and bounded review-row runtime helpers."""

from __future__ import annotations

from typing import Any, cast

from core.importer.security import import_security_limits
from server.services.import_types import ReviewRowBuffer, ReviewRowPayload, ReviewRows


def review_overflow_count(review_rows: ReviewRows) -> int:
    return int(getattr(review_rows, "overflow_count", 0) or 0)


def review_overflow_errors(*, overflow_count: int) -> list[dict[str, Any]]:
    resolved_overflow = max(0, int(overflow_count or 0))
    if resolved_overflow <= 0:
        return []
    return [
        {
            "row": 0,
            "errors": [
                (
                    f"{resolved_overflow} additional rows required review and exceeded the "
                    f"emergency review capacity of {import_security_limits().max_review_items_emergency}. "
                    "Clean or split the file and retry."
                )
            ],
        }
    ]


def append_review_row_limited(
    review_rows: ReviewRows,
    review_row: ReviewRowPayload,
) -> bool:
    if isinstance(review_rows, ReviewRowBuffer):
        append_result = review_rows.append(cast(dict[str, Any], review_row))
        if isinstance(append_result, bool):
            return append_result
        return True
    max_review_rows = import_security_limits().max_review_items_emergency
    if len(review_rows) >= max_review_rows:
        if hasattr(review_rows, "overflow_count"):
            review_rows.overflow_count = review_overflow_count(review_rows) + 1
            return False
        raise ValueError(
            f"Import generated more than {max_review_rows} review rows. "
            "Clean or split the file and retry."
        )
    review_rows.append(review_row)
    return True


def record_review_overflow(*, result: Any, review_rows: ReviewRows) -> None:
    overflow_errors = review_overflow_errors(overflow_count=review_overflow_count(review_rows))
    if not overflow_errors:
        return
    result.errors.extend(overflow_errors)
    result.error_count += len(overflow_errors)


__all__ = [
    "append_review_row_limited",
    "record_review_overflow",
    "review_overflow_count",
    "review_overflow_errors",
]
