from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import api_client_auth as module

pytestmark = pytest.mark.ui


class _FakeResponse:
    def __init__(
        self, status_code: int, text: str = "", *, payload: dict[str, object] | None = None
    ) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload if payload is not None else {}

    def json(self) -> dict[str, object]:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_refresh_token_401_logs_info_not_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMOAPP_API_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setattr(module, "_get_refresh_token", lambda _username: "refresh-token")
    monkeypatch.setattr(
        module, "get_requests", lambda: SimpleNamespace(RequestException=RuntimeError)
    )
    monkeypatch.setattr(
        module,
        "get_session",
        lambda: SimpleNamespace(post=lambda *args, **kwargs: _FakeResponse(401, "invalid refresh")),
    )
    logs: dict[str, int] = {"info": 0, "warning": 0}
    monkeypatch.setattr(
        module.logger, "info", lambda *a, **k: logs.__setitem__("info", logs["info"] + 1)
    )
    monkeypatch.setattr(
        module.logger,
        "warning",
        lambda *a, **k: logs.__setitem__("warning", logs["warning"] + 1),
    )

    token = module._refresh_access_token("owner@example.com")

    assert token is None
    assert logs["info"] == 1
    assert logs["warning"] == 0


def test_refresh_token_500_logs_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_get_refresh_token", lambda _username: "refresh-token")
    monkeypatch.setattr(
        module, "get_requests", lambda: SimpleNamespace(RequestException=RuntimeError)
    )
    monkeypatch.setattr(
        module,
        "get_session",
        lambda: SimpleNamespace(post=lambda *args, **kwargs: _FakeResponse(500, "server error")),
    )
    logs: dict[str, int] = {"warning": 0}
    monkeypatch.setattr(
        module.logger,
        "warning",
        lambda *a, **k: logs.__setitem__("warning", logs["warning"] + 1),
    )

    token = module._refresh_access_token("owner@example.com")

    assert token is None
    assert logs["warning"] == 1


def test_refresh_token_non_json_payload_logs_warning_and_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "_get_refresh_token", lambda _username: "refresh-token")
    monkeypatch.setattr(
        module, "get_requests", lambda: SimpleNamespace(RequestException=RuntimeError)
    )
    monkeypatch.setattr(
        module,
        "get_session",
        lambda: SimpleNamespace(
            post=lambda *args, **kwargs: _FakeResponse(
                200, "not-json", payload=ValueError("invalid json")
            )
        ),
    )
    logs: dict[str, int] = {"warning": 0}
    monkeypatch.setattr(
        module.logger,
        "warning",
        lambda *a, **k: logs.__setitem__("warning", logs["warning"] + 1),
    )

    token = module._refresh_access_token("owner@example.com")

    assert token is None
    assert logs["warning"] == 1


def test_refresh_token_local_https_connection_refused_logs_info_not_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RefreshRequestError(RuntimeError):
        pass

    monkeypatch.setenv("IMMOAPP_API_BASE_URL", "https://localhost")
    monkeypatch.setattr(module, "_get_refresh_token", lambda _username: "refresh-token")
    monkeypatch.setattr(
        module,
        "get_requests",
        lambda: SimpleNamespace(RequestException=_RefreshRequestError),
    )
    monkeypatch.setattr(
        module,
        "get_session",
        lambda: SimpleNamespace(
            post=lambda *args, **kwargs: (_ for _ in ()).throw(
                _RefreshRequestError(
                    "HTTPSConnectionPool(host='localhost', port=443): "
                    "Max retries exceeded with url: /api/auth/token/refresh/ "
                    "(Caused by NewConnectionError(\"HTTPSConnection(host='localhost', port=443): "
                    "Failed to establish a new connection: [WinError 10061] "
                    'No connection could be made because the target machine actively refused it"))'
                )
            )
        ),
    )
    monkeypatch.setattr(
        module,
        "get_api_config",
        lambda: SimpleNamespace(base_url="https://localhost", remember_session=True),
    )
    logs: dict[str, int] = {"info": 0, "warning": 0}
    monkeypatch.setattr(
        module.logger, "info", lambda *a, **k: logs.__setitem__("info", logs["info"] + 1)
    )
    monkeypatch.setattr(
        module.logger,
        "warning",
        lambda *a, **k: logs.__setitem__("warning", logs["warning"] + 1),
    )

    token = module._refresh_access_token("owner@example.com")

    assert token is None
    assert logs["info"] == 1
    assert logs["warning"] == 0


def test_login_with_creds_non_json_payload_raises_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMMOAPP_API_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setattr(
        module, "get_requests", lambda: SimpleNamespace(RequestException=RuntimeError)
    )
    monkeypatch.setattr(
        module,
        "get_session",
        lambda: SimpleNamespace(
            post=lambda *args, **kwargs: _FakeResponse(
                200, "not-json", payload=ValueError("invalid json")
            )
        ),
    )

    with pytest.raises(module.ApiError) as exc:
        module._login_with_creds("owner@example.com", "StrongPassword!123")

    assert int(exc.value.status_code) == 502
