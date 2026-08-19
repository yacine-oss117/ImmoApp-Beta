"""Security alert helpers for suspicious auth/privilege patterns."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from django.core.cache import cache

from server.services import auth_events


def _int_env(name: str, default: int, *, low: int, high: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(low, min(high, value))


_ALERT_COOLDOWN_SECONDS = _int_env(
    "IMMOAPP_SECURITY_ALERT_COOLDOWN_SECONDS",
    300,
    low=30,
    high=3600,
)
_REFRESH_FAILURE_WINDOW_SECONDS = _int_env(
    "IMMOAPP_REFRESH_FAILURE_WINDOW_SECONDS",
    600,
    low=60,
    high=3600,
)
_REFRESH_FAILURE_THRESHOLD = _int_env(
    "IMMOAPP_REFRESH_FAILURE_ALERT_THRESHOLD",
    10,
    low=3,
    high=100,
)


def _cooldown_key(*parts: object) -> str:
    normalized = ":".join(str(part or "").strip().lower() for part in parts)
    return f"immoapp:sec-alert:{normalized}"


def emit_security_alert(
    *,
    reason_code: str,
    agency_id: int | None,
    user_id: int | None,
    identifier: str | None,
    source_ip: str | None,
    user_agent: str | None = None,
    request_id: str | None = None,
    details: Mapping[str, Any] | None = None,
    cooldown_identity: str | None = None,
) -> None:
    key = _cooldown_key(reason_code, cooldown_identity or identifier or source_ip or "global")
    if not cache.add(key, "1", timeout=_ALERT_COOLDOWN_SECONDS):
        return
    auth_events.log_auth_event(
        event_type="security_alert",
        outcome="alert",
        agency_id=agency_id,
        user_id=user_id,
        identifier=identifier,
        reason_code=reason_code,
        source_ip=source_ip,
        user_agent=user_agent,
        request_id=request_id,
        details=details,
        fail_silently=True,
    )


def record_refresh_failure(
    *,
    agency_id: int | None,
    user_id: int | None,
    source_ip: str | None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> None:
    identity = f"{agency_id or 'none'}:{user_id or 'none'}:{source_ip or 'none'}"
    key = f"immoapp:refresh-fail:{identity}"
    current = cache.get(key)
    try:
        count = int(current) + 1
    except Exception:
        count = 1
    cache.set(key, count, timeout=_REFRESH_FAILURE_WINDOW_SECONDS)
    if count < _REFRESH_FAILURE_THRESHOLD:
        return
    emit_security_alert(
        reason_code="token_refresh_abuse",
        agency_id=agency_id,
        user_id=user_id,
        identifier=str(user_id) if user_id else None,
        source_ip=source_ip,
        user_agent=user_agent,
        request_id=request_id,
        details={
            "window_seconds": _REFRESH_FAILURE_WINDOW_SECONDS,
            "threshold": _REFRESH_FAILURE_THRESHOLD,
            "count": count,
        },
        cooldown_identity=identity,
    )


__all__ = ["emit_security_alert", "record_refresh_failure"]
