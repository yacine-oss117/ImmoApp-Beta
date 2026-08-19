"""Short-lived runtime pressure overrides published by active workers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime

from django.core.cache import cache

_CACHE_KEY = "immoapp:runtime_pressure_tripwire"


@dataclass(frozen=True)
class RuntimePressureOverride:
    profile: str
    reason: str
    created_at: str
    ttl_seconds: int


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _default_ttl_seconds() -> int:
    raw = (os.environ.get("IMMOAPP_RUNTIME_PRESSURE_TRIPWIRE_TTL_SECONDS") or "").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 30
    return max(5, min(value, 300))


def _coerce_ttl_seconds(value: object) -> int:
    if isinstance(value, bool):
        ttl_value = int(value)
    elif isinstance(value, int):
        ttl_value = value
    elif isinstance(value, str):
        try:
            ttl_value = int(value)
        except ValueError:
            ttl_value = _default_ttl_seconds()
    else:
        ttl_value = _default_ttl_seconds()
    return max(1, ttl_value)


def publish_override(*, profile: str, reason: str, ttl_seconds: int | None = None) -> None:
    payload = {
        "profile": str(profile or "red").strip().lower() or "red",
        "reason": str(reason or "tripwire").strip() or "tripwire",
        "created_at": _utc_now_iso(),
        "ttl_seconds": _coerce_ttl_seconds(ttl_seconds or _default_ttl_seconds()),
    }
    try:
        cache.set(_CACHE_KEY, payload, timeout=_coerce_ttl_seconds(payload["ttl_seconds"]))
    except Exception:
        return


def current_override() -> RuntimePressureOverride | None:
    try:
        payload = cache.get(_CACHE_KEY)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return RuntimePressureOverride(
        profile=str(payload.get("profile") or "red"),
        reason=str(payload.get("reason") or "tripwire"),
        created_at=str(payload.get("created_at") or _utc_now_iso()),
        ttl_seconds=_coerce_ttl_seconds(payload.get("ttl_seconds") or _default_ttl_seconds()),
    )


def clear_override() -> None:
    try:
        cache.delete(_CACHE_KEY)
    except Exception:
        return


__all__ = [
    "RuntimePressureOverride",
    "clear_override",
    "current_override",
    "publish_override",
]
