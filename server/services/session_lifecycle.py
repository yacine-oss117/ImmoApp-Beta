"""Session issuance, validation, touch, and cache management helpers."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.utils import timezone

from core.env_flags import require_session_id_claim
from server.accounts.models import UserSession

_SESSION_VALIDATION_CACHE_LOCK = threading.Lock()
_SESSION_VALIDATION_CACHE: dict[tuple[int, str], tuple[float, datetime]] = {}


def _refresh_days() -> int:
    raw = os.environ.get("JWT_REFRESH_DAYS", "1").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 1
    return max(1, min(value, 30))


def _session_lifetime() -> timedelta:
    seconds_raw = os.environ.get("IMMOAPP_SESSION_LIFETIME_SECONDS", "").strip()
    if seconds_raw:
        try:
            sec = int(seconds_raw)
            return timedelta(seconds=max(300, min(sec, 60 * 60 * 24 * 30)))
        except ValueError:
            pass
    return timedelta(days=_refresh_days())


def _session_validate_cache_seconds() -> float:
    raw = os.environ.get("IMMOAPP_SESSION_VALIDATE_CACHE_SECONDS", "15").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 15.0
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return 0.0
    return max(0.0, min(value, 120.0))


def _session_touch_min_interval_seconds() -> int:
    raw = os.environ.get("IMMOAPP_SESSION_TOUCH_MIN_INTERVAL_SECONDS", "60").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 60
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return 0
    return max(0, min(value, 3600))


def _invalidate_validation_cache(
    *, user_id: int | None = None, session_id: UUID | None = None
) -> None:
    with _SESSION_VALIDATION_CACHE_LOCK:
        if user_id is None and session_id is None:
            _SESSION_VALIDATION_CACHE.clear()
            return
        sid_text = str(session_id) if session_id is not None else None
        doomed: list[tuple[int, str]] = []
        for key_user_id, key_session_id in _SESSION_VALIDATION_CACHE.keys():
            if user_id is not None and key_user_id != user_id:
                continue
            if sid_text is not None and key_session_id != sid_text:
                continue
            doomed.append((key_user_id, key_session_id))
        for key in doomed:
            _SESSION_VALIDATION_CACHE.pop(key, None)


def _to_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return UUID(text)
    except ValueError:
        return None


def _token_iat_to_dt(iat: object) -> datetime | None:
    if not isinstance(iat, (int, float)):
        return None
    return datetime.fromtimestamp(float(iat), tz=dt_timezone.utc)


def _live_user_is_active(user: Any) -> bool:
    if not bool(getattr(user, "is_active", False)):
        return False
    user_id = getattr(user, "id", None)
    if not isinstance(user_id, int):
        return False
    User = get_user_model()
    return bool(User.objects.filter(id=user_id, is_active=True).exists())


def issue_session_impl(
    *,
    user: Any,
    source_ip: str | None,
    user_agent: str | None,
) -> UserSession:
    now = timezone.now()
    return cast(
        UserSession,
        UserSession.objects.create(
            session_id=uuid4(),
            user=user,
            agency_id=getattr(user, "agency_id", None),
            source_ip=str(source_ip or "")[:64],
            user_agent=str(user_agent or "")[:512],
            last_seen_at=now,
            expires_at=now + _session_lifetime(),
        ),
    )


def bind_refresh_jti_impl(*, session_id: object, refresh_jti: str | None) -> None:
    sid = _to_uuid(session_id)
    if sid is None:
        return
    now = timezone.now()
    UserSession.objects.filter(session_id=sid, revoked_at__isnull=True).update(
        refresh_jti=str(refresh_jti or "")[:64],
        last_seen_at=now,
        expires_at=now + _session_lifetime(),
    )


def touch_session_impl(*, session_id: object) -> None:
    sid = _to_uuid(session_id)
    if sid is None:
        return
    UserSession.objects.filter(session_id=sid, revoked_at__isnull=True).update(
        last_seen_at=timezone.now()
    )


def validate_token_session_impl(
    *,
    user: Any,
    session_id: object,
    token_iat: object,
) -> tuple[bool, str | None]:
    if not _live_user_is_active(user):
        resolved_user_id = getattr(user, "id", None)
        if isinstance(resolved_user_id, int):
            _invalidate_validation_cache(user_id=resolved_user_id)
        return False, "user_inactive"

    iat_dt = _token_iat_to_dt(token_iat)
    invalid_before = getattr(user, "session_invalid_before", None)
    if invalid_before is not None and iat_dt is not None and iat_dt <= invalid_before:
        return False, "session_revoked_before_iat"

    sid = _to_uuid(session_id)
    require_sid = require_session_id_claim()
    if sid is None:
        return (False, "missing_session_id") if require_sid else (True, None)

    resolved_user_id = getattr(user, "id", None)
    cache_ttl = _session_validate_cache_seconds()
    cache_key: tuple[int, str] | None = None
    if isinstance(resolved_user_id, int):
        cache_key = (resolved_user_id, str(sid))
        if cache_ttl > 0:
            now_mono = time.monotonic()
            with _SESSION_VALIDATION_CACHE_LOCK:
                cache_entry = _SESSION_VALIDATION_CACHE.get(cache_key)
            if cache_entry is not None:
                cache_deadline, session_expires_at = cache_entry
                if cache_deadline > now_mono and session_expires_at > timezone.now():
                    row_state = (
                        UserSession.objects.filter(
                            session_id=sid,
                            user_id=getattr(user, "id", None),
                        )
                        .values_list("expires_at", "revoked_at")
                        .first()
                    )
                    if row_state is None:
                        _invalidate_validation_cache(user_id=cache_key[0], session_id=sid)
                        return False, "session_not_found"
                    row_expires_at, row_revoked_at = row_state
                    if row_revoked_at is not None:
                        _invalidate_validation_cache(user_id=cache_key[0], session_id=sid)
                        return False, "session_revoked"
                    now = timezone.now()
                    if row_expires_at <= now:
                        _invalidate_validation_cache(user_id=cache_key[0], session_id=sid)
                        return False, "session_expired"
                    if row_expires_at != session_expires_at:
                        with _SESSION_VALIDATION_CACHE_LOCK:
                            _SESSION_VALIDATION_CACHE[cache_key] = (cache_deadline, row_expires_at)
                    return True, None
                _invalidate_validation_cache(user_id=cache_key[0], session_id=sid)

    row = UserSession.objects.filter(session_id=sid, user_id=getattr(user, "id", None)).first()
    if row is None:
        if cache_key is not None:
            _invalidate_validation_cache(user_id=cache_key[0], session_id=sid)
        return False, "session_not_found"
    if row.revoked_at is not None:
        if cache_key is not None:
            _invalidate_validation_cache(user_id=cache_key[0], session_id=sid)
        return False, "session_revoked"
    now = timezone.now()
    if row.expires_at <= now:
        if cache_key is not None:
            _invalidate_validation_cache(user_id=cache_key[0], session_id=sid)
        return False, "session_expired"

    touch_interval = _session_touch_min_interval_seconds()
    if touch_interval <= 0:
        touch_session_impl(session_id=sid)
    else:
        last_seen_at = row.last_seen_at
        should_touch = (
            last_seen_at is None or (now - last_seen_at).total_seconds() >= touch_interval
        )
        if should_touch:
            UserSession.objects.filter(
                session_id=sid,
                user_id=getattr(user, "id", None),
                revoked_at__isnull=True,
            ).update(last_seen_at=now)

    if cache_key is not None and cache_ttl > 0:
        with _SESSION_VALIDATION_CACHE_LOCK:
            _SESSION_VALIDATION_CACHE[cache_key] = (time.monotonic() + cache_ttl, row.expires_at)
    return True, None
