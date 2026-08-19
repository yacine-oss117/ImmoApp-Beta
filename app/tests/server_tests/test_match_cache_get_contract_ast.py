from __future__ import annotations

from pathlib import Path


def test_match_cache_get_returns_counts_and_count_meta() -> None:
    text = Path("server/api/views_cache_status.py").read_text(encoding="utf-8")
    assert "get_cached_counts_batch_with_meta" in text
    assert '"counts": counts' in text
    assert '"count_meta": count_meta' in text
