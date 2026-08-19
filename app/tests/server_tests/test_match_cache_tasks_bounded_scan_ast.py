from __future__ import annotations

from pathlib import Path


def test_match_cache_tasks_use_bounded_keyset_scans() -> None:
    text = Path("server/api/tasks_match_cache.py").read_text(encoding="utf-8")
    assert "iter_active_client_batches" in text
    assert "iter_active_demande_batches" in text
    assert "MATCH_CACHE_MAX_ROWS_PER_RUN" in text
    assert "task_scan_checkpoint" in text
    assert (
        "SELECT id FROM clients WHERE status = 'active' AND deleted_at IS NULL AND agency_id = %s"
        not in text
    )
    assert "SELECT id FROM demandes WHERE deleted_at IS NULL AND agency_id = %s" not in text
