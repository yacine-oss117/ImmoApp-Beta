from __future__ import annotations

from pathlib import Path


def test_match_cache_dirty_writes_apply_timeouts_and_chunking() -> None:
    text = Path("core/data/match_cache_write.py").read_text(encoding="utf-8")
    assert "CACHE_DIRTY_MARK_CHUNK_SIZE" in text
    assert "def mark_client_dirty" in text and "_set_lock_timeout(session)" in text
    assert "def mark_clients_in_wilaya_dirty" in text and "LIMIT %s" in text
    assert "def mark_all_dirty" in text and "WHERE is_dirty = 0" in text


def test_match_cache_service_dirty_paths_use_retry_wrapper() -> None:
    text = Path("server/services/match_cache.py").read_text(encoding="utf-8")
    assert "def mark_all_dirty" in text and "run_with_retry(" in text
    assert "def mark_client_dirty" in text and "run_with_retry(" in text
    assert "def mark_clients_in_wilaya_dirty" in text and "run_with_retry(" in text
