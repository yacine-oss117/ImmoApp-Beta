"""Shared WebSocket protocol constants for server and desktop runtimes."""

from __future__ import annotations

WS_PROTOCOL_QUERY_KEY = "ws_v"
WS_PROTOCOL_V2 = "2"

CONTROL_FIELD = "control"
CONTROL_PING = "ping"
CONTROL_PONG = "pong"
CONTROL_HEARTBEAT = "heartbeat"
CONTROL_AUTH_EXPIRING = "auth_expiring"

WS_CLOSE_BAD_REQUEST = 4400
WS_CLOSE_UNAUTHORIZED = 4401
WS_CLOSE_FORBIDDEN = 4403

__all__ = [
    "CONTROL_AUTH_EXPIRING",
    "CONTROL_FIELD",
    "CONTROL_HEARTBEAT",
    "CONTROL_PING",
    "CONTROL_PONG",
    "WS_CLOSE_BAD_REQUEST",
    "WS_CLOSE_FORBIDDEN",
    "WS_CLOSE_UNAUTHORIZED",
    "WS_PROTOCOL_QUERY_KEY",
    "WS_PROTOCOL_V2",
]
