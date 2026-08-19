from __future__ import annotations

import pytest

from app.services import match_cache_sync


def test_store_client_match_count_returns_false_on_total_cache_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _store_fail(_client_id: int, _count: int) -> None:
        raise RuntimeError("store failed")

    def _dirty_fail(_client_id: int) -> None:
        raise RuntimeError("dirty mark failed")

    monkeypatch.setattr(match_cache_sync, "store_count", _store_fail)
    monkeypatch.setattr(match_cache_sync, "mark_client_dirty", _dirty_fail)

    assert match_cache_sync.store_client_match_count(123, 7, context="test") is False


def test_store_client_match_count_returns_true_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []

    def _store_ok(client_id: int, count: int) -> None:
        calls.append((client_id, count))

    monkeypatch.setattr(match_cache_sync, "store_count", _store_ok)
    monkeypatch.setattr(match_cache_sync, "mark_client_dirty", lambda _client_id: None)

    assert match_cache_sync.store_client_match_count(321, 12) is True
    assert calls == [(321, 12)]
