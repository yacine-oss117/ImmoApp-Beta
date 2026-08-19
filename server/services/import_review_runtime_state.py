"""Review-state persistence and review-required notification helpers."""

from __future__ import annotations

from typing import Any, cast

from server.imports.models import ImportJob
from server.services.import_notifications import emit_import_notification
from server.services.import_review_runtime import review_overflow_count
from server.services.import_review_store import (
    clear_db_review_state,
    persist_review_state_with_compatibility_sample,
    review_count_snapshot,
)
from server.services.import_types import ReviewRows
from server.services.json_safe import json_safe_value


def persist_review_state(
    *,
    job: ImportJob,
    review_rows: ReviewRows,
    progress_detail: dict[str, object],
) -> None:
    if isinstance(job, ImportJob):
        if review_rows:
            snapshot = persist_review_state_with_compatibility_sample(
                job=job,
                review_rows=[cast(dict[str, Any], dict(row)) for row in review_rows],
            )
        else:
            clear_db_review_state(job)
            snapshot = review_count_snapshot(job)
            job.review_rows = []
    else:
        job.review_rows = cast(
            list[dict[str, Any]],
            json_safe_value([dict(row) for row in review_rows]),
        )
        snapshot = type(
            "_Snapshot",
            (),
            {"pending_group_count": 0, "visible_review_count": len(job.review_rows)},
        )()
    job.stage = ImportJob.Stage.REVIEW
    payload = cast(dict[str, object], json_safe_value(dict(progress_detail)))
    payload["review_overflow_count"] = review_overflow_count(review_rows)
    payload["review_pending_group_count"] = int(snapshot.pending_group_count or 0)
    payload["review_state"] = (
        "emergency_overflow" if review_overflow_count(review_rows) > 0 else "normal"
    )
    payload["overflow_blocking"] = bool(review_overflow_count(review_rows) > 0)
    payload["review_disabled"] = bool(review_overflow_count(review_rows) > 0)
    payload["review_disabled_reason"] = (
        "This import produced more unresolved review items than the system can safely process in one job."
        if review_overflow_count(review_rows) > 0
        else ""
    )
    job.progress_detail = payload
    update_fields = ["review_rows", "stage", "progress_detail", "updated_at"]
    if isinstance(job, ImportJob):
        result_summary = dict(job.result_summary or {})
        result_summary["review_storage_mode"] = "db_paged_v2"
        result_summary["review_pending_group_count"] = int(snapshot.pending_group_count or 0)
        result_summary["review_state"] = str(payload.get("review_state", "normal") or "normal")
        result_summary["overflow_blocking"] = bool(payload.get("overflow_blocking", False))
        result_summary["review_disabled"] = bool(payload.get("review_disabled", False))
        result_summary["review_disabled_reason"] = str(
            payload.get("review_disabled_reason", "") or ""
        )
        job.result_summary = cast(dict[str, Any], json_safe_value(result_summary))
        update_fields.insert(3, "result_summary")
    job.save(update_fields=update_fields)


def emit_review_required_notification(*, user_id: int, job: ImportJob) -> None:
    progress_detail = cast(dict[str, Any], job.progress_detail or {})
    overflow_count = int(progress_detail.get("review_overflow_count", 0) or 0)
    snapshot = review_count_snapshot(job)
    visible_review_count = int(snapshot.visible_review_count or 0)
    emit_import_notification(
        event_type="import.review_required",
        user_id=user_id,
        title="Import needs review",
        body=f"{job.filename} needs review before completion.",
        data={
            "session_id": str(job.id),
            "review_count": visible_review_count,
            "review_overflow_count": overflow_count,
            "review_total_count": visible_review_count + overflow_count,
            "review_pending_group_count": int(snapshot.pending_group_count or 0),
            "entity_type": str(job.detected_entity or ""),
        },
    )


__all__ = ["emit_review_required_notification", "persist_review_state"]
