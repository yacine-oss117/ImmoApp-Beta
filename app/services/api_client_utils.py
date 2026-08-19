"""Shared helpers for the API client."""

from __future__ import annotations

import base64
import json
import os
import re
import time

from app.services.api_config import get_api_base_url

JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]

_API_PREFIX = "/api/v1"
_DEFAULT_TIMEOUT = 8
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _load_timeout() -> float:
    raw = os.environ.get("IMMOAPP_API_TIMEOUT")
    if not raw:
        return float(_DEFAULT_TIMEOUT)
    try:
        value = float(raw)
    except ValueError:
        return float(_DEFAULT_TIMEOUT)
    return max(3.0, min(value, 30.0))


_API_TIMEOUT = _load_timeout()


def get_api_timeout() -> float:
    return _API_TIMEOUT


def format_error_payload(payload: object, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("detail", "error", "message", "error_message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        parts: list[str] = []
        for key, value in payload.items():
            if value is None:
                continue
            if isinstance(value, list):
                msg = ", ".join(str(item) for item in value if item is not None)
            elif isinstance(value, dict):
                msg = ", ".join(
                    f"{nested_key}: {nested_val}" for nested_key, nested_val in value.items()
                )
            else:
                msg = str(value)
            if msg:
                parts.append(f"{key}: {msg}")
        if parts:
            return "; ".join(parts)
    elif isinstance(payload, list):
        return "; ".join(str(item) for item in payload if item is not None)
    elif isinstance(payload, str) and payload.strip():
        return payload
    return fallback


def compact_error_text(text: str, *, max_len: int = 280) -> str:
    """Collapse verbose/raw server payloads (including HTML debug pages) to a short message."""
    raw = (text or "").strip()
    if not raw:
        return ""

    lowered = raw.lower()
    if "<html" in lowered or "<!doctype html" in lowered:
        title_match = re.search(r"<title>(.*?)</title>", raw, flags=re.IGNORECASE | re.DOTALL)
        if title_match:
            raw = title_match.group(1)
        else:
            raw = _HTML_TAG_RE.sub(" ", raw)

    raw = re.sub(r"\s+", " ", raw).strip()
    if len(raw) <= max_len:
        return raw
    return f"{raw[:max_len].rstrip()}..."


def build_url(path: str, *, prefix_api: bool = True) -> str:
    """Build a full URL from a path, optionally prepending the API prefix."""
    base = get_api_base_url()
    if not base:
        raise RuntimeError("API base URL is not configured")
    route = path if path.startswith("/") else f"/{path}"
    if prefix_api:
        route = f"{_API_PREFIX}{route}"
        if not route.endswith("/"):
            route = f"{route}/"
    return f"{base}{route}"


def decode_jwt_claims(token: str) -> dict[str, object] | None:
    """Decode JWT claims without verification (offline gating only)."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1]
        padded = payload + "=" * (-len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def token_is_valid(token: str, *, leeway_seconds: int = 30) -> bool:
    claims = decode_jwt_claims(token)
    if not claims:
        return False
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return (exp - leeway_seconds) > time.time()


def as_dict(payload: object) -> dict[str, object]:
    """Coerce a JSON payload to a dictionary."""
    if isinstance(payload, dict):
        return {str(key): value for key, value in payload.items()}
    return {}


def as_dict_list(payload: object) -> list[dict[str, object]]:
    """Coerce a JSON payload to a list of dictionaries."""
    if isinstance(payload, list):
        return [
            {str(key): value for key, value in item.items()}
            for item in payload
            if isinstance(item, dict)
        ]
    return []


__all__ = [
    "JsonValue",
    "JsonPrimitive",
    "get_api_timeout",
    "format_error_payload",
    "compact_error_text",
    "build_url",
    "decode_jwt_claims",
    "token_is_valid",
    "as_dict",
    "as_dict_list",
]
