from __future__ import annotations

from pathlib import Path


def test_idempotency_engine_uses_postgres_records() -> None:
    text = Path("server/api/idempotency_engine.py").read_text(encoding="utf-8")
    assert "api_idempotency_records" in text
    assert "_try_insert_in_progress_record" in text
    assert "ON CONFLICT DO NOTHING" in text
    assert "RETURNING id" in text
    assert "_select_locked_record" in text
    assert "FOR UPDATE" in text
    assert "row = _select_locked_record(session, scope=scope)" in text
    assert "inserted = _try_insert_in_progress_record(" in text
    assert "ERR_KEY_REUSE_MISMATCH" in text
    assert "ERR_IN_PROGRESS" in text
    assert "ERR_TAMPERED" in text
    assert "Idempotency-Key" in text
    assert "django.core.cache" not in text
    assert "_wait_for_completion" in text
    assert "status.HTTP_401_UNAUTHORIZED" in text
    assert "status.HTTP_403_FORBIDDEN" in text
    assert "sanitize_replay_payload" in text
    assert "fetch_secret_data" in text
    assert "signature_key_id" in text
    assert "_invalidate_hmac_keyring_cache" in text
    assert (
        "Internal process-local cache reset for tests and same-process refresh paths only." in text
    )
    assert "same-process reload before declaring the persisted record unverifiable" in text
    public_exports = text.split("__all__ = [", 1)[1]
    assert "_invalidate_hmac_keyring_cache" not in public_exports


def test_idempotency_migration_exists() -> None:
    text = Path("server/alembic/versions/20260221_0017_api_idempotency_records.py").read_text(
        encoding="utf-8"
    )
    assert "CREATE TABLE IF NOT EXISTS api_idempotency_records" in text
    assert "uq_api_idempotency_scope" in text
