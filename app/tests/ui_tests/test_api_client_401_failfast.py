from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import api_client
from app.services.api_client_errors import ApiError


class _FakeResponse:
    status_code = 401
    text = "Unauthorized"

    @staticmethod
    def json() -> dict[str, str]:
        return {"detail": "Unauthorized"}


def test_api_client_401_fails_fast_when_reauth_cannot_get_token(monkeypatch) -> None:
    request_count = 0

    class _FakeSession:
        def request(self, **_: object) -> _FakeResponse:
            nonlocal request_count
            request_count += 1
            return _FakeResponse()

    token_values = iter(["initial-token", None])

    monkeypatch.setattr(api_client, "get_offline_mode", lambda: False)
    monkeypatch.setattr(api_client, "build_url", lambda path, prefix_api=True: path)
    monkeypatch.setattr(api_client, "get_api_timeout", lambda: 1.0)
    monkeypatch.setattr(api_client, "circuit_check", lambda: None)
    monkeypatch.setattr(api_client, "record_api_failure", lambda: None)
    monkeypatch.setattr(api_client, "record_api_success", lambda: None)
    monkeypatch.setattr(api_client, "should_retry_status", lambda status: False)
    monkeypatch.setattr(api_client, "get_session", lambda: _FakeSession())
    monkeypatch.setattr(
        api_client,
        "get_requests",
        lambda: SimpleNamespace(RequestException=RuntimeError),
    )
    monkeypatch.setattr(
        api_client,
        "get_api_config",
        lambda: SimpleNamespace(username="admin", schema=None),
    )
    monkeypatch.setattr(api_client, "_get_token", lambda: next(token_values))

    with pytest.raises(ApiError) as exc_info:
        api_client.api_get("/api/v1/test")

    assert exc_info.value.status_code == 401
    assert request_count == 1
