"""Brute-force lockout controls for credential endpoints."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from django.core.cache import cache

from server.services import auth_security_alerts


def _int_env(name: str, default: int, *, low: int, high: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(low, min(high, value))


_FAILURE_WINDOW_SECONDS = _int_env(
    "IMMOAPP_AUTH_FAILURE_WINDOW_SECONDS",
    900,
    low=60,
    high=24 * 3600,
)
_FAILURE_THRESHOLD = _int_env(
    "IMMOAPP_AUTH_FAILURE_THRESHOLD",
    6,
    low=3,
    high=100,
)
_LOCK_SECONDS = _int_env(
    "IMMOAPP_AUTH_LOCK_SECONDS",
    900,
    low=60,
    high=24 * 3600,
)


def _normalize(value: str | None) -> str:
    return str(value or "").strip().lower()


def _identity(identifier: str | None, source_ip: str | None) -> str:
    return f"{_normalize(identifier)}:{_normalize(source_ip)}"


def _count_key(identity: str) -> str:
    return f"immoapp:auth-failure:{identity}"


def _lock_key(identity: str) -> str:
    return f"immoapp:auth-lock:{identity}"


def locked_until(*, identifier: str | None, source_ip: str | None) -> datetime | None:
    identity = _identity(identifier, source_ip)
    ts = cache.get(_lock_key(identity))
    if ts is None:
        return None
    try:
        unix_ts = float(ts)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc)


def clear_failures(*, identifier: str | None, source_ip: str | None) -> None:
    identity = _identity(identifier, source_ip)
    cache.delete_many([_count_key(identity), _lock_key(identity)])


def record_failure(
    *,
    identifier: str | None,
    source_ip: str | None,
    agency_id: int | None,
    user_id: int | None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> datetime | None:
    identity = _identity(identifier, source_ip)
    count_key = _count_key(identity)
    lock_key = _lock_key(identity)

    current = cache.get(count_key)
    try:
        count = int(current) + 1
    except Exception:
        count = 1
    cache.set(count_key, count, timeout=_FAILURE_WINDOW_SECONDS)
    if count < _FAILURE_THRESHOLD:
        return None

    until = datetime.now(tz=timezone.utc).timestamp() + _LOCK_SECONDS
    cache.set(lock_key, until, timeout=_LOCK_SECONDS)
    auth_security_alerts.emit_security_alert(
        reason_code="login_bruteforce_lockout",
        agency_id=agency_id,
        user_id=user_id,
        identifier=identifier,
        source_ip=source_ip,
        user_agent=user_agent,
        request_id=request_id,
        details={
            "failure_window_seconds": _FAILURE_WINDOW_SECONDS,
            "failure_threshold": _FAILURE_THRESHOLD,
            "lock_seconds": _LOCK_SECONDS,
            "count": count,
        },
        cooldown_identity=identity,
    )
    return datetime.fromtimestamp(until, tz=timezone.utc)


__all__ = ["clear_failures", "locked_until", "record_failure"]
