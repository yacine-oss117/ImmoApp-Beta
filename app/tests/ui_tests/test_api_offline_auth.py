from __future__ import annotations

import base64
import json
import time

import pytest

from app.services import api_client, offline_state


def _b64(data: dict[str, object]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _make_token(exp: int) -> str:
    header = _b64({"alg": "none", "typ": "JWT"})
    payload = _b64({"exp": exp})
    return f"{header}.{payload}."


def test_offline_auth_uses_cached_token(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    offline_state.set_offline_mode(True)

    token = _make_token(int(time.time()) + 3600)
    api_client.set_session_access_token(token)

    monkeypatch.setattr(
        api_client, "_refresh_access_token", lambda *_: (_ for _ in ()).throw(AssertionError())
    )
    monkeypatch.setattr(
        api_client, "_login_with_creds", lambda *_: (_ for _ in ()).throw(AssertionError())
    )

    assert api_client.get_access_token() == token


def test_offline_auth_rejects_expired_token(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    offline_state.set_offline_mode(True)

    token = _make_token(int(time.time()) - 10)
    api_client.set_session_access_token(token)

    assert api_client.get_access_token() is None


def test_offline_request_blocked(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    offline_state.set_offline_mode(True)

    with pytest.raises(RuntimeError):
        api_client.api_get("/health")
