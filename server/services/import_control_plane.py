"""Compatibility facade for importer control-plane helpers."""

from __future__ import annotations

from typing import Any, Callable

from server.imports.models import ImportJob
from server.services.import_cancel_flow import (
    cancel_import_immediately as _cancel_import_immediately_impl,
)
from server.services.import_execution_state import (
    cleanup_prepared_artifact,
    friendly_import_error_message,
    mark_job_failed,
    persist_direct_execution_state,
    review_progress_detail,
)
from server.services.import_review_store import clear_db_review_state
from server.services.import_workflow_dispatch import (
    WorkflowDispatchPlan,
    advance_workflow_dispatch,
    aggregate_review_overflow_count,
    rollup_workflow_progress,
)


def cancel_import_immediately(
    *,
    job: ImportJob,
    user_id: int,
    request_workflow_cancellation_fn: Callable[..., int],
    workflow_payload_fn: Callable[[ImportJob], dict[str, Any]],
    save_workflow_payload_fn: Callable[[ImportJob, dict[str, Any]], None],
    emit_import_notification_fn: Callable[..., None],
) -> None:
    _cancel_import_immediately_impl(
        job=job,
        user_id=user_id,
        request_workflow_cancellation_fn=request_workflow_cancellation_fn,
        workflow_payload_fn=workflow_payload_fn,
        save_workflow_payload_fn=save_workflow_payload_fn,
        emit_import_notification_fn=emit_import_notification_fn,
        clear_db_review_state_fn=clear_db_review_state,
    )


__all__ = [
    "WorkflowDispatchPlan",
    "advance_workflow_dispatch",
    "aggregate_review_overflow_count",
    "cancel_import_immediately",
    "cleanup_prepared_artifact",
    "friendly_import_error_message",
    "mark_job_failed",
    "persist_direct_execution_state",
    "review_progress_detail",
    "rollup_workflow_progress",
]
