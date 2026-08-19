"""WebSocket protocol helpers and constants."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import parse_qs

from core.contracts.ws_protocol import (
    CONTROL_AUTH_EXPIRING,
    CONTROL_FIELD,
    CONTROL_HEARTBEAT,
    CONTROL_PING,
    CONTROL_PONG,
    WS_CLOSE_BAD_REQUEST,
    WS_CLOSE_FORBIDDEN,
    WS_CLOSE_UNAUTHORIZED,
    WS_PROTOCOL_QUERY_KEY,
    WS_PROTOCOL_V2,
)

HEARTBEAT_INTERVAL_SECONDS = int(os.environ.get("WS_HEARTBEAT_INTERVAL_SECONDS", "30"))
AUTH_EXPIRING_LEAD_SECONDS = int(os.environ.get("WS_AUTH_EXPIRING_LEAD_SECONDS", "60"))
AUTH_EXPIRY_GRACE_SECONDS = int(os.environ.get("WS_AUTH_EXPIRY_GRACE_SECONDS", "5"))


def _query_dict(scope: dict[str, Any]) -> dict[str, list[str]]:
    raw_query = scope.get("query_string", b"")
    if isinstance(raw_query, bytes):
        decoded = raw_query.decode("utf-8", errors="ignore")
    else:
        decoded = str(raw_query or "")
    return parse_qs(decoded, keep_blank_values=True)


def scope_supports_v2(scope: dict[str, Any]) -> bool:
    query = _query_dict(scope)
    values = query.get(WS_PROTOCOL_QUERY_KEY, [])
    return any(value == WS_PROTOCOL_V2 for value in values)


def control_payload(kind: str, **payload: object) -> dict[str, object]:
    message: dict[str, object] = {CONTROL_FIELD: kind}
    message.update(payload)
    return message


__all__ = [
    "AUTH_EXPIRING_LEAD_SECONDS",
    "AUTH_EXPIRY_GRACE_SECONDS",
    "CONTROL_AUTH_EXPIRING",
    "CONTROL_FIELD",
    "CONTROL_HEARTBEAT",
    "CONTROL_PING",
    "CONTROL_PONG",
    "HEARTBEAT_INTERVAL_SECONDS",
    "WS_CLOSE_BAD_REQUEST",
    "WS_CLOSE_FORBIDDEN",
    "WS_CLOSE_UNAUTHORIZED",
    "WS_PROTOCOL_QUERY_KEY",
    "WS_PROTOCOL_V2",
    "control_payload",
    "scope_supports_v2",
]
