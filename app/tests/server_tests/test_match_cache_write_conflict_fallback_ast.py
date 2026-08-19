from __future__ import annotations

from pathlib import Path


def test_match_cache_write_supports_composite_and_legacy_conflict_targets() -> None:
    text = Path("core/data/match_cache_write.py").read_text(encoding="utf-8")
    assert "ON CONFLICT (agency_id, client_id)" in text
    assert "ON CONFLICT (client_id)" in text
    assert "no unique or exclusion constraint matching the on conflict specification" in text
