"""Time utilities for consistent timestamp handling (client-side)."""

from __future__ import annotations

from datetime import date, datetime, timezone


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def normalize_timestamp(value: object) -> str | None:
    """Normalize a timestamp-like value to an ISO string or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).isoformat()
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None
