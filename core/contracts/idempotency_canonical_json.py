"""Canonical JSON + query hashing for idempotency fingerprints."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

CANONICAL_JSON_VERSION = "v1"


def _normalize_number(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            raise ValueError("non-finite decimal is not supported in canonical JSON")
        return str(value.normalize())
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError("non-finite float is not supported in canonical JSON")
        # Preserve numeric intent from parsed JSON:
        # - integral floats remain "1.0" and not coerced to integer.
        return format(value, ".15g")
    return value


def _normalize_value(value: Any) -> Any:
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return _normalize_number(value)
    if isinstance(value, Mapping):
        return {
            str(k): _normalize_value(v) for k, v in sorted(value.items(), key=lambda i: str(i[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_value(v) for v in value]
    if isinstance(value, (str, bool)) or value is None:
        return value
    raise TypeError(f"Unsupported canonical JSON type: {type(value)!r}")


def canonical_json_dumps(payload: Any) -> str:
    normalized = _normalize_value(payload)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_body_hash(payload: Any) -> str:
    dumped = canonical_json_dumps(payload)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def canonical_query_hash(query_items: Mapping[str, Any]) -> str:
    normalized: dict[str, list[str]] = {}
    for key in sorted(query_items):
        raw = query_items[key]
        if isinstance(raw, (list, tuple)):
            values = [str(v) for v in raw]
        else:
            values = [str(raw)]
        normalized[str(key)] = sorted(values)
    dumped = canonical_json_dumps(normalized)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


__all__ = [
    "CANONICAL_JSON_VERSION",
    "canonical_body_hash",
    "canonical_json_dumps",
    "canonical_query_hash",
]
