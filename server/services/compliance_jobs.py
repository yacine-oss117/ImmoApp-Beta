"""Compliance export/delete job orchestration."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from server.accounts.models import ComplianceJob, UserSession
from server.services import auth_events, auth_sessions
from server.services.errors import NotFoundError, PermissionDeniedError
from server.services.users_helpers import agency_id_of, is_superuser, require_owner

logger = logging.getLogger(__name__)


class JobAlreadyActiveError(RuntimeError):
    """Raised when an active compliance job already exists for the same scope."""

    def __init__(self, message: str, *, job_id: str) -> None:
        super().__init__(message)
        self.job_id = job_id


def _artifact_ttl_hours() -> int:
    raw = os.environ.get("IMMOAPP_COMPLIANCE_ARTIFACT_TTL_HOURS", "168").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 168
    return max(24, min(value, 24 * 30))


def _safe_actor_id(actor: object | None) -> int | None:
    value = getattr(actor, "id", None) if actor is not None else None
    return int(value) if value is not None else None


def _serialize_job(row: ComplianceJob) -> dict[str, object]:
    return {
        "job_id": str(row.job_id),
        "agency_id": int(row.agency_id),
        "target_user_id": int(row.target_user_id),
        "requested_by_id": int(row.requested_by_id) if row.requested_by_id else None,
        "job_type": str(row.job_type),
        "status": str(row.status),
        "step_up_verified_at": row.step_up_verified_at.isoformat(),
        "error_code": str(row.error_code or ""),
        "artifact_path": str(row.artifact_path or ""),
        "artifact_sha256": str(row.artifact_sha256 or ""),
        "artifact_size_bytes": int(row.artifact_size_bytes or 0),
        "artifact_content_type": str(row.artifact_content_type or ""),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


def _assert_same_agency(actor: object, target_user: object) -> None:
    if is_superuser(actor):
        return
    actor_agency_id = agency_id_of(actor)
    target_agency_id = agency_id_of(target_user)
    if (
        actor_agency_id is None
        or target_agency_id is None
        or int(actor_agency_id) != int(target_agency_id)
    ):
        raise PermissionDeniedError("Forbidden agency scope.")


def _resolve_target_user(actor: object, target_user_id: int):
    User = get_user_model()
    target = User.objects.filter(id=int(target_user_id)).first()
    if target is None:
        raise NotFoundError("User not found.")
    _assert_same_agency(actor, target)
    return target


def _existing_active_job(
    *, agency_id: int, target_user_id: int, job_type: str
) -> ComplianceJob | None:
    return (
        ComplianceJob.objects.filter(
            agency_id=agency_id,
            target_user_id=target_user_id,
            job_type=job_type,
            status__in=ComplianceJob.ACTIVE_STATUSES,
        )
        .order_by("-created_at", "-id")
        .first()
    )


def _create_job(
    *,
    actor: object,
    target_user_id: int,
    job_type: str,
    step_up_verified_at,
    reason: str | None = None,
) -> dict[str, object]:
    require_owner(actor)
    target = _resolve_target_user(actor, target_user_id)
    actor_id = _safe_actor_id(actor)
    if (
        job_type == ComplianceJob.TYPE_DELETE
        and actor_id is not None
        and int(target.id) == actor_id
    ):
        raise PermissionDeniedError(
            "Cannot run compliance delete on your own account. "
            "Transfer ownership first or ask another owner."
        )
    if job_type == ComplianceJob.TYPE_DELETE and bool(getattr(target, "is_owner", False)):
        User = get_user_model()
        active_owner_count = User.objects.filter(
            agency_id=int(target.agency_id),
            is_owner=True,
            is_active=True,
        ).count()
        if active_owner_count <= 1:
            raise PermissionDeniedError(
                "Cannot delete the last owner of an agency. "
                "Transfer ownership to another team member first."
            )
    agency_id = int(target.agency_id)
    reason_text = str(reason or "").strip()[:512]
    with transaction.atomic():
        existing = _existing_active_job(
            agency_id=agency_id,
            target_user_id=int(target.id),
            job_type=job_type,
        )
        if existing is not None:
            raise JobAlreadyActiveError(
                "An active compliance job already exists for this user and job type.",
                job_id=str(existing.job_id),
            )
        row = ComplianceJob.objects.create(
            agency_id=agency_id,
            target_user_id=int(target.id),
            requested_by_id=actor_id,
            job_type=job_type,
            status=ComplianceJob.STATUS_QUEUED,
            step_up_verified_at=step_up_verified_at,
            payload_json={"reason": reason_text} if reason_text else {},
            result_json={},
        )
    auth_events.log_auth_event(
        event_type=f"compliance_{job_type}_requested",
        outcome="success",
        agency_id=agency_id,
        user_id=int(target.id),
        identifier=str(getattr(target, "username", "") or ""),
        reason_code=job_type,
        details={"job_id": str(row.job_id)},
        fail_silently=True,
    )
    return _serialize_job(row)


def create_export_job(
    *,
    actor: object,
    target_user_id: int,
    step_up_verified_at,
    reason: str | None = None,
) -> dict[str, object]:
    return _create_job(
        actor=actor,
        target_user_id=target_user_id,
        job_type=ComplianceJob.TYPE_EXPORT,
        step_up_verified_at=step_up_verified_at,
        reason=reason,
    )


def create_delete_job(
    *,
    actor: object,
    target_user_id: int,
    step_up_verified_at,
    reason: str | None = None,
) -> dict[str, object]:
    return _create_job(
        actor=actor,
        target_user_id=target_user_id,
        job_type=ComplianceJob.TYPE_DELETE,
        step_up_verified_at=step_up_verified_at,
        reason=reason,
    )


def _job_for_actor(
    *, actor: object, job_id: str | uuid.UUID, for_update: bool = False
) -> ComplianceJob:
    qs = ComplianceJob.objects
    if for_update:
        qs = qs.select_for_update()
    row = qs.filter(job_id=job_id).first()
    if row is None:
        raise NotFoundError("Compliance job not found.")
    if not is_superuser(actor):
        actor_agency_id = agency_id_of(actor)
        if actor_agency_id is None or int(actor_agency_id) != int(row.agency_id):
            raise PermissionDeniedError("Forbidden agency scope.")
    return row


def get_job(*, actor: object, job_id: str | uuid.UUID) -> dict[str, object]:
    row = _job_for_actor(actor=actor, job_id=job_id, for_update=False)
    return _serialize_job(row)


def _mark_running(row: ComplianceJob) -> None:
    now = timezone.now()
    row.status = ComplianceJob.STATUS_RUNNING
    row.started_at = row.started_at or now
    row.error_code = ""
    row.save(update_fields=["status", "started_at", "error_code"])


def _mark_failed(row: ComplianceJob, *, error_code: str) -> None:
    now = timezone.now()
    row.status = ComplianceJob.STATUS_FAILED
    row.error_code = error_code[:128]
    row.finished_at = now
    row.expires_at = now + timedelta(hours=_artifact_ttl_hours())
    row.save(update_fields=["status", "error_code", "finished_at", "expires_at"])


def _mark_succeeded(
    row: ComplianceJob,
    *,
    result_json: dict[str, Any],
    artifact_content_type: str = "application/json",
) -> None:
    payload_bytes = json.dumps(
        result_json,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    now = timezone.now()
    row.status = ComplianceJob.STATUS_SUCCEEDED
    row.result_json = result_json
    row.artifact_content_type = artifact_content_type
    row.artifact_size_bytes = len(payload_bytes)
    row.artifact_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    row.artifact_path = ""
    row.finished_at = now
    row.expires_at = now + timedelta(hours=_artifact_ttl_hours())
    row.save(
        update_fields=[
            "status",
            "result_json",
            "artifact_content_type",
            "artifact_size_bytes",
            "artifact_sha256",
            "artifact_path",
            "finished_at",
            "expires_at",
        ]
    )


def _build_export_payload(row: ComplianceJob) -> dict[str, Any]:
    User = get_user_model()
    target = User.objects.filter(id=row.target_user_id).first()
    if target is None:
        raise NotFoundError("User not found.")
    sessions_total = UserSession.objects.filter(user_id=target.id).count()
    active_sessions = UserSession.objects.filter(user_id=target.id, revoked_at__isnull=True).count()
    return {
        "schema": "immoapp.compliance.export.v1",
        "job_id": str(row.job_id),
        "generated_at": timezone.now().isoformat(),
        "subject": {
            "user_id": int(target.id),
            "username": str(target.username or ""),
            "email": str(target.email or ""),
            "first_name": str(target.first_name or ""),
            "last_name": str(target.last_name or ""),
            "role": str(target.role or ""),
            "agency_id": int(target.agency_id),
            "is_active": bool(target.is_active),
            "mfa_totp_enabled": bool(target.mfa_totp_enabled),
            "session_count_total": int(sessions_total),
            "session_count_active": int(active_sessions),
        },
    }


def _run_delete(row: ComplianceJob) -> dict[str, Any]:
    User = get_user_model()
    target = User.objects.filter(id=row.target_user_id).first()
    if target is None:
        raise NotFoundError("User not found.")
    if bool(getattr(target, "is_superuser", False)):
        raise PermissionDeniedError("Cannot run compliance delete for superuser.")
    now = timezone.now()
    pseudonym = f"deleted-{target.id}-{uuid.uuid4().hex[:8]}"
    target.username = pseudonym[:150]
    target.email = ""
    target.first_name = ""
    target.first_name_enc = ""
    target.first_name_search_src = ""
    target.last_name = ""
    target.last_name_enc = ""
    target.last_name_search_src = ""
    target.is_active = False
    target.mfa_totp_enabled = False
    target.mfa_totp_secret = ""
    target.mfa_totp_secret_enc = ""
    target.mfa_totp_enrolled_at = None
    target.can_import = False
    target.can_hard_delete = False
    target.is_owner = False
    target.session_invalid_before = now
    if hasattr(target, "set_unusable_password"):
        target.set_unusable_password()
    target.save(validate=False)
    auth_sessions.revoke_user_sessions(user=target, reason="compliance_delete")
    return {
        "schema": "immoapp.compliance.delete.v1",
        "job_id": str(row.job_id),
        "deleted_at": now.isoformat(),
        "subject": {
            "user_id": int(target.id),
            "pseudonymized_username": str(target.username),
            "agency_id": int(target.agency_id),
        },
    }


def _emit_user_job_notification(
    *,
    row: ComplianceJob,
    event_type: str,
    title: str,
    body: str,
) -> None:
    requested_by_id = row.requested_by_id
    if requested_by_id is None:
        return
    try:
        from server.api.notifications import record_and_notify
        from server.pg.uow import use_security_context

        with use_security_context(agency_id=int(row.agency_id), is_superuser=False):
            record_and_notify(
                scope="user",
                event_type=event_type,
                title=title,
                body=body,
                user_id=int(requested_by_id),
                data={"job_id": str(row.job_id), "job_type": str(row.job_type)},
            )
    except Exception:
        logger.warning("Failed to emit compliance job notification", exc_info=True)


def run_export_job(*, job_id: str | uuid.UUID) -> dict[str, object]:
    with transaction.atomic():
        row = ComplianceJob.objects.select_for_update().filter(job_id=job_id).first()
        if row is None:
            raise NotFoundError("Compliance job not found.")
        if row.status not in ComplianceJob.ACTIVE_STATUSES:
            return _serialize_job(row)
        _mark_running(row)
    try:
        payload = _build_export_payload(row)
    except Exception:
        with transaction.atomic():
            latest = ComplianceJob.objects.select_for_update().get(id=row.id)
            _mark_failed(latest, error_code="EXPORT_FAILED")
            _emit_user_job_notification(
                row=latest,
                event_type="compliance.job_failed",
                title="Request failed",
                body="Your data export request failed. Please try again.",
            )
            return _serialize_job(latest)
    with transaction.atomic():
        latest = ComplianceJob.objects.select_for_update().get(id=row.id)
        _mark_succeeded(latest, result_json=payload, artifact_content_type="application/json")
        _emit_user_job_notification(
            row=latest,
            event_type="compliance.job_completed",
            title="Request completed",
            body="Your data export is ready.",
        )
        return _serialize_job(latest)


def run_delete_job(*, job_id: str | uuid.UUID) -> dict[str, object]:
    with transaction.atomic():
        row = ComplianceJob.objects.select_for_update().filter(job_id=job_id).first()
        if row is None:
            raise NotFoundError("Compliance job not found.")
        if row.status not in ComplianceJob.ACTIVE_STATUSES:
            return _serialize_job(row)
        _mark_running(row)
    try:
        payload = _run_delete(row)
    except Exception:
        with transaction.atomic():
            latest = ComplianceJob.objects.select_for_update().get(id=row.id)
            _mark_failed(latest, error_code="DELETE_FAILED")
            _emit_user_job_notification(
                row=latest,
                event_type="compliance.job_failed",
                title="Request failed",
                body="Your delete request failed. Please try again.",
            )
            return _serialize_job(latest)
    with transaction.atomic():
        latest = ComplianceJob.objects.select_for_update().get(id=row.id)
        _mark_succeeded(latest, result_json=payload, artifact_content_type="application/json")
        _emit_user_job_notification(
            row=latest,
            event_type="compliance.job_completed",
            title="Request completed",
            body="Your delete request is complete.",
        )
        return _serialize_job(latest)


def get_export_artifact(*, actor: object, job_id: str | uuid.UUID) -> tuple[str, bytes]:
    row = _job_for_actor(actor=actor, job_id=job_id, for_update=False)
    if row.job_type != ComplianceJob.TYPE_EXPORT:
        raise NotFoundError("Export artifact not found.")
    if row.status != ComplianceJob.STATUS_SUCCEEDED:
        raise ValueError("Export artifact is not ready.")
    payload = row.result_json if isinstance(row.result_json, dict) else {}
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    return str(row.artifact_content_type or "application/json"), body


__all__ = [
    "JobAlreadyActiveError",
    "create_delete_job",
    "create_export_job",
    "get_export_artifact",
    "get_job",
    "run_delete_job",
    "run_export_job",
]
