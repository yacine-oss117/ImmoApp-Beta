"""Service-owned helpers for import status and cancel API views."""

from __future__ import annotations

from typing import cast

from server.immoapp_server.business_metrics_imports import record_import_status_signal
from server.imports.models import ImportJob
from server.services import tenant_resource_governor
from server.services.import_cancel_flow import cancel_import_request
from server.services.import_chunk_workflow import (
    request_workflow_cancellation,
    save_workflow_payload,
    workflow_payload,
)
from server.services.import_control_plane import cancel_import_immediately as _cancel_now_impl
from server.services.import_execution_governor import effective_import_runtime_profile
from server.services.import_execution_health import execution_health_snapshot
from server.services.import_job_queue import (
    dispatch_next_agency_import,
    dispatch_queued_imports,
    execution_owner_for_job,
    queue_position_for_job,
    release_execution_slot,
)
from server.services.import_mapping import canonicalize_column_mapping
from server.services.import_mapping_palette import derive_mapping_palette
from server.services.import_notifications import emit_import_notification
from server.services.import_review_store import ensure_review_state, review_count_snapshot
from server.services.import_service import get_active_schema
from server.services.import_status_contracts import (
    BudgetStateSnapshotFn,
    CanonicalizeColumnMappingFn,
    DeriveMappingPaletteFn,
    EnsureReviewStateFn,
    ExecutionHealthSnapshotFn,
    LiveAgencyQueueDepthFn,
    QueuePositionForJobFn,
    ResolveImportStatusFn,
    ReviewCountSnapshotFn,
    RuntimeProfileFn,
    WorkflowPayloadFn,
)
from server.services.import_status_payload import build_import_status_payload as _build_status
from server.services.import_status_policy import live_agency_queue_depth as _live_queue_depth
from server.services.import_status_resolver import resolve_import_status


def _live_agency_queue_depth(*, agency_id: int, session_status: str) -> int:
    return _live_queue_depth(agency_id=agency_id, session_status=session_status)


def build_import_status_payload(*, session: ImportJob, agency_id: int) -> dict[str, object]:
    return _build_status(
        session=session,
        agency_id=agency_id,
        workflow_payload_fn=cast(WorkflowPayloadFn, workflow_payload),
        ensure_review_state_fn=cast(EnsureReviewStateFn, ensure_review_state),
        review_count_snapshot_fn=cast(ReviewCountSnapshotFn, review_count_snapshot),
        resolve_import_status_fn=cast(ResolveImportStatusFn, resolve_import_status),
        effective_import_runtime_profile_fn=cast(
            RuntimeProfileFn, effective_import_runtime_profile
        ),
        budget_state_snapshot_fn=cast(
            BudgetStateSnapshotFn, tenant_resource_governor.budget_state_snapshot
        ),
        execution_health_snapshot_fn=cast(ExecutionHealthSnapshotFn, execution_health_snapshot),
        queue_position_for_job_fn=cast(QueuePositionForJobFn, queue_position_for_job),
        canonicalize_column_mapping_fn=cast(
            CanonicalizeColumnMappingFn, canonicalize_column_mapping
        ),
        derive_mapping_palette_fn=cast(DeriveMappingPaletteFn, derive_mapping_palette),
        live_agency_queue_depth_fn=cast(LiveAgencyQueueDepthFn, _live_agency_queue_depth),
    )


def cancel_import_immediately(*, job: ImportJob, user_id: int) -> None:
    _cancel_now_impl(
        job=job,
        user_id=user_id,
        request_workflow_cancellation_fn=request_workflow_cancellation,
        workflow_payload_fn=workflow_payload,
        save_workflow_payload_fn=save_workflow_payload,
        emit_import_notification_fn=emit_import_notification,
    )


def cancel_import_immediately_response(
    *,
    job: ImportJob,
    user_id: int,
    agency_id: int,
) -> dict[str, object]:
    cancel_import_immediately(job=job, user_id=user_id)
    if job.status == ImportJob.Status.RUNNING:
        release_execution_slot(
            agency_id=int(agency_id or 0),
            owner=execution_owner_for_job(job.id),
        )
    dispatch_next_agency_import(agency_id=int(agency_id or 0), schema=get_active_schema())
    dispatch_queued_imports(limit=2, max_global_running=2)
    refresh_from_db = getattr(job, "refresh_from_db", None)
    if callable(refresh_from_db):
        refresh_from_db()
    payload = build_import_status_payload(session=job, agency_id=agency_id)
    record_import_status_signal(
        event="cancel",
        terminal_reason="cancelled",
        cancel_requested=True,
    )
    payload["detail"] = "This import was cancelled."
    return payload


def cancel_import_request_payload(
    *,
    job: ImportJob,
    user_id: int,
    agency_id: int,
) -> dict[str, object]:
    return cancel_import_request(
        job=job,
        user_id=user_id,
        agency_id=int(agency_id or 0),
        build_import_status_payload_fn=build_import_status_payload,
        execution_health_snapshot_fn=execution_health_snapshot,
        cancel_import_immediately_fn=cancel_import_immediately,
        request_workflow_cancellation_fn=request_workflow_cancellation,
        release_execution_slot_fn=release_execution_slot,
        execution_owner_for_job_fn=execution_owner_for_job,
        dispatch_next_agency_import_fn=dispatch_next_agency_import,
        dispatch_queued_imports_fn=dispatch_queued_imports,
        record_import_status_signal_fn=record_import_status_signal,
        get_active_schema_fn=get_active_schema,
    )


__all__ = [
    "build_import_status_payload",
    "cancel_import_immediately",
    "cancel_import_immediately_response",
    "cancel_import_request_payload",
]
