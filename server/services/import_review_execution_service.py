"""Facade for importer review-resolution execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable

from core.contracts.import_batch_refs import CreatedRowRef
from core.importer.normalize_pipeline import NormalizationPipeline
from server.imports.models import ImportJob
from server.services.import_agency_profile import refresh_agency_profile
from server.services.import_dead_letter import record_dead_letter_rows
from server.services.import_learning import record_learning_signals
from server.services.import_review_conflicts import detect_create_conflicts
from server.services.import_review_created_rows import ReviewCorrectionCreateBatch
from server.services.import_review_payloads import NormalizedReviewSubmitRequest
from server.services.import_review_resolution import (
    apply_review_resolutions_impl,
)
from server.services.import_review_resolution_creates import (
    insert_review_correction_batches_impl,
    insert_review_corrections_impl,
)
from server.services.import_review_resolution_errors import ImportReviewConflictError
from server.services.import_review_submit_service import (
    ImportReviewSubmitConflictError,
    kickoff_review_submission,
    run_review_submit_task,
)
from server.services.import_rows import validate_row
from server.services.import_types import ReviewRowPayload


def insert_review_corrections(
    *,
    job_id: str,
    entity_type: str,
    corrected_rows: list[dict[str, object]],
    user_id: int,
    agency_id: int,
) -> list[CreatedRowRef]:
    return insert_review_corrections_impl(
        job_id=job_id,
        entity_type=entity_type,
        corrected_rows=corrected_rows,
        user_id=user_id,
        agency_id=agency_id,
    )


def insert_review_correction_batches(
    *,
    job_id: str,
    batches: Sequence[ReviewCorrectionCreateBatch],
    user_id: int,
    agency_id: int,
) -> dict[str, list[CreatedRowRef]]:
    return insert_review_correction_batches_impl(
        job_id=job_id,
        batches=batches,
        user_id=user_id,
        agency_id=agency_id,
    )


def apply_review_resolutions(
    *,
    job_id: str = "",
    entity_type: str,
    review_rows: list[ReviewRowPayload],
    corrections: Mapping[str, Mapping[str, object]] | None,
    decisions: Mapping[str, Mapping[str, object]] | None,
    skip_rows: list[int | str] | None,
    user_id: int,
    agency_id: int,
) -> dict[str, object]:
    return apply_review_resolutions_impl(
        job_id=job_id,
        entity_type=entity_type,
        review_rows=review_rows,
        corrections=corrections,
        decisions=decisions,
        skip_rows=skip_rows,
        user_id=user_id,
        agency_id=agency_id,
        normalization_pipeline_cls=NormalizationPipeline,
        validate_row_fn=validate_row,
        insert_review_correction_batches_fn=insert_review_correction_batches,
        detect_create_conflicts_fn=detect_create_conflicts,
        record_learning_signals_fn=record_learning_signals,
        record_dead_letter_rows_fn=record_dead_letter_rows,
        refresh_agency_profile_fn=refresh_agency_profile,
    )


def submit_review(
    *,
    job: ImportJob,
    actor_user_id: int,
    agency_id: int,
    entity_type: str,
    request_payload: NormalizedReviewSubmitRequest,
    enqueue_review_submit_task_fn: Callable[..., Any],
    register_task_fn: Callable[..., object],
    schema: str | None,
    correlation_id: str | None,
) -> dict[str, object]:
    return kickoff_review_submission(
        job=job,
        actor_user_id=actor_user_id,
        agency_id=agency_id,
        entity_type=entity_type,
        request_payload=request_payload,
        enqueue_review_submit_task_fn=enqueue_review_submit_task_fn,
        register_task_fn=register_task_fn,
        schema=schema,
        correlation_id=correlation_id,
    )


__all__ = [
    "ImportReviewConflictError",
    "ImportReviewSubmitConflictError",
    "NormalizationPipeline",
    "apply_review_resolutions",
    "detect_create_conflicts",
    "insert_review_correction_batches",
    "insert_review_corrections",
    "record_dead_letter_rows",
    "record_learning_signals",
    "refresh_agency_profile",
    "run_review_submit_task",
    "submit_review",
    "validate_row",
]
