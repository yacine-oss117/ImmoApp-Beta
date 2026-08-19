"""Review-submit attempt fencing backed by ImportJob workflow state."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from django.db import transaction
from django.utils import timezone

from server.imports.models import ImportJob
from server.services.import_workflow_storage import save_workflow_payload, workflow_payload
from server.services.json_safe import json_safe_value
from server.services.task_attempt_lifecycle import (
    ATTEMPT_CANCELLED,
    ATTEMPT_COMPLETED,
    ATTEMPT_CONFLICT,
    ATTEMPT_FAILED,
    ATTEMPT_PENDING,
    ATTEMPT_PUBLISH_FAILED,
    ATTEMPT_PUBLISHED,
    ATTEMPT_STALE_IGNORED,
    ATTEMPT_STARTED,
    ATTEMPT_TERMINAL_STATUSES,
    TaskAttemptStaleError,
    cancel_payload,
    claim_started_payload,
    finish_payload,
    heartbeat_payload,
    is_attempt_current,
    new_attempt_payload,
)

logger = logging.getLogger(__name__)

ATTEMPT_REVIEW_SUBMIT = "review_submit"
REVIEW_SUBMIT_ATTEMPT_WORKFLOW_KEY = "review_submit_dispatch"
REVIEW_SUBMIT_STARTABLE_STATUSES = frozenset(
    {ATTEMPT_PENDING, ATTEMPT_PUBLISHED, ATTEMPT_PUBLISH_FAILED}
)

_T = TypeVar("_T")


class StaleImportTaskAttemptError(TaskAttemptStaleError):
    """Raised when a review-submit worker no longer owns the attempt fence."""


@dataclass(frozen=True)
class ReviewSubmitAttemptTransition:
    job: ImportJob | None
    payload: dict[str, object]
    status: str
    changed: bool
    reason: str = ""


def _now_iso() -> str:
    return cast(str, timezone.now().isoformat())


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _workflow(job: ImportJob) -> dict[str, object]:
    return {str(key): value for key, value in workflow_payload(job).items()}


def _payload_from_workflow(workflow: Mapping[str, object]) -> dict[str, object]:
    return _mapping(workflow.get(REVIEW_SUBMIT_ATTEMPT_WORKFLOW_KEY))


def _locked_job(job: ImportJob) -> ImportJob | None:
    agency_id = int(getattr(job, "agency_id", 0) or 0)
    return cast(
        ImportJob | None,
        ImportJob.objects.select_for_update().filter(id=job.id, agency_id=agency_id).first(),
    )


def _save_attempt(
    job: ImportJob,
    workflow: dict[str, object],
    payload: Mapping[str, object],
) -> dict[str, object]:
    normalized_payload = cast(dict[str, object], json_safe_value(dict(payload)))
    workflow[REVIEW_SUBMIT_ATTEMPT_WORKFLOW_KEY] = normalized_payload
    save_workflow_payload(job, cast(dict[str, Any], json_safe_value(workflow)))
    return normalized_payload


def begin_review_submit_attempt(
    *,
    job: ImportJob,
    task_id: str,
    initial_payload: Mapping[str, object] | None = None,
    status: str = ATTEMPT_PENDING,
) -> dict[str, object]:
    workflow = _workflow(job)
    payload = new_attempt_payload(
        attempt_type=ATTEMPT_REVIEW_SUBMIT,
        task_id=task_id,
        status=status,
        now_iso=_now_iso(),
        initial_payload=initial_payload,
    )
    saved = _save_attempt(job, workflow, payload)
    logger.info(
        "Review-submit attempt created",
        extra={
            "job_id": str(job.id),
            "attempt_id": str(saved.get("attempt_id", "") or ""),
            "task_id": str(task_id or ""),
            "status": str(status or ATTEMPT_PENDING),
        },
    )
    return saved


def review_submit_attempt_payload(job: ImportJob) -> dict[str, object]:
    return _payload_from_workflow(workflow_payload(job))


def claim_review_submit_attempt_started(
    *,
    session_id: str,
    agency_id: int,
    task_id: str | None,
) -> ReviewSubmitAttemptTransition:
    with transaction.atomic():
        job = (
            ImportJob.objects.select_for_update().filter(id=session_id, agency_id=agency_id).first()
        )
        if job is None:
            return ReviewSubmitAttemptTransition(
                job=None,
                payload={},
                status="missing",
                changed=False,
                reason="missing_job",
            )
        workflow = _workflow(job)
        payload = _payload_from_workflow(workflow)
        if not str(payload.get("task_id", "") or "").strip():
            payload["task_id"] = str(getattr(job, "task_id", "") or "")
        decision = claim_started_payload(
            payload=payload,
            task_id=task_id,
            attempt_type=ATTEMPT_REVIEW_SUBMIT,
            now_iso=_now_iso(),
            startable_statuses=REVIEW_SUBMIT_STARTABLE_STATUSES,
        )
        if not decision.changed:
            if decision.reason == "task_id_mismatch":
                logger.info(
                    "Stale review-submit attempt ignored at start claim",
                    extra={
                        "job_id": str(job.id),
                        "task_id": str(task_id or ""),
                        "current_task_id": str(payload.get("task_id", "") or ""),
                    },
                )
            return ReviewSubmitAttemptTransition(
                job=job,
                payload=payload,
                status=decision.status,
                changed=False,
                reason=decision.reason,
            )
        saved = _save_attempt(job, workflow, decision.payload)
        logger.info(
            "Review-submit attempt started",
            extra={
                "job_id": str(job.id),
                "attempt_id": str(saved.get("attempt_id", "") or ""),
                "task_id": str(saved.get("task_id", "") or ""),
            },
        )
        return ReviewSubmitAttemptTransition(
            job=job,
            payload=saved,
            status=ATTEMPT_STARTED,
            changed=True,
        )


def heartbeat_review_submit_attempt(
    *,
    job: ImportJob,
    task_id: str | None,
) -> ReviewSubmitAttemptTransition:
    with transaction.atomic():
        locked_job = _locked_job(job)
        if locked_job is None:
            return ReviewSubmitAttemptTransition(
                job=None, payload={}, status="missing", changed=False
            )
        workflow = _workflow(locked_job)
        payload = _payload_from_workflow(workflow)
        decision = heartbeat_payload(payload=payload, task_id=task_id, now_iso=_now_iso())
        if not decision.changed:
            logger.info(
                "Review-submit attempt heartbeat ignored",
                extra={
                    "job_id": str(locked_job.id),
                    "task_id": str(task_id or ""),
                    "status": decision.status,
                },
            )
            return ReviewSubmitAttemptTransition(
                job=locked_job,
                payload=payload,
                status=decision.status,
                changed=False,
                reason=decision.reason,
            )
        saved = _save_attempt(locked_job, workflow, decision.payload)
        return ReviewSubmitAttemptTransition(
            job=locked_job, payload=saved, status=ATTEMPT_STARTED, changed=True
        )


def assert_review_submit_attempt_current(*, job: ImportJob, task_id: str | None) -> ImportJob:
    transition = heartbeat_review_submit_attempt(job=job, task_id=task_id)
    if transition.job is None or not transition.changed:
        logger.info(
            "Stale review-submit attempt ignored",
            extra={
                "job_id": str(getattr(job, "id", "") or ""),
                "task_id": str(task_id or ""),
                "status": transition.status,
            },
        )
        raise StaleImportTaskAttemptError(
            attempt_type=ATTEMPT_REVIEW_SUBMIT,
            task_id=str(task_id or ""),
            status=transition.status,
        )
    return transition.job


def run_with_review_submit_attempt_fence(
    *,
    job: ImportJob,
    task_id: str | None,
    operation: str,
    fn: Callable[[ImportJob], _T],
) -> _T:
    with transaction.atomic():
        locked_job = _locked_job(job)
        if locked_job is None:
            raise StaleImportTaskAttemptError(
                attempt_type=ATTEMPT_REVIEW_SUBMIT,
                task_id=str(task_id or ""),
                status="missing",
            )
        workflow = _workflow(locked_job)
        payload = _payload_from_workflow(workflow)
        decision = heartbeat_payload(payload=payload, task_id=task_id, now_iso=_now_iso())
        if not decision.changed:
            logger.info(
                "Review-submit fenced write ignored",
                extra={
                    "job_id": str(locked_job.id),
                    "attempt_id": str(payload.get("attempt_id", "") or ""),
                    "task_id": str(task_id or ""),
                    "status": decision.status,
                    "operation": str(operation or ""),
                },
            )
            raise StaleImportTaskAttemptError(
                attempt_type=ATTEMPT_REVIEW_SUBMIT,
                task_id=str(task_id or ""),
                status=decision.status,
            )
        _save_attempt(locked_job, workflow, decision.payload)
        return fn(locked_job)


def request_review_submit_attempt_cancel(
    *,
    job: ImportJob,
    task_id: str | None,
    reason: str,
    clear_workflow_keys: Iterable[str] = (),
) -> ReviewSubmitAttemptTransition:
    with transaction.atomic():
        locked_job = _locked_job(job)
        if locked_job is None:
            return ReviewSubmitAttemptTransition(
                job=None, payload={}, status="missing", changed=False
            )
        workflow = _workflow(locked_job)
        payload = _payload_from_workflow(workflow)
        if not str(payload.get("task_id", "") or "").strip():
            payload["task_id"] = str(getattr(locked_job, "task_id", "") or "")
        decision = cancel_payload(
            payload=payload,
            task_id=task_id,
            now_iso=_now_iso(),
            reason=reason,
            cancellable_statuses=(ATTEMPT_STARTED,),
        )
        if not decision.changed:
            return ReviewSubmitAttemptTransition(
                job=locked_job,
                payload=payload,
                status=decision.status,
                changed=False,
                reason=decision.reason,
            )
        for clear_key in clear_workflow_keys:
            workflow.pop(str(clear_key), None)
        saved = _save_attempt(locked_job, workflow, decision.payload)
        logger.warning(
            "Review-submit attempt cancellation requested",
            extra={
                "job_id": str(locked_job.id),
                "attempt_id": str(saved.get("attempt_id", "") or ""),
                "task_id": str(saved.get("task_id", "") or ""),
                "cancel_reason": str(reason or ""),
            },
        )
        return ReviewSubmitAttemptTransition(
            job=locked_job, payload=saved, status=ATTEMPT_CANCELLED, changed=True
        )


def _finish_locked_attempt(
    *,
    job: ImportJob,
    workflow: dict[str, object],
    payload: Mapping[str, object],
    task_id: str | None,
    status: str,
    clear_workflow_keys: Iterable[str] = (),
) -> tuple[dict[str, object], bool]:
    decision = finish_payload(
        payload=payload,
        task_id=task_id,
        attempt_type=ATTEMPT_REVIEW_SUBMIT,
        requested_status=status,
        now_iso=_now_iso(),
    )
    if not decision.changed and decision.reason == "terminal_conflict":
        logger.warning(
            "Review-submit terminal transition ignored",
            extra={
                "job_id": str(job.id),
                "task_id": str(task_id or ""),
                "current_status": decision.status,
                "requested_status": str(status or ""),
            },
        )
    if not decision.changed:
        return decision.payload, False
    for clear_key in clear_workflow_keys:
        workflow.pop(str(clear_key), None)
    saved = _save_attempt(job, workflow, decision.payload)
    logger.info(
        "Review-submit terminal transition accepted",
        extra={
            "job_id": str(job.id),
            "attempt_id": str(saved.get("attempt_id", "") or ""),
            "task_id": str(saved.get("task_id", "") or ""),
            "status": str(status or ""),
        },
    )
    return saved, True


def finish_review_submit_attempt_fresh(
    *,
    job: ImportJob,
    task_id: str | None,
    status: str,
    clear_workflow_keys: Iterable[str] = (),
) -> ReviewSubmitAttemptTransition:
    with transaction.atomic():
        locked_job = _locked_job(job)
        if locked_job is None:
            return ReviewSubmitAttemptTransition(
                job=None, payload={}, status="missing", changed=False
            )
        workflow = _workflow(locked_job)
        payload = _payload_from_workflow(workflow)
        saved, changed = _finish_locked_attempt(
            job=locked_job,
            workflow=workflow,
            payload=payload,
            task_id=task_id,
            status=status,
            clear_workflow_keys=clear_workflow_keys,
        )
        return ReviewSubmitAttemptTransition(
            job=locked_job,
            payload=saved,
            status=str(saved.get("status", "") or status),
            changed=changed,
        )


def run_review_submit_terminal_section(
    *,
    job: ImportJob,
    task_id: str | None,
    operation: str,
    success_status: str,
    clear_workflow_keys: Iterable[str],
    fn: Callable[
        [
            ImportJob,
            Callable[[str, Iterable[str]], dict[str, object]],
        ],
        _T,
    ],
    handle_exception: Callable[
        [
            ImportJob,
            Exception,
            Callable[[str, Iterable[str]], dict[str, object]],
        ],
        _T,
    ],
) -> _T:
    """Run irreversible review-submit work and terminal finish under one fence."""

    with transaction.atomic():
        locked_job = _locked_job(job)
        if locked_job is None:
            raise StaleImportTaskAttemptError(
                attempt_type=ATTEMPT_REVIEW_SUBMIT,
                task_id=str(task_id or ""),
                status="missing",
            )
        workflow = _workflow(locked_job)
        payload = _payload_from_workflow(workflow)
        current = is_attempt_current(payload=payload, task_id=task_id)
        if not current.changed:
            logger.info(
                "Review-submit terminal section ignored",
                extra={
                    "job_id": str(locked_job.id),
                    "attempt_id": str(payload.get("attempt_id", "") or ""),
                    "task_id": str(task_id or ""),
                    "status": current.status,
                    "operation": str(operation or ""),
                },
            )
            raise StaleImportTaskAttemptError(
                attempt_type=ATTEMPT_REVIEW_SUBMIT,
                task_id=str(task_id or ""),
                status=current.status,
            )
        heartbeat = heartbeat_payload(payload=payload, task_id=task_id, now_iso=_now_iso())
        _save_attempt(locked_job, workflow, heartbeat.payload)

        def finish_current(
            status: str,
            keys_to_clear: Iterable[str] = clear_workflow_keys,
        ) -> dict[str, object]:
            latest_workflow = _workflow(locked_job)
            latest_payload = _payload_from_workflow(latest_workflow)
            saved, _changed = _finish_locked_attempt(
                job=locked_job,
                workflow=latest_workflow,
                payload=latest_payload,
                task_id=task_id,
                status=status,
                clear_workflow_keys=keys_to_clear,
            )
            return saved

        try:
            result = fn(locked_job, finish_current)
        except Exception as exc:
            return handle_exception(locked_job, exc, finish_current)
        finish_current(success_status, clear_workflow_keys)
        return result


__all__ = [
    "ATTEMPT_CANCELLED",
    "ATTEMPT_COMPLETED",
    "ATTEMPT_CONFLICT",
    "ATTEMPT_FAILED",
    "ATTEMPT_PENDING",
    "ATTEMPT_PUBLISHED",
    "ATTEMPT_PUBLISH_FAILED",
    "ATTEMPT_REVIEW_SUBMIT",
    "ATTEMPT_STARTED",
    "ATTEMPT_STALE_IGNORED",
    "ATTEMPT_TERMINAL_STATUSES",
    "REVIEW_SUBMIT_ATTEMPT_WORKFLOW_KEY",
    "ReviewSubmitAttemptTransition",
    "StaleImportTaskAttemptError",
    "assert_review_submit_attempt_current",
    "begin_review_submit_attempt",
    "claim_review_submit_attempt_started",
    "finish_review_submit_attempt_fresh",
    "heartbeat_review_submit_attempt",
    "request_review_submit_attempt_cancel",
    "review_submit_attempt_payload",
    "run_review_submit_terminal_section",
    "run_with_review_submit_attempt_fence",
]
