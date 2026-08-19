from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_cache_status_uses_count_helpers_not_full_id_lists() -> None:
    text = _read("server/api/views_cache_status.py")
    assert "match_cache.get_dirty_client_count()" in text
    assert "match_cache.get_missing_client_count()" in text
    assert "get_dirty_client_ids()" not in text
    assert "get_missing_client_ids()" not in text


def test_cache_dirty_missing_endpoints_expose_cursor_metadata() -> None:
    text = _read("server/api/views_cache_status.py")
    assert '"next_cursor": next_cursor' in text
    assert '"has_more": has_more' in text
    assert "get_dirty_client_ids_page(" in text
    assert "get_missing_client_ids_page(" in text
