from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.utils import task_push as module  # noqa: E402

pytestmark = pytest.mark.ui


def test_task_push_build_url_adds_protocol_v2(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    monkeypatch.setattr(module, "get_api_base_url", lambda: "http://localhost:8000")
    monkeypatch.setattr(module, "peek_access_token", lambda: "token")
    monkeypatch.setattr(module, "get_api_schema", lambda: "public")

    params = module._build_ws_url_and_token("task-123")
    assert params is not None
    url, token = params
    assert token == "token"
    assert "/ws/tasks/task-123/" in url
    assert "ws_v=2" in url
    assert "schema=public" in url


def test_task_push_returns_none_without_token(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    monkeypatch.setattr(module, "get_api_base_url", lambda: "http://localhost:8000")
    monkeypatch.setattr(module, "peek_access_token", lambda: None)
    monkeypatch.setattr(module, "get_api_schema", lambda: "public")

    assert module._build_ws_url_and_token("task-123") is None
