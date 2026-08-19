"""Cursor pagination helpers."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any


def normalize_limit(
    value: int | str | None,
    *,
    default: int = 50,
    minimum: int = 1,
    maximum: int = 200,
) -> int:
    if value is None:
        return default
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def encode_cursor(payload: Mapping[str, object]) -> str:
    raw = json.dumps(dict(payload), separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    token = str(cursor or "").strip()
    if not token:
        return None
    padding = "=" * (-len(token) % 4)
    try:
        decoded = base64.urlsafe_b64decode((token + padding).encode("ascii"))
        parsed = json.loads(decoded.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Invalid cursor.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Invalid cursor.")
    return parsed


__all__ = ["decode_cursor", "encode_cursor", "normalize_limit"]
