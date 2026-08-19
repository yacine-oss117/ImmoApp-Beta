"""WebSocket helpers for task completion push notifications."""

from __future__ import annotations

import json
import logging
from typing import cast
from urllib.parse import urlencode, urlparse

from app.services.api_client import peek_access_token, set_session_access_token
from app.services.api_config import get_api_base_url, get_api_schema
from core.contracts.ws_protocol import (
    CONTROL_AUTH_EXPIRING,
    CONTROL_FIELD,
    CONTROL_HEARTBEAT,
    CONTROL_PING,
    CONTROL_PONG,
    WS_CLOSE_FORBIDDEN,
    WS_CLOSE_UNAUTHORIZED,
    WS_PROTOCOL_QUERY_KEY,
    WS_PROTOCOL_V2,
)

logger = logging.getLogger(__name__)
_AUTH_CLOSE_CODES = {WS_CLOSE_UNAUTHORIZED, WS_CLOSE_FORBIDDEN}


def _build_ws_url_and_token(task_id: str) -> tuple[str, str] | None:
    base = get_api_base_url()
    if not base:
        return None
    token = peek_access_token()
    if not token:
        return None
    parsed = urlparse(base)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    query: dict[str, str] = {}
    schema = get_api_schema()
    if schema:
        query["schema"] = schema
    query[WS_PROTOCOL_QUERY_KEY] = WS_PROTOCOL_V2
    qs = urlencode(query)
    base_url = f"{scheme}://{parsed.netloc}/ws/tasks/{task_id}/"
    url = f"{base_url}?{qs}" if qs else base_url
    return (url, token)


def wait_for_task_notification(
    task_id: str, *, timeout_sec: float = 30.0
) -> dict[str, object] | None:
    """Wait for a task completion push; returns payload or None on timeout/failure."""
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtNetwork import QAbstractSocket, QNetworkRequest
        from PySide6.QtWebSockets import QWebSocket
        from PySide6.QtWidgets import QApplication
    except Exception:
        return None

    if QApplication.instance() is None:
        return None

    def _wait_once(*, retry_after_auth: bool) -> tuple[dict[str, object] | None, bool]:
        ws_params = _build_ws_url_and_token(task_id)
        if not ws_params:
            return None, False
        url, token = ws_params

        loop = QEventLoop()
        socket = QWebSocket()
        result: dict[str, object] | None = None
        should_retry_auth = False

        def _finish(payload: dict[str, object] | None) -> None:
            nonlocal result
            result = payload
            if socket.state() != QAbstractSocket.SocketState.UnconnectedState:
                socket.close()
            if loop.isRunning():
                loop.quit()

        def _on_message(message: str) -> None:
            nonlocal should_retry_auth
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                return
            control = payload.get(CONTROL_FIELD)
            if isinstance(control, str):
                if control == CONTROL_PING:
                    socket.sendTextMessage(json.dumps({CONTROL_FIELD: CONTROL_PONG}))
                    return
                if control in {CONTROL_PONG, CONTROL_HEARTBEAT}:
                    return
                if control == CONTROL_AUTH_EXPIRING:
                    should_retry_auth = retry_after_auth
                    set_session_access_token(None)
                    _finish(None)
                    return
            if payload.get("task_id") == task_id:
                _finish(cast(dict[str, object], payload))

        def _on_error(_error: object) -> None:
            _finish(None)

        def _on_timeout() -> None:
            _finish(None)

        def _on_disconnected() -> None:
            nonlocal should_retry_auth
            if cast(int, socket.closeCode().value) in _AUTH_CLOSE_CODES:
                should_retry_auth = retry_after_auth
                set_session_access_token(None)
            _finish(None)

        socket.textMessageReceived.connect(_on_message)
        socket.errorOccurred.connect(_on_error)
        socket.disconnected.connect(_on_disconnected)

        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(_on_timeout)
        timer.start(int(timeout_sec * 1000))

        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode())
        request.setRawHeader(b"Sec-WebSocket-Protocol", f"bearer.{token}".encode())
        socket.open(request)
        loop.exec()
        timer.stop()
        return result, should_retry_auth

    first_result, should_retry = _wait_once(retry_after_auth=True)
    if first_result is not None:
        return first_result
    if not should_retry:
        return None
    second_result, _ = _wait_once(retry_after_auth=False)
    return second_result


__all__ = ["wait_for_task_notification"]
