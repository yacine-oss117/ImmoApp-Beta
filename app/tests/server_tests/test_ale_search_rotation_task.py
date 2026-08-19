from __future__ import annotations

import pytest

from server.api import tasks_ale


def test_rotate_ale_search_keys_task_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tasks_ale,
        "start_ale_search_rotation",
        lambda *, to_version: {"status": "started", "current": to_version, "previous": "v1"},
    )

    result = tasks_ale.rotate_ale_search_keys_task(mode="start", to_version="v2")

    assert result["mode"] == "start"
    assert result["status"] == "started"
    assert result["current"] == "v2"


def test_rotate_ale_search_keys_task_finalize(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tasks_ale,
        "finalize_ale_search_rotation",
        lambda: {"status": "finalized", "current": "v2", "previous": ""},
    )

    result = tasks_ale.rotate_ale_search_keys_task(mode="finalize")

    assert result["mode"] == "finalize"
    assert result["status"] == "finalized"


def test_rotate_ale_search_keys_task_requires_valid_mode() -> None:
    with pytest.raises(ValueError, match="mode must be 'start' or 'finalize'"):
        tasks_ale.rotate_ale_search_keys_task(mode="invalid")


def test_rotate_ale_search_keys_task_requires_to_version_for_start() -> None:
    with pytest.raises(ValueError, match="to_version is required"):
        tasks_ale.rotate_ale_search_keys_task(mode="start")
