"""Created-row ref contract helpers for review correction creates."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from core.contracts.import_batch_refs import CreatedRowRef


@dataclass(frozen=True)
class ReviewCorrectionCreateBatch:
    entity_type: str
    corrected_rows: list[dict[str, object]]


class InsertReviewCorrectionsCallable(Protocol):
    def __call__(
        self,
        *,
        job_id: str,
        entity_type: str,
        corrected_rows: list[dict[str, object]],
        user_id: int,
        agency_id: int,
    ) -> Iterable[CreatedRowRef]: ...


class InsertReviewCorrectionBatchesCallable(Protocol):
    def __call__(
        self,
        *,
        job_id: str,
        batches: Sequence[ReviewCorrectionCreateBatch],
        user_id: int,
        agency_id: int,
    ) -> dict[str, list[CreatedRowRef]]: ...


def call_insert_review_corrections(
    *,
    insert_review_corrections_fn: InsertReviewCorrectionsCallable,
    job_id: str,
    entity_type: str,
    corrected_rows: list[dict[str, object]],
    user_id: int,
    agency_id: int,
) -> list[CreatedRowRef]:
    return [
        CreatedRowRef(
            source_ordinal=int(value.source_ordinal),
            created_id=int(value.created_id),
        )
        for value in list(
            insert_review_corrections_fn(
                job_id=job_id,
                entity_type=entity_type,
                corrected_rows=corrected_rows,
                user_id=user_id,
                agency_id=agency_id,
            )
        )
    ]


def call_insert_review_correction_batches(
    *,
    insert_review_correction_batches_fn: InsertReviewCorrectionBatchesCallable,
    job_id: str,
    batches: Sequence[ReviewCorrectionCreateBatch],
    user_id: int,
    agency_id: int,
) -> dict[str, list[CreatedRowRef]]:
    batch_results = insert_review_correction_batches_fn(
        job_id=job_id,
        batches=batches,
        user_id=user_id,
        agency_id=agency_id,
    )
    return {
        str(entity_type): [
            CreatedRowRef(
                source_ordinal=int(value.source_ordinal),
                created_id=int(value.created_id),
            )
            for value in list(created_rows or [])
        ]
        for entity_type, created_rows in batch_results.items()
    }


def require_created_rows_match_pending(
    *,
    entity_type: str,
    pending_count: int,
    created_rows: Sequence[CreatedRowRef],
) -> list[CreatedRowRef]:
    created_count = len(created_rows)
    if created_count != pending_count:
        raise ValueError(
            f"Review create batch for {entity_type} returned {created_count} created-row refs for "
            f"{int(pending_count)} pending rows."
        )
    normalized_rows = [
        CreatedRowRef(
            source_ordinal=int(row.source_ordinal),
            created_id=int(row.created_id),
        )
        for row in created_rows
    ]
    expected_ordinals = set(range(max(0, int(pending_count))))
    actual_ordinals = [row.source_ordinal for row in normalized_rows]
    if any(row.created_id <= 0 for row in normalized_rows):
        raise ValueError(
            f"Review create batch for {entity_type} returned a non-positive created id."
        )
    if any(ordinal < 0 for ordinal in actual_ordinals):
        raise ValueError(
            f"Review create batch for {entity_type} returned a negative source ordinal."
        )
    if len(set(actual_ordinals)) != len(actual_ordinals):
        raise ValueError(
            f"Review create batch for {entity_type} returned duplicate source ordinals."
        )
    if set(actual_ordinals) != expected_ordinals:
        raise ValueError(
            f"Review create batch for {entity_type} returned source ordinals that did not match the pending rows."
        )
    return sorted(normalized_rows, key=lambda row: row.source_ordinal)
