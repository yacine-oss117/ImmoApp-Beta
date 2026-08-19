"""UserActionToken mechanics for account reset and invite-activation flows."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import timedelta
from typing import Any, Callable, cast

from django.utils import timezone

from server.accounts.models import UserActionToken
from server.services.errors import PermissionDeniedError

_PASSWORD_RESET_TTL_SECONDS_DEFAULT = 1800
_INVITE_TTL_SECONDS_DEFAULT = 72 * 3600


def _bounded_int_env(name: str, default: int, *, min_v: int, max_v: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_v, min(max_v, value))


def _password_reset_ttl_seconds() -> int:
    return _bounded_int_env(
        "IMMOAPP_PASSWORD_RESET_TTL_SECONDS",
        _PASSWORD_RESET_TTL_SECONDS_DEFAULT,
        min_v=300,
        max_v=86400,
    )


def _invite_ttl_seconds(expires_seconds: int | None = None) -> int:
    if expires_seconds is None:
        return _bounded_int_env(
            "IMMOAPP_INVITE_TTL_SECONDS",
            _INVITE_TTL_SECONDS_DEFAULT,
            min_v=900,
            max_v=7 * 86400,
        )
    return max(900, min(7 * 86400, int(expires_seconds)))


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _new_raw_token() -> str:
    return secrets.token_urlsafe(32)


def _issue_token_record(
    *,
    purpose: str,
    user: Any,
    issued_by: object | None,
    ttl_seconds: int,
    metadata: dict[str, object] | None = None,
    agency_id_of_fn: Callable[[object | None], int | None],
) -> tuple[UserActionToken, str]:
    agency_id = agency_id_of_fn(user)
    if agency_id is None:
        raise ValueError("User must belong to an agency for token issuance.")
    raw_token = _new_raw_token()
    record = UserActionToken.objects.create(
        token_hash=_hash_token(raw_token),
        purpose=purpose,
        agency_id=agency_id,
        user=user,
        issued_by=issued_by if hasattr(issued_by, "pk") else None,
        expires_at=timezone.now() + timedelta(seconds=ttl_seconds),
        metadata=metadata or {},
    )
    return record, raw_token


def _consume_token_or_raise(
    *,
    token: str,
    purpose: str,
    reason_prefix: str,
    request_id: str | None,
    source_ip: str | None,
    user_agent: str | None,
    auth_events_module: Any,
    safe_user_identifier_fn: Callable[[Any | None], str | None],
) -> UserActionToken:
    token_value = token.strip()
    if not token_value:
        raise PermissionDeniedError("Token is required.")
    now = timezone.now()
    record = (
        UserActionToken.objects.select_for_update()
        .select_related("user")
        .filter(token_hash=_hash_token(token_value), purpose=purpose)
        .first()
    )
    if record is None:
        auth_events_module.log_auth_event(
            event_type=reason_prefix,
            outcome="failure",
            reason_code="invalid_token",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            fail_silently=True,
        )
        raise PermissionDeniedError("Invalid or expired token.")
    if record.consumed_at is not None:
        record_user_id = getattr(record, "user_id", None)
        record_agency_id = getattr(record, "agency_id", None)
        auth_events_module.log_auth_event(
            event_type=reason_prefix,
            outcome="failure",
            user_id=int(record_user_id) if record_user_id is not None else None,
            agency_id=int(record_agency_id) if record_agency_id is not None else None,
            identifier=safe_user_identifier_fn(record.user),
            reason_code="token_consumed",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={"token_id": str(record.token_id)},
            fail_silently=True,
        )
        raise PermissionDeniedError("Invalid or expired token.")
    if record.expires_at <= now:
        record_user_id = getattr(record, "user_id", None)
        record_agency_id = getattr(record, "agency_id", None)
        auth_events_module.log_auth_event(
            event_type=reason_prefix,
            outcome="failure",
            user_id=int(record_user_id) if record_user_id is not None else None,
            agency_id=int(record_agency_id) if record_agency_id is not None else None,
            identifier=safe_user_identifier_fn(record.user),
            reason_code="token_expired",
            request_id=request_id,
            source_ip=source_ip,
            user_agent=user_agent,
            details={"token_id": str(record.token_id)},
            fail_silently=True,
        )
        raise PermissionDeniedError("Invalid or expired token.")
    return cast(UserActionToken, record)
