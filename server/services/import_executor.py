"""Orchestration shell for importer execution."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from server.api.notifications import NotificationPersistenceError
from server.imports.models import ImportJob
from server.services import import_execution_state
from server.services.import_constants import (
    ENTITY_TYPE_DEMANDE,
    ENTITY_TYPE_OFFER,
    normalize_duplicate_strategy,
    normalize_entity_type,
)
from server.services.import_execution_metrics import record_import_metrics
from server.services.import_executor_checkpoint import (
    build_checkpoint_fingerprint,
    build_planned_artifact_fingerprint,
    clear_planned_artifact_checkpoint,
    load_planned_artifact_checkpoint,
    load_planned_checkpoint,
    persist_planned_artifact_checkpoint,
    persist_planned_checkpoint,
    restore_planned_checkpoint_state,
)
from server.services.import_executor_checkpoint import (
    clear_planned_checkpoint_best_effort as _clear_planned_checkpoint_best_effort_impl,
)
from server.services.import_job_topology import job_topology
from server.services.import_load_service import (
    load_child_only_import,
    load_same_side_bundle_import,
    load_single_entity_import,
)
from server.services.import_planning_service import (
    plan_child_only_import,
    plan_same_side_bundle_import,
    plan_single_entity_import,
)
from server.services.import_prepare_service import (
    prepare_child_only_import,
    prepare_same_side_bundle_import,
    prepare_single_entity_import,
)
from server.services.import_review_execution_service import (
    apply_review_resolutions,
    insert_review_corrections,
)
from server.services.import_review_runtime import (
    record_review_overflow,
    review_overflow_count,
)
from server.services.import_type_inference import unsupported_child_only_import_message
from server.services.import_types import ImportResult, PreparedImportArtifact, ReviewRowBuffer
from server.services.storage import StorageError, download_to_temp

logger = logging.getLogger(__name__)


def _persist_direct_execution_state(
    *,
    job: ImportJob,
    user_id: int,
    artifact: PreparedImportArtifact,
    result: ImportResult,
    review_rows: ReviewRowBuffer,
) -> None:
    import_execution_state.persist_direct_execution_state(
        job=job,
        user_id=user_id,
        artifact=artifact,
        result=result,
        review_rows=review_rows,
    )


def _mark_job_failed(job: ImportJob, exc: Exception) -> None:
    import_execution_state.mark_job_failed(job, exc)


def _clear_planned_checkpoint_best_effort(job: ImportJob) -> None:
    _clear_planned_checkpoint_best_effort_impl(
        job=job,
        clear_planned_artifact_checkpoint_fn=clear_planned_artifact_checkpoint,
        logger=logger,
    )


def _execute_direct_flow(
    *,
    job: ImportJob,
    user_id: int,
    fingerprint_entity_type: str,
    metrics_entity_type: str,
    skip_rows: int,
    skip_review_rows: bool,
    duplicate_strategy: str,
    corrections: dict[str, dict[str, object]] | None,
    prepare_and_plan_fn: Callable[
        [ImportResult, ReviewRowBuffer],
        tuple[PreparedImportArtifact, list[dict[str, object]]],
    ],
    load_fn: Callable[
        [PreparedImportArtifact, list[dict[str, object]], ReviewRowBuffer, ImportResult],
        Any,
    ],
) -> ImportResult:
    result = ImportResult(success=False)
    errors: list[dict[str, object]] = []
    review_rows: ReviewRowBuffer = ReviewRowBuffer()
    execution_started_at = time.monotonic()
    artifact: PreparedImportArtifact | None = None
    total_db_time = 0.0
    fingerprint = build_checkpoint_fingerprint(
        job=job,
        entity_type=fingerprint_entity_type,
        duplicate_strategy=duplicate_strategy,
        skip_rows=skip_rows,
        skip_review_rows=skip_review_rows,
        corrections=corrections,
        build_planned_artifact_fingerprint_fn=build_planned_artifact_fingerprint,
    )
    try:
        checkpoint = load_planned_checkpoint(
            job=job,
            fingerprint=fingerprint,
            load_planned_artifact_checkpoint_fn=load_planned_artifact_checkpoint,
        )
        if checkpoint is not None:
            artifact = restore_planned_checkpoint_state(
                checkpoint=checkpoint,
                result=result,
                review_rows=review_rows,
            )
            errors = list(result.errors)
        else:
            artifact, errors = prepare_and_plan_fn(result, review_rows)
            persist_planned_checkpoint(
                job=job,
                artifact=artifact,
                fingerprint=fingerprint,
                review_rows=review_rows,
                errors=errors,
                skipped_count=result.skipped_count,
                error_count=result.error_count,
                persist_planned_artifact_checkpoint_fn=persist_planned_artifact_checkpoint,
            )
        load_outcome = load_fn(artifact, errors, review_rows, result)
        total_db_time = float(getattr(load_outcome, "total_db_time", 0.0) or 0.0)
        result.errors = [dict(error) for error in errors]
        _persist_direct_execution_state(
            job=job,
            user_id=user_id,
            artifact=artifact,
            result=result,
            review_rows=review_rows,
        )
        if result.success:
            _clear_planned_checkpoint_best_effort(job)
    except NotificationPersistenceError:
        raise
    except (StorageError, ValueError) as exc:
        result.success = False
        result.errors = [
            {"row": 0, "errors": [import_execution_state.friendly_import_error_message(exc)]}
        ]
        result.error_count = max(1, result.error_count)
        _mark_job_failed(job, exc)
    except Exception as exc:
        result.success = False
        result.errors = [
            {"row": 0, "errors": [import_execution_state.friendly_import_error_message(exc)]}
        ]
        result.error_count = max(1, result.error_count)
        _mark_job_failed(job, exc)
    finally:
        review_rows.cleanup()
        import_execution_state.cleanup_prepared_artifact(artifact)

    record_review_overflow(result=result, review_rows=review_rows)
    record_import_metrics(
        entity_type=metrics_entity_type,
        result=result,
        review_count=len(review_rows) + review_overflow_count(review_rows),
        execution_started_at=execution_started_at,
        total_db_time=total_db_time,
    )
    return result


def _execute_child_only_import(
    *,
    job: ImportJob,
    user_id: int,
    entity_type: str,
    skip_rows: int,
    skip_review_rows: bool,
    duplicate_strategy: str,
    corrections: dict[str, dict[str, object]] | None,
) -> ImportResult:
    def _prepare_and_plan(
        result: ImportResult,
        review_rows: ReviewRowBuffer,
    ) -> tuple[PreparedImportArtifact, list[dict[str, object]]]:
        artifact = prepare_child_only_import(
            job=job,
            entity_type=entity_type,
            skip_rows=skip_rows,
            skip_review_rows=skip_review_rows,
            corrections=corrections,
            review_rows=review_rows,
            result=result,
            download_to_temp_fn=download_to_temp,
        )
        errors = list(result.errors)
        artifact = plan_child_only_import(
            job=job,
            user_id=user_id,
            entity_type=entity_type,
            duplicate_strategy=duplicate_strategy,
            skip_review_rows=skip_review_rows,
            review_rows=review_rows,
            errors=errors,
            result=result,
            artifact=artifact,
        )
        return artifact, errors

    def _load(
        artifact: PreparedImportArtifact,
        _errors: list[dict[str, object]],
        review_rows: ReviewRowBuffer,
        result: ImportResult,
    ) -> Any:
        return load_child_only_import(
            job=job,
            user_id=user_id,
            entity_type=entity_type,
            review_rows=review_rows,
            result=result,
            artifact=artifact,
        )

    return _execute_direct_flow(
        job=job,
        user_id=user_id,
        fingerprint_entity_type=entity_type,
        metrics_entity_type=entity_type,
        skip_rows=skip_rows,
        skip_review_rows=skip_review_rows,
        duplicate_strategy=duplicate_strategy,
        corrections=corrections,
        prepare_and_plan_fn=_prepare_and_plan,
        load_fn=_load,
    )


def _execute_same_side_bundle_import(
    *,
    job: ImportJob,
    user_id: int,
    skip_rows: int,
    skip_review_rows: bool,
    duplicate_strategy: str,
    corrections: dict[str, dict[str, object]] | None,
) -> ImportResult:
    topology = job_topology(job)
    topology_side = topology.topology_side
    root_entity = topology.root_entity
    child_entity = topology.child_entity

    def _prepare_and_plan(
        result: ImportResult,
        review_rows: ReviewRowBuffer,
    ) -> tuple[PreparedImportArtifact, list[dict[str, object]]]:
        artifact = prepare_same_side_bundle_import(
            job=job,
            root_entity=root_entity,
            child_entity=child_entity,
            topology_side=topology_side,
            skip_rows=skip_rows,
            skip_review_rows=skip_review_rows,
            duplicate_strategy=duplicate_strategy,
            corrections=corrections,
            review_rows=review_rows,
            result=result,
            download_to_temp_fn=download_to_temp,
        )
        errors = list(result.errors)
        artifact = plan_same_side_bundle_import(
            job=job,
            user_id=user_id,
            duplicate_strategy=duplicate_strategy,
            skip_review_rows=skip_review_rows,
            review_rows=review_rows,
            errors=errors,
            result=result,
            artifact=artifact,
        )
        return artifact, errors

    def _load(
        artifact: PreparedImportArtifact,
        errors: list[dict[str, object]],
        review_rows: ReviewRowBuffer,
        result: ImportResult,
    ) -> Any:
        return load_same_side_bundle_import(
            job=job,
            user_id=user_id,
            review_rows=review_rows,
            errors=errors,
            result=result,
            artifact=artifact,
        )

    return _execute_direct_flow(
        job=job,
        user_id=user_id,
        fingerprint_entity_type=root_entity,
        metrics_entity_type=root_entity,
        skip_rows=skip_rows,
        skip_review_rows=skip_review_rows,
        duplicate_strategy=duplicate_strategy,
        corrections=corrections,
        prepare_and_plan_fn=_prepare_and_plan,
        load_fn=_load,
    )


def execute_import(
    *,
    job: ImportJob,
    user_id: int,
    skip_rows: int = 0,
    skip_review_rows: bool = False,
    duplicate_strategy: str = "skip",
    corrections: dict[str, dict[str, object]] | None = None,
) -> ImportResult:
    result = ImportResult(success=False)

    if not job.source_path:
        result.errors = [{"row": 0, "errors": ["File not found on server"]}]
        return result

    entity_type = normalize_entity_type(job.detected_entity)
    duplicate_strategy = normalize_duplicate_strategy(duplicate_strategy)
    resolved_bundle_mode = job_topology(job).bundle_mode

    if resolved_bundle_mode == "mixed_blocked":
        result.errors = [
            {
                "row": 0,
                "errors": [
                    "This file mixes client-side and listing-side rows. Split it before execution."
                ],
            }
        ]
        result.error_count = 1
        return result
    if resolved_bundle_mode == "same_side_bundle":
        return _execute_same_side_bundle_import(
            job=job,
            user_id=user_id,
            skip_rows=skip_rows,
            skip_review_rows=skip_review_rows,
            duplicate_strategy=duplicate_strategy,
            corrections=corrections,
        )
    unsupported_message = unsupported_child_only_import_message(
        {
            "bundle_mode": resolved_bundle_mode,
            "detected_entity": entity_type,
        }
    )
    if unsupported_message:
        result.errors = [{"row": 0, "errors": [unsupported_message]}]
        result.error_count = 1
        return result
    if entity_type in {ENTITY_TYPE_DEMANDE, ENTITY_TYPE_OFFER}:
        return _execute_child_only_import(
            job=job,
            user_id=user_id,
            entity_type=entity_type,
            skip_rows=skip_rows,
            skip_review_rows=skip_review_rows,
            duplicate_strategy=duplicate_strategy,
            corrections=corrections,
        )

    def _prepare_and_plan(
        run_result: ImportResult,
        review_rows: ReviewRowBuffer,
    ) -> tuple[PreparedImportArtifact, list[dict[str, object]]]:
        artifact = prepare_single_entity_import(
            job=job,
            user_id=user_id,
            entity_type=entity_type,
            skip_rows=skip_rows,
            skip_review_rows=skip_review_rows,
            duplicate_strategy=duplicate_strategy,
            corrections=corrections,
            review_rows=review_rows,
            result=run_result,
            download_to_temp_fn=download_to_temp,
        )
        artifact = plan_single_entity_import(
            job=job,
            entity_type=entity_type,
            duplicate_strategy=duplicate_strategy,
            skip_review_rows=skip_review_rows,
            review_rows=review_rows,
            errors=run_result.errors,
            result=run_result,
            artifact=artifact,
        )
        return artifact, list(run_result.errors)

    def _load(
        artifact: PreparedImportArtifact,
        _errors: list[dict[str, object]],
        review_rows: ReviewRowBuffer,
        run_result: ImportResult,
    ) -> Any:
        return load_single_entity_import(
            job=job,
            user_id=user_id,
            entity_type=entity_type,
            review_rows=review_rows,
            result=run_result,
            artifact=artifact,
        )

    return _execute_direct_flow(
        job=job,
        user_id=user_id,
        fingerprint_entity_type=entity_type,
        metrics_entity_type=entity_type,
        skip_rows=skip_rows,
        skip_review_rows=skip_review_rows,
        duplicate_strategy=duplicate_strategy,
        corrections=corrections,
        prepare_and_plan_fn=_prepare_and_plan,
        load_fn=_load,
    )


__all__ = [
    "ImportResult",
    "apply_review_resolutions",
    "execute_import",
    "insert_review_corrections",
]
