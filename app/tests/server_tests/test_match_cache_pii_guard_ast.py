from __future__ import annotations

from pathlib import Path


def test_match_cache_runtime_sql_does_not_reference_identity_columns() -> None:
    write_sql = Path("core/data/match_cache_write.py").read_text(encoding="utf-8")
    read_sql = Path("core/data/match_cache_read.py").read_text(encoding="utf-8")
    dashboard_sql = Path("server/services/dashboard.py").read_text(encoding="utf-8")

    assert "match_counts_cache m.family_name" not in read_sql
    assert "match_counts_cache m.phone" not in read_sql
    assert "m.family_name" not in write_sql
    assert "m.phone" not in write_sql
    assert "COALESCE(m.family_name" not in dashboard_sql
    assert "COALESCE(m.phone" not in dashboard_sql
