"""Workflow-backed dispatch state for async review-submit tasks."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from typing import Any, cast

from django.db import transaction
from django.utils import timezone

from server.imports.models import ImportJob
from server.services.import_review_payloads import (
    NormalizedReviewSubmitRequest,
    PreparedReviewSubmitPayload,
)
from server.services.import_review_submit_attempts import (
    ATTEMPT_CANCELLED,
    ATTEMPT_STARTED,
    ATTEMPT_TERMINAL_STATUSES,
    begin_review_submit_attempt,
    claim_review_submit_attempt_started,
    finish_review_submit_attempt_fresh,
)
from server.services.import_workflow_storage import save_workflow_payload, workflow_payload
from server.services.json_safe import json_safe_value

logger = logging.getLogger(__name__)

REVIEW_SUBMIT_WORKFLOW_KEY = "review_submit"
REVIEW_SUBMIT_DISPATCH_WORKFLOW_KEY = "review_submit_dispatch"
REVIEW_SUBMIT_DISPATCH_PENDING = "pending"
REVIEW_SUBMIT_DISPATCH_PUBLISHED = "published"
REVIEW_SUBMIT_DISPATCH_PUBLISH_FAILED = "publish_failed"
REVIEW_SUBMIT_DISPATCH_STARTED = ATTEMPT_STARTED
REVIEW_SUBMIT_DISPATCH_COMPLETED = "completed"
REVIEW_SUBMIT_DISPATCH_CONFLICT = "conflict"
REVIEW_SUBMIT_DISPATCH_FAILED = "failed"
REVIEW_SUBMIT_DISPATCH_CANCELLED = ATTEMPT_CANCELLED
REVIEW_SUBMIT_DISPATCH_REPAIRABLE_STATUSES = frozenset(
    {
        REVIEW_SUBMIT_DISPATCH_PENDING,
        REVIEW_SUBMIT_DISPATCH_PUBLISHED,
        REVIEW_SUBMIT_DISPATCH_PUBLISH_FAILED,
    }
)
REVIEW_SUBMIT_DISPATCH_TERMINAL_STATUSES = frozenset(
    {
        REVIEW_SUBMIT_DISPATCH_COMPLETED,
        REVIEW_SUBMIT_DISPATCH_CONFLICT,
        REVIEW_SUBMIT_DISPATCH_FAILED,
        REVIEW_SUBMIT_DISPATCH_CANCELLED,
    }
)
REVIEW_SUBMIT_DISPATCH_PUBLISH_FAILED_CODE = "review_submit_publish_failed"


def _workflow(job: ImportJob) -> dict[str, object]:
    return {str(key): value for key, value in workflow_payload(job).items()}


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        return int(stripped) if stripped else 0
    return 0


def _save(job: ImportJob, workflow: Mapping[str, object]) -> None:
    save_workflow_payload(
        job,
        cast(dict[str, object], json_safe_value(dict(workflow))),
    )


def _now_iso() -> str:
    return cast(str, timezone.now().isoformat())


def generate_review_submit_task_id() -> str:
    return str(uuid.uuid4())


def persist_review_submit_workflow(
    *,
    job: ImportJob,
    request_payload: NormalizedReviewSubmitRequest,
    prepared_submit: PreparedReviewSubmitPayload | None = None,
) -> None:
    if prepared_submit is None:
        persisted_corrections = {
            str(key): dict(value or {})
            for key, value in request_payload.corrections.items()
            if str(key or "").strip()
        }
        persisted_decisions = {
            str(key): dict(value or {})
            for key, value in request_payload.decisions.items()
            if str(key or "").strip()
        }
        persisted_skip_rows = [
            str(value) for value in request_payload.skip_rows if str(value or "").strip()
        ]
        persisted_bulk_operations = [
            dict(item) for item in request_payload.bulk_operations if isinstance(item, Mapping)
        ]
    else:
        persisted_corrections = {
            str(key): dict(value or {})
            for key, value in prepared_submit.corrections.items()
            if str(key or "").strip()
        }
        persisted_decisions = {
            str(key): dict(value or {})
            for key, value in prepared_submit.decisions.items()
            if str(key or "").strip()
        }
        persisted_skip_rows = [
            str(value) for value in prepared_submit.skip_rows if str(value or "").strip()
        ]
        persisted_bulk_operations = []

    workflow = _workflow(job)
    workflow[REVIEW_SUBMIT_WORKFLOW_KEY] = cast(
        dict[str, object],
        json_safe_value(
            {
                "corrections": persisted_corrections,
                "decisions": persisted_decisions,
                "skip_rows": persisted_skip_rows,
                "bulk_operations": persisted_bulk_operations,
            }
        ),
    )
    _save(job, workflow)


def load_review_submit_workflow(job: ImportJob) -> dict[str, object]:
    workflow = _workflow(job)
    return _mapping(workflow.get(REVIEW_SUBMIT_WORKFLOW_KEY))


def review_submit_dispatch_payload(job: ImportJob) -> dict[str, object]:
    workflow = _workflow(job)
    return _mapping(workflow.get(REVIEW_SUBMIT_DISPATCH_WORKFLOW_KEY))


def begin_review_submit_dispatch(
    *,
    job: ImportJob,
    task_id: str,
    actor_user_id: int,
    agency_id: int,
    schema: str | None,
    correlation_id: str | None,
) -> None:
    begin_review_submit_attempt(
        job=job,
        task_id=task_id,
        status=REVIEW_SUBMIT_DISPATCH_PENDING,
        initial_payload={
            "task_id": str(task_id or ""),
            "status": REVIEW_SUBMIT_DISPATCH_PENDING,
            "actor_user_id": int(actor_user_id or 0),
            "agency_id": int(agency_id or 0),
            "schema": str(schema or ""),
            "correlation_id": str(correlation_id or ""),
            "requested_at": _now_iso(),
            "published_at": "",
            "started_at": "",
            "heartbeat_at": "",
            "finished_at": "",
            "cancel_requested_at": "",
            "cancel_reason": "",
            "publish_attempt_count": 0,
            "last_error_code": "",
            "last_attempted_at": "",
        },
    )


def _mark_review_submit_dispatch_published(
    job: ImportJob,
    *,
    task_id: str,
) -> dict[str, object]:
    workflow = _workflow(job)
    dispatch = _mapping(workflow.get(REVIEW_SUBMIT_DISPATCH_WORKFLOW_KEY))
    if str(dispatch.get("task_id", "") or "") != str(task_id or ""):
        return dispatch
    status = str(dispatch.get("status", "") or "")
    if status in ATTEMPT_TERMINAL_STATUSES:
        return dispatch
    if status != REVIEW_SUBMIT_DISPATCH_STARTED:
        dispatch["status"] = REVIEW_SUBMIT_DISPATCH_PUBLISHED
    if not str(dispatch.get("published_at", "") or "").strip():
        dispatch["published_at"] = _now_iso()
    dispatch["publish_attempt_count"] = _int_value(dispatch.get("publish_attempt_count", 0)) + 1
    dispatch["last_attempted_at"] = _now_iso()
    dispatch["last_error_code"] = ""
    workflow[REVIEW_SUBMIT_DISPATCH_WORKFLOW_KEY] = cast(
        dict[str, object], json_safe_value(dispatch)
    )
    _save(job, workflow)
    return dispatch


def _mark_review_submit_dispatch_publish_failed(
    job: ImportJob,
    *,
    task_id: str,
    error_code: str = REVIEW_SUBMIT_DISPATCH_PUBLISH_FAILED_CODE,
) -> dict[str, object]:
    workflow = _workflow(job)
    dispatch = _mapping(workflow.get(REVIEW_SUBMIT_DISPATCH_WORKFLOW_KEY))
    if str(dispatch.get("task_id", "") or "") != str(task_id or ""):
        return dispatch
    status = str(dispatch.get("status", "") or "")
    if status in ATTEMPT_TERMINAL_STATUSES | {REVIEW_SUBMIT_DISPATCH_STARTED}:
        return dispatch
    dispatch["status"] = REVIEW_SUBMIT_DISPATCH_PUBLISH_FAILED
    dispatch["publish_attempt_count"] = _int_value(dispatch.get("publish_attempt_count", 0)) + 1
    dispatch["last_error_code"] = str(error_code or REVIEW_SUBMIT_DISPATCH_PUBLISH_FAILED_CODE)
    dispatch["last_attempted_at"] = _now_iso()
    workflow[REVIEW_SUBMIT_DISPATCH_WORKFLOW_KEY] = cast(
        dict[str, object], json_safe_value(dispatch)
    )
    _save(job, workflow)
    return dispatch


def _locked_dispatch_job(job: ImportJob) -> ImportJob | None:
    agency_id = _int_value(getattr(job, "agency_id", 0))
    return cast(
        ImportJob | None,
        ImportJob.objects.select_for_update().filter(id=job.id, agency_id=agency_id).first(),
    )


def mark_review_submit_dispatch_published_fresh(
    job: ImportJob,
    *,
    task_id: str,
) -> dict[str, object]:
    """Mark post-publish success against fresh locked workflow state.

    The publisher can hold a stale in-memory workflow payload while a fast worker
    has already moved the dispatch to started or a terminal state. Reloading under
    a row lock prevents the publisher from downgrading that fresher state.
    """

    with transaction.atomic():
        locked_job = _locked_dispatch_job(job)
        if locked_job is None:
            return {}
        return _mark_review_submit_dispatch_published(locked_job, task_id=task_id)


def mark_review_submit_dispatch_publish_failed_fresh(
    job: ImportJob,
    *,
    task_id: str,
    error_code: str = REVIEW_SUBMIT_DISPATCH_PUBLISH_FAILED_CODE,
) -> dict[str, object]:
    """Mark post-publish failure against fresh locked workflow state."""

    with transaction.atomic():
        locked_job = _locked_dispatch_job(job)
        if locked_job is None:
            return {}
        return _mark_review_submit_dispatch_publish_failed(
            locked_job,
            task_id=task_id,
            error_code=error_code,
        )


def finish_review_submit_dispatch_fresh(
    job: ImportJob,
    *,
    task_id: str | None,
    status: str,
    clear_submit_payload: bool = True,
) -> dict[str, object]:
    """Finish review-submit dispatch against fresh locked workflow state.

    Worker terminal paths can hold stale workflow payloads from the start-claim
    phase while publisher metadata is written later. This helper preserves the
    latest dispatch envelope and only removes the submit payload after the
    stored task id still matches the worker that is finishing.
    """

    transition = finish_review_submit_attempt_fresh(
        job=job,
        task_id=task_id,
        status=status,
        clear_workflow_keys=([REVIEW_SUBMIT_WORKFLOW_KEY] if clear_submit_payload else []),
    )
    return transition.payload


def claim_review_submit_dispatch_start(
    *,
    session_id: str,
    agency_id: int,
    task_id: str | None,
) -> tuple[ImportJob | None, str]:
    transition = claim_review_submit_attempt_started(
        session_id=session_id,
        agency_id=agency_id,
        task_id=task_id,
    )
    return transition.job, transition.status


def publish_review_submit_dispatch(
    *,
    job: ImportJob,
    enqueue_review_submit_task_fn: Callable[..., Any],
    register_task_fn: Callable[..., object],
) -> bool:
    dispatch = review_submit_dispatch_payload(job)
    if not dispatch:
        return False
    status = str(dispatch.get("status", "") or "")
    if status not in REVIEW_SUBMIT_DISPATCH_REPAIRABLE_STATUSES:
        return False
    task_id = str(dispatch.get("task_id", "") or "").strip()
    if not task_id:
        return False
    try:
        async_result = enqueue_review_submit_task_fn(
            task_id=task_id,
            session_id=str(job.id),
            user_id=_int_value(dispatch.get("actor_user_id", 0)),
            agency_id=_int_value(dispatch.get("agency_id", 0)),
            schema=str(dispatch.get("schema", "") or "") or None,
            correlation_id=str(dispatch.get("correlation_id", "") or "") or None,
        )
        result_task_id = str(getattr(async_result, "id", "") or task_id)
        if result_task_id != task_id:
            logger.warning(
                "Review-submit dispatch returned mismatched task id for job %s: expected=%s actual=%s",
                job.id,
                task_id,
                result_task_id,
            )
        mark_review_submit_dispatch_published_fresh(job, task_id=task_id)
        try:
            register_task_fn(
                task_id,
                agency_id=_int_value(dispatch.get("agency_id", 0)),
                user_id=_int_value(dispatch.get("actor_user_id", 0)),
            )
        except Exception:
            logger.exception(
                "Review-submit dispatch published but task ownership registration failed for job %s task_id=%s",
                job.id,
                task_id,
            )
        return True
    except Exception:
        mark_review_submit_dispatch_publish_failed_fresh(job, task_id=task_id)
        logger.exception(
            "Review-submit dispatch publish failed for job %s task_id=%s",
            job.id,
            task_id,
        )
        return False


__all__ = [
    "REVIEW_SUBMIT_DISPATCH_COMPLETED",
    "REVIEW_SUBMIT_DISPATCH_CANCELLED",
    "REVIEW_SUBMIT_DISPATCH_CONFLICT",
    "REVIEW_SUBMIT_DISPATCH_FAILED",
    "REVIEW_SUBMIT_DISPATCH_PENDING",
    "REVIEW_SUBMIT_DISPATCH_PUBLISH_FAILED",
    "REVIEW_SUBMIT_DISPATCH_PUBLISH_FAILED_CODE",
    "REVIEW_SUBMIT_DISPATCH_PUBLISHED",
    "REVIEW_SUBMIT_DISPATCH_REPAIRABLE_STATUSES",
    "REVIEW_SUBMIT_DISPATCH_STARTED",
    "REVIEW_SUBMIT_DISPATCH_TERMINAL_STATUSES",
    "REVIEW_SUBMIT_DISPATCH_WORKFLOW_KEY",
    "REVIEW_SUBMIT_WORKFLOW_KEY",
    "begin_review_submit_dispatch",
    "claim_review_submit_dispatch_start",
    "finish_review_submit_dispatch_fresh",
    "generate_review_submit_task_id",
    "load_review_submit_workflow",
    "mark_review_submit_dispatch_publish_failed_fresh",
    "mark_review_submit_dispatch_published_fresh",
    "persist_review_submit_workflow",
    "publish_review_submit_dispatch",
    "review_submit_dispatch_payload",
]
