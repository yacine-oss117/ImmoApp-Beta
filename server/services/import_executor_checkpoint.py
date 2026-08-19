"""Checkpoint helpers for direct import execution orchestration."""

from __future__ import annotations

import logging
from typing import Any, Callable

from server.imports.models import ImportJob
from server.services.import_artifact_checkpoint import (
    build_planned_artifact_fingerprint,
    clear_planned_artifact_checkpoint,
    load_planned_artifact_checkpoint,
    persist_planned_artifact_checkpoint,
)
from server.services.import_types import (
    ImportResult,
    PlannedArtifactCheckpoint,
    PreparedImportArtifact,
    ReviewRowBuffer,
)


def build_checkpoint_fingerprint(
    *,
    job: ImportJob,
    entity_type: str,
    duplicate_strategy: str,
    skip_rows: int,
    skip_review_rows: bool,
    corrections: dict[str, dict[str, object]] | None,
    build_planned_artifact_fingerprint_fn: Callable[..., str] = build_planned_artifact_fingerprint,
) -> str:
    return build_planned_artifact_fingerprint_fn(
        job=job,
        entity_type=entity_type,
        duplicate_strategy=duplicate_strategy,
        skip_rows=skip_rows,
        skip_review_rows=skip_review_rows,
        corrections=corrections,
    )


def load_planned_checkpoint(
    *,
    job: ImportJob,
    fingerprint: str,
    load_planned_artifact_checkpoint_fn: Callable[
        ..., PlannedArtifactCheckpoint | None
    ] = load_planned_artifact_checkpoint,
) -> PlannedArtifactCheckpoint | None:
    return load_planned_artifact_checkpoint_fn(
        job=job,
        fingerprint=fingerprint,
    )


def persist_planned_checkpoint(
    *,
    job: ImportJob,
    artifact: PreparedImportArtifact,
    fingerprint: str,
    review_rows: ReviewRowBuffer,
    errors: list[dict[str, object]],
    skipped_count: int,
    error_count: int,
    persist_planned_artifact_checkpoint_fn: Callable[
        ..., None
    ] = persist_planned_artifact_checkpoint,
) -> None:
    persist_planned_artifact_checkpoint_fn(
        job=job,
        artifact=artifact,
        fingerprint=fingerprint,
        review_rows=review_rows,
        errors=errors,
        skipped_count=skipped_count,
        error_count=error_count,
    )


def restore_planned_checkpoint_state(
    *,
    checkpoint: PlannedArtifactCheckpoint,
    result: ImportResult,
    review_rows: ReviewRowBuffer,
) -> PreparedImportArtifact:
    artifact = checkpoint.artifact
    try:
        review_rows.extend(dict(row) for row in checkpoint.review_rows)
        review_rows.overflow_count = checkpoint.review_overflow_count
        result.skipped_count = checkpoint.skipped_count
        result.error_count = checkpoint.error_count
        result.errors = [dict(error) for error in checkpoint.errors]
        return artifact
    finally:
        cleanup = getattr(checkpoint.review_rows, "cleanup", None)
        if callable(cleanup):
            cleanup()


def clear_planned_checkpoint_best_effort(
    *,
    job: ImportJob,
    clear_planned_artifact_checkpoint_fn: Callable[..., Any] = clear_planned_artifact_checkpoint,
    logger: logging.Logger,
) -> None:
    try:
        clear_planned_artifact_checkpoint_fn(job=job)
    except Exception:
        logger.warning("Failed to clear planned import checkpoint", exc_info=True)


__all__ = [
    "build_checkpoint_fingerprint",
    "build_planned_artifact_fingerprint",
    "clear_planned_artifact_checkpoint",
    "clear_planned_checkpoint_best_effort",
    "load_planned_artifact_checkpoint",
    "load_planned_checkpoint",
    "persist_planned_artifact_checkpoint",
    "persist_planned_checkpoint",
    "restore_planned_checkpoint_state",
]
