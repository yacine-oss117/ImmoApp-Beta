"""Schema guardrails for match_counts_cache denormalized visibility."""

from pathlib import Path


def test_match_cache_schema_has_visibility_columns_and_trigger() -> None:
    path = Path("server/alembic/versions/20260206_0008_match_cache_visibility_rls.py")
    text = path.read_text(encoding="utf-8")
    assert "match_counts_cache" in text
    assert "visibility TEXT" in text
    assert "owner_user_id BIGINT" in text
    assert "sync_match_cache_from_client" in text
    assert "trg_sync_match_cache_client" in text


def test_match_cache_schema_drop_pii_and_composite_key() -> None:
    path = Path("server/alembic/versions/20260221_0016_match_cache_drop_pii.py")
    text = path.read_text(encoding="utf-8")
    assert "DROP COLUMN IF EXISTS family_name" in text
    assert "DROP COLUMN IF EXISTS phone" in text
    assert "PRIMARY KEY (agency_id, client_id)" in text
    assert "task_scan_checkpoints" in text
