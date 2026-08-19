"""Persistence helpers for review-submit terminal recovery states."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from server.imports.models import ImportJob
from server.services.import_review_queries import review_count_snapshot
from server.services.import_review_store import ensure_review_state
from server.services.import_review_submit_attempts import finish_review_submit_attempt_fresh
from server.services.import_review_submit_dispatch import (
    REVIEW_SUBMIT_DISPATCH_CONFLICT,
    REVIEW_SUBMIT_DISPATCH_FAILED,
    REVIEW_SUBMIT_WORKFLOW_KEY,
)
from server.services.json_safe import json_safe_value

_FAILED_CODE = "IMPORT_REVIEW_SUBMIT_FAILED"
_FAILED_DETAIL = "We couldn’t continue with these choices just yet. Please try again."


def _coerce_int(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip() or "0")
        except ValueError:
            return default
    return default


def _dict(value: object) -> dict[str, object]:
    return (
        {str(key): item for key, item in dict(value).items()} if isinstance(value, Mapping) else {}
    )


def review_submit_generic_error_payload() -> dict[str, object]:
    return {"code": _FAILED_CODE, "detail": _FAILED_DETAIL}


def persist_review_submit_ready_state(
    *,
    job: ImportJob,
    conflict_payload: Mapping[str, object] | None = None,
    error_payload: Mapping[str, object] | None = None,
) -> None:
    snapshot = ensure_review_state(job) or review_count_snapshot(job)
    summary = _dict(job.result_summary)
    if conflict_payload is None:
        summary.pop("review_submit_conflict", None)
    else:
        summary["review_submit_conflict"] = cast(
            dict[str, object], json_safe_value(dict(conflict_payload))
        )
    if error_payload is None:
        summary.pop("review_submit_error", None)
    else:
        summary["review_submit_error"] = cast(
            dict[str, object], json_safe_value(dict(error_payload))
        )
    visible_count = int(snapshot.visible_review_count or 0)
    summary["review_count"] = visible_count
    summary["review_pending_group_count"] = int(snapshot.pending_group_count or 0)
    summary["review_state"] = "normal" if visible_count > 0 else "none"
    summary["overflow_blocking"] = False
    summary["review_disabled"] = False
    summary["review_disabled_reason"] = ""
    job.result_summary = cast(dict[str, object], json_safe_value(summary))
    job.progress_detail = cast(
        dict[str, object],
        json_safe_value(
            {
                **_dict(job.progress_detail),
                "phase": "review",
                "error_count": _coerce_int(summary.get("error_count", 0)),
                "review_pending_group_count": int(snapshot.pending_group_count or 0),
                "review_state": "normal" if visible_count > 0 else "none",
                "overflow_blocking": False,
                "review_disabled": False,
                "review_disabled_reason": "",
            }
        ),
    )
    job.status = ImportJob.Status.READY
    job.stage = ImportJob.Stage.REVIEW
    job.error_message = None
    job.save(
        update_fields=[
            "result_summary",
            "progress_detail",
            "status",
            "stage",
            "error_message",
            "updated_at",
        ]
    )


def persist_review_submit_failure_terminal(
    *,
    job: ImportJob,
    task_id: str | None,
    clear_submit_payload: bool,
) -> None:
    persist_review_submit_ready_state(job=job, error_payload=review_submit_generic_error_payload())
    finish_review_submit_attempt_fresh(
        job=job,
        task_id=task_id,
        status=REVIEW_SUBMIT_DISPATCH_FAILED,
        clear_workflow_keys=([REVIEW_SUBMIT_WORKFLOW_KEY] if clear_submit_payload else []),
    )


def persist_review_submit_conflict_terminal(
    *,
    job: ImportJob,
    task_id: str | None,
    conflict_payload: Mapping[str, object],
) -> None:
    persist_review_submit_ready_state(job=job, conflict_payload=conflict_payload)
    finish_review_submit_attempt_fresh(
        job=job,
        task_id=task_id,
        status=REVIEW_SUBMIT_DISPATCH_CONFLICT,
        clear_workflow_keys=[REVIEW_SUBMIT_WORKFLOW_KEY],
    )


__all__ = [
    "persist_review_submit_conflict_terminal",
    "persist_review_submit_failure_terminal",
    "persist_review_submit_ready_state",
    "review_submit_generic_error_payload",
]
