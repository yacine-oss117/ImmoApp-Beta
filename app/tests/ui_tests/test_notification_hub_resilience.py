from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from app.widgets import notification_hub as module  # noqa: E402
from core.contracts.ws_protocol import CONTROL_AUTH_EXPIRING, CONTROL_PING

pytestmark = pytest.mark.ui


def test_notification_hub_build_url_adds_protocol_v2(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    monkeypatch.setattr(module, "get_api_base_url", lambda: "http://localhost:8000")
    monkeypatch.setattr(module, "peek_access_token", lambda: "token")
    monkeypatch.setattr(module, "get_api_schema", lambda: "public")

    hub = module.NotificationHub()
    params = hub._build_url_and_token()
    assert params is not None
    url, token = params
    assert token == "token"
    assert "ws_v=2" in url
    assert "schema=public" in url


def test_notification_hub_backoff_is_capped(qapp) -> None:
    hub = module.NotificationHub()
    intervals: list[int] = []
    for attempt in range(1, 11):
        hub._retry_attempt = attempt
        intervals.append(hub._next_retry_interval_ms())
    assert all(interval <= module._RETRY_MAX_MS for interval in intervals)
    assert intervals[-1] <= module._RETRY_MAX_MS


def test_notification_hub_handles_control_ping(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    hub = module.NotificationHub()
    sent: list[str] = []
    monkeypatch.setattr(hub, "_send_control", lambda control: sent.append(control))

    hub._on_message(json.dumps({"control": CONTROL_PING}))
    assert sent == ["pong"]


def test_notification_hub_handles_auth_expiring(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    hub = module.NotificationHub()
    cleared: list[object] = []
    monkeypatch.setattr(module, "set_session_access_token", lambda token: cleared.append(token))

    hub._on_message(json.dumps({"control": CONTROL_AUTH_EXPIRING, "expires_in": 5}))
    assert cleared == [None]


def test_notification_hub_connect_fetches_token_in_background(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    hub = module.NotificationHub()
    calls = {"token": 0, "worker": 0}

    monkeypatch.setattr(module, "get_api_base_url", lambda: "http://localhost:8000")
    monkeypatch.setattr(module, "peek_access_token", lambda: None)
    monkeypatch.setattr(module, "get_api_schema", lambda: "public")
    monkeypatch.setattr(
        module, "get_access_token", lambda: calls.__setitem__("token", calls["token"] + 1)
    )

    def _fake_run_background_result(func, on_success, on_error=None, *args, **kwargs):
        _ = on_success, on_error, args, kwargs
        calls["worker"] += 1
        # Ensure get_access_token is deferred to background worker; do not execute func here.
        _ = func

    monkeypatch.setattr(module, "run_background_result", _fake_run_background_result)

    hub._connect()

    assert calls["worker"] == 1
    assert calls["token"] == 0
    assert hub._token_fetch_inflight is True


def test_notification_hub_arm_reconnect_increments_once_per_cycle(qapp) -> None:
    hub = module.NotificationHub()

    hub._arm_reconnect("error")
    assert hub._retry_attempt == 1
    assert hub._reconnect_pending is True

    hub._arm_reconnect("disconnect")
    assert hub._retry_attempt == 1


def test_notification_hub_open_socket_uses_handshake_options(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    class _FakeOptions:
        def __init__(self) -> None:
            self.subs: list[str] = []

        def setSubprotocols(self, subs: list[str]) -> None:
            self.subs = list(subs)

    class _FakeSocket:
        def __init__(self) -> None:
            self.last_args: tuple[object, ...] = ()

        def state(self):
            return module.QAbstractSocket.SocketState.UnconnectedState

        def open(self, *args):
            self.last_args = args

    fake_socket = _FakeSocket()
    hub = module.NotificationHub()
    hub._socket = fake_socket  # noqa: SLF001 - test seam

    monkeypatch.setattr(module, "QWebSocketHandshakeOptions", _FakeOptions)
    monkeypatch.setattr(module, "get_api_base_url", lambda: "http://127.0.0.1:8000")

    hub._open_socket("ws://127.0.0.1:8000/ws/notifications/?ws_v=2", "token-123")

    assert len(fake_socket.last_args) == 2
    request, options = fake_socket.last_args
    assert bytes(request.rawHeader("Authorization")) == b"Bearer token-123"
    assert bytes(request.rawHeader("Origin")) == b"http://127.0.0.1:8000"
    assert options.subs == ["bearer.token-123"]


def test_notification_hub_open_socket_falls_back_when_options_overload_missing(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    class _FakeOptions:
        def setSubprotocols(self, _subs: list[str]) -> None:
            return

    class _FakeSocket:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        def state(self):
            return module.QAbstractSocket.SocketState.UnconnectedState

        def open(self, *args):
            self.calls.append(args)
            if len(args) == 2:
                raise TypeError("Qt overload not available")

    fake_socket = _FakeSocket()
    hub = module.NotificationHub()
    hub._socket = fake_socket  # noqa: SLF001 - test seam

    monkeypatch.setattr(module, "QWebSocketHandshakeOptions", _FakeOptions)
    monkeypatch.setattr(module, "get_api_base_url", lambda: "http://127.0.0.1:8000")

    hub._open_socket("ws://127.0.0.1:8000/ws/notifications/?ws_v=2", "token-xyz")

    assert len(fake_socket.calls) == 2
    assert len(fake_socket.calls[0]) == 2
    assert len(fake_socket.calls[1]) == 1
    request = fake_socket.calls[1][0]
    assert bytes(request.rawHeader("Sec-WebSocket-Protocol")) == b"bearer.token-xyz"
