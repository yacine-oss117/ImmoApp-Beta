"""WebSocket notification hub for real-time user updates."""

from __future__ import annotations

import json
import logging
import random
from typing import cast
from urllib.parse import urlencode, urlparse

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket, QNetworkRequest
from PySide6.QtWebSockets import QWebSocket, QWebSocketHandshakeOptions

from app.services.api_client import get_access_token, peek_access_token, set_session_access_token
from app.services.api_config import get_api_base_url, get_api_schema
from app.utils.qt_async import run_background_result
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

_RETRY_BASE_MS = 1000
_RETRY_MAX_MS = 30000
_RETRY_JITTER_MS = 500
_PING_INTERVAL_MS = 25000
_PONG_TIMEOUT_MS = 12000
_AUTH_CLOSE_CODES = {WS_CLOSE_UNAUTHORIZED, WS_CLOSE_FORBIDDEN}


class NotificationHub(QObject):
    """Maintain a WebSocket connection for user/agency notifications."""

    notification_received = Signal(dict)
    connection_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._socket: QWebSocket = QWebSocket()
        self._retry_timer: QTimer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._on_retry_timeout)
        self._ping_timer: QTimer = QTimer(self)
        self._ping_timer.setInterval(_PING_INTERVAL_MS)
        self._ping_timer.timeout.connect(self._send_ping)
        self._pong_timeout_timer: QTimer = QTimer(self)
        self._pong_timeout_timer.setSingleShot(True)
        self._pong_timeout_timer.timeout.connect(self._on_pong_timeout)
        self._closed: bool = False
        self._retry_attempt: int = 0
        self._reconnect_pending: bool = False
        self._token_fetch_inflight: bool = False

        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.textMessageReceived.connect(self._on_message)
        self._socket.errorOccurred.connect(self._on_error)

    def start(self) -> None:
        """Start (or restart) the notification WebSocket."""
        self._closed = False
        self._retry_attempt = 0
        self._reconnect_pending = False
        self._token_fetch_inflight = False
        self._connect()

    def stop(self) -> None:
        """Stop the notification WebSocket."""
        self._closed = True
        self._reconnect_pending = False
        self._token_fetch_inflight = False
        self._retry_timer.stop()
        self._ping_timer.stop()
        self._pong_timeout_timer.stop()
        if self._socket.state() != QAbstractSocket.SocketState.UnconnectedState:
            self._socket.close()

    def _build_url_and_token(self) -> tuple[str, str] | None:
        base = get_api_base_url()
        if not base:
            return None
        parsed = urlparse(base)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        query: dict[str, str] = {}
        schema = get_api_schema()
        if schema:
            query["schema"] = schema
        query[WS_PROTOCOL_QUERY_KEY] = WS_PROTOCOL_V2
        qs = urlencode(query)
        base_url = f"{scheme}://{parsed.netloc}/ws/notifications/"
        url = f"{base_url}?{qs}" if qs else base_url
        token = peek_access_token()
        if not token:
            return None
        return (url, token)

    def _next_retry_interval_ms(self) -> int:
        attempt = max(int(self._retry_attempt), 1)
        base: int = _RETRY_BASE_MS * (2 ** (attempt - 1))
        if base > _RETRY_MAX_MS:
            base = _RETRY_MAX_MS
        jitter: int = random.randint(0, _RETRY_JITTER_MS)
        interval: int = base + jitter
        if interval > _RETRY_MAX_MS:
            return _RETRY_MAX_MS
        return interval

    def _arm_reconnect(self, reason: str) -> None:
        if self._closed:
            return
        if self._reconnect_pending:
            return
        self._reconnect_pending = True
        self._retry_attempt += 1
        interval = self._next_retry_interval_ms()
        logger.debug("Scheduling WS reconnect in %sms (%s)", interval, reason)
        self._retry_timer.start(interval)

    def _on_retry_timeout(self) -> None:
        self._reconnect_pending = False
        self._connect()

    def _open_socket(self, url: str, token: str) -> None:
        if self._socket.state() != QAbstractSocket.SocketState.UnconnectedState:
            return
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode())
        api_base = get_api_base_url()
        if api_base:
            parsed = urlparse(api_base)
            origin_scheme = "https" if parsed.scheme == "https" else "http"
            origin = f"{origin_scheme}://{parsed.netloc}".encode()
            request.setRawHeader(b"Origin", origin)

        # Use Qt handshake options for subprotocol negotiation.
        # Raw "Sec-WebSocket-Protocol" headers are not consistently honored.
        try:
            options = QWebSocketHandshakeOptions()
            options.setSubprotocols([f"bearer.{token}"])
            self._socket.open(request, options)
        except TypeError:
            # Backward compatibility for Qt builds that don't expose the
            # handshake-options overload.
            request.setRawHeader(b"Sec-WebSocket-Protocol", f"bearer.{token}".encode())
            self._socket.open(request)

    def _resolve_token_background(self) -> None:
        if self._token_fetch_inflight:
            return
        self._token_fetch_inflight = True

        def _fetch() -> str | None:
            return get_access_token()

        def _on_success(token: str | None) -> None:
            self._token_fetch_inflight = False
            if self._closed:
                return
            if not token:
                self._arm_reconnect("token-missing")
                return
            base = get_api_base_url()
            if not base:
                self._arm_reconnect("config-missing")
                return
            parsed = urlparse(base)
            scheme = "wss" if parsed.scheme == "https" else "ws"
            query: dict[str, str] = {}
            schema = get_api_schema()
            if schema:
                query["schema"] = schema
            query[WS_PROTOCOL_QUERY_KEY] = WS_PROTOCOL_V2
            qs = urlencode(query)
            base_url = f"{scheme}://{parsed.netloc}/ws/notifications/"
            url = f"{base_url}?{qs}" if qs else base_url
            self._open_socket(url, token)

        def _on_error(exc: Exception) -> None:
            self._token_fetch_inflight = False
            if self._closed:
                return
            logger.warning("Background WS token fetch failed: %s", exc)
            self._arm_reconnect("token-error")

        run_background_result(_fetch, _on_success, _on_error)

    def _connect(self) -> None:
        if self._closed:
            return
        self._retry_timer.stop()
        ws_params = self._build_url_and_token()
        if ws_params:
            url, token = ws_params
            self._open_socket(url, token)
            return
        self._resolve_token_background()

    def _on_connected(self) -> None:
        self.connection_changed.emit(True)
        self._retry_attempt = 0
        self._reconnect_pending = False
        self._token_fetch_inflight = False
        self._retry_timer.stop()
        self._pong_timeout_timer.stop()
        self._ping_timer.start()

    def _on_disconnected(self) -> None:
        self.connection_changed.emit(False)
        self._ping_timer.stop()
        self._pong_timeout_timer.stop()
        close_code = cast(int, self._socket.closeCode().value)
        logger.debug(
            "Notification WS disconnected: close_code=%s close_reason=%s",
            close_code,
            self._socket.closeReason(),
        )
        if close_code in _AUTH_CLOSE_CODES:
            set_session_access_token(None)
        if not self._closed:
            self._arm_reconnect("disconnect")

    def _send_control(self, control: str) -> None:
        if self._socket.state() != QAbstractSocket.SocketState.ConnectedState:
            return
        payload = json.dumps({CONTROL_FIELD: control})
        self._socket.sendTextMessage(payload)

    def _send_ping(self) -> None:
        if self._socket.state() != QAbstractSocket.SocketState.ConnectedState:
            return
        self._send_control(CONTROL_PING)
        self._pong_timeout_timer.start(_PONG_TIMEOUT_MS)

    def _on_pong_timeout(self) -> None:
        if self._socket.state() == QAbstractSocket.SocketState.ConnectedState:
            self._socket.abort()

    def _on_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("Invalid notification payload: %s", message)
            return
        if isinstance(payload, dict):
            control = payload.get(CONTROL_FIELD)
            if isinstance(control, str):
                if control == CONTROL_PONG:
                    self._pong_timeout_timer.stop()
                    return
                if control in {CONTROL_PING, CONTROL_HEARTBEAT}:
                    self._send_control(CONTROL_PONG)
                    return
                if control == CONTROL_AUTH_EXPIRING:
                    set_session_access_token(None)
                    if self._socket.state() == QAbstractSocket.SocketState.ConnectedState:
                        self._socket.close()
                    return
            payload_dict: dict[str, object] = {str(k): v for k, v in payload.items()}
            self.notification_received.emit(payload_dict)

    def _on_error(self, _error: object) -> None:
        logger.debug("Notification WS error: %s", self._socket.errorString())
        if not self._closed:
            self._arm_reconnect("error")


__all__ = ["NotificationHub"]
