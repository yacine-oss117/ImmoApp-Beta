from pathlib import Path


def test_match_rebuild_pipeline_is_sql_only() -> None:
    text = Path("server/api/match_pairs_compute.py").read_text(encoding="utf-8")
    assert "compute_match_artifacts_for_demandes" in text
    assert "rebuild_match_artifacts_for_demandes" in text
    assert "fetchmany(" not in text
    assert "heapq" not in text
