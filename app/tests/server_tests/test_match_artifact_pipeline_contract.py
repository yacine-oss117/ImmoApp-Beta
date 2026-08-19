from __future__ import annotations

from pathlib import Path


def test_direct_pipeline_uses_delete_then_insert_without_upsert() -> None:
    text = Path("core/data/match_artifact_pipeline.py").read_text(encoding="utf-8")
    assert "DELETE FROM match_candidates WHERE demande_id = ANY(%s)" in text
    assert "DELETE FROM match_pairs WHERE demande_id = ANY(%s)" in text
    assert "INSERT INTO match_candidates" in text
    assert "INSERT INTO match_pairs" in text
    assert "ON CONFLICT" not in text
    assert "update_visibility_cache" not in text


def test_direct_pipeline_keeps_deterministic_pair_ordering() -> None:
    text = Path("core/data/match_artifact_pipeline.py").read_text(encoding="utf-8")
    assert "ORDER BY score DESC, offer_id ASC" in text
    assert "ROW_NUMBER() OVER" in text
    assert "PARTITION BY demande_id" in text
