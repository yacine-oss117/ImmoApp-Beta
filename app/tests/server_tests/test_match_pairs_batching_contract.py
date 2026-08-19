from __future__ import annotations

from pathlib import Path


def test_match_pairs_tasks_use_batch_compute_path() -> None:
    text = Path("server/api/tasks_match_pairs.py").read_text(encoding="utf-8")
    assert "compute_match_pairs_for_demandes" in text
    assert "_demande_batches(" in text
    assert "IMMOAPP_MATCH_PAIRS_DEMANDE_BATCH_SIZE" in text


def test_match_pairs_data_exposes_direct_multi_demande_sql_path() -> None:
    text = Path("core/data/match_artifact_pipeline.py").read_text(encoding="utf-8")
    assert "def rebuild_match_artifacts_for_demandes" in text
    assert "PARTITION BY demande_id" in text
    assert "DELETE FROM match_candidates WHERE demande_id = ANY(%s)" in text
    assert "DELETE FROM match_pairs WHERE demande_id = ANY(%s)" in text
