from __future__ import annotations

from pathlib import Path


def test_match_artifact_storage_tuning_migration_exists() -> None:
    text = Path("server/alembic/versions/20260308_0020_match_artifact_storage_tuning.py").read_text(
        encoding="utf-8"
    )
    assert "autovacuum_vacuum_scale_factor = 0.02" in text
    assert "autovacuum_analyze_scale_factor = 0.01" in text
    assert '_apply("match_candidates")' in text
    assert '_apply("match_pairs")' in text


def test_match_partition_rollout_reapplies_storage_settings() -> None:
    text = Path("server/pg/match_partitions.py").read_text(encoding="utf-8")
    assert "_MATCH_ARTIFACT_STORAGE_OPTIONS" in text
    assert "autovacuum_vacuum_scale_factor = 0.02" in text
    assert "autovacuum_analyze_scale_factor = 0.01" in text
    assert '_apply_match_table_storage_settings(session, "match_candidates")' in text
    assert '_apply_match_table_storage_settings(session, "match_pairs")' in text
