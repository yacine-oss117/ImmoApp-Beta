"""Session listing and revocation helpers."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from server.accounts.models import UserSession
from server.services import session_lifecycle
from server.services.errors import NotFoundError, PermissionDeniedError


def _iso_or_none(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def list_user_sessions_impl(*, user: Any) -> list[dict[str, object]]:
    rows = (
        UserSession.objects.filter(user=user)
        .order_by("-last_seen_at", "-id")
        .values(
            "session_id",
            "source_ip",
            "user_agent",
            "created_at",
            "last_seen_at",
            "expires_at",
            "revoked_at",
            "revoke_reason",
        )
    )
    return [
        {
            "session_id": str(row["session_id"]),
            "source_ip": str(row.get("source_ip") or ""),
            "user_agent": str(row.get("user_agent") or ""),
            "created_at": _iso_or_none(row.get("created_at")),
            "last_seen_at": _iso_or_none(row.get("last_seen_at")),
            "expires_at": _iso_or_none(row.get("expires_at")),
            "revoked_at": _iso_or_none(row.get("revoked_at")),
            "revoke_reason": str(row.get("revoke_reason") or ""),
        }
        for row in rows
    ]


def revoke_session_impl(*, actor: Any, session_id: object, reason: str = "user_revoke") -> None:
    sid = session_lifecycle._to_uuid(session_id)
    if sid is None:
        raise ValueError("session_id must be a valid UUID")
    session = UserSession.objects.filter(session_id=sid).first()
    if session is None:
        raise NotFoundError("Session not found.")
    session_user_id = getattr(session, "user_id", None)
    if not getattr(actor, "is_superuser", False) and session_user_id != getattr(actor, "id", None):
        raise PermissionDeniedError("Forbidden session scope.")
    if session.revoked_at is None:
        session.revoked_at = timezone.now()
        session.revoke_reason = reason[:64]
        session.save(update_fields=["revoked_at", "revoke_reason"])
        if session_user_id is not None:
            session_lifecycle._invalidate_validation_cache(
                user_id=int(session_user_id),
                session_id=sid,
            )


def revoke_all_sessions_impl(*, actor: Any, except_session_id: object | None = None) -> int:
    if getattr(actor, "id", None) is None:
        return 0
    qs = UserSession.objects.filter(user_id=actor.id, revoked_at__isnull=True)
    exclude_sid = session_lifecycle._to_uuid(except_session_id)
    if exclude_sid is not None:
        qs = qs.exclude(session_id=exclude_sid)
    now = timezone.now()
    count = qs.update(revoked_at=now, revoke_reason="bulk_revoke")
    actor.session_invalid_before = now
    actor.save(update_fields=["session_invalid_before"])
    session_lifecycle._invalidate_validation_cache(user_id=int(actor.id))
    return int(count)


def revoke_user_sessions_impl(*, user: Any, reason: str = "user_deactivated") -> int:
    user_id = getattr(user, "id", None)
    if not isinstance(user_id, int):
        return 0
    now = timezone.now()
    with transaction.atomic():
        count = UserSession.objects.filter(user_id=user_id, revoked_at__isnull=True).update(
            revoked_at=now,
            revoke_reason=str(reason or "user_deactivated")[:64],
        )
        user.session_invalid_before = now
        user.save(update_fields=["session_invalid_before"], validate=False)
    session_lifecycle._invalidate_validation_cache(user_id=user_id)
    return int(count)
