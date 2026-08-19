from __future__ import annotations

from pathlib import Path


def test_idempotency_store_signs_persisted_row_state() -> None:
    text = Path("server/api/idempotency_engine.py").read_text(encoding="utf-8")
    assert "record_id: int = 0" in text
    assert '"created_at": context.created_at' in text
    assert '"expires_at": context.expires_at' in text
    assert "Idempotency context is missing persisted row metadata." in text
    assert "sign_row = _normalize_hmac_row(" in text
    assert "record_hmac = %s," in text
    assert "WHERE id = %s" in text


def test_idempotency_replay_normalizes_datetime_fields_before_hmac_verify() -> None:
    text = Path("server/api/idempotency_engine.py").read_text(encoding="utf-8")
    assert "def _normalize_hmac_row(" in text
    assert "_compute_record_hmac(_normalize_hmac_row(row), key=hmac_key)" in text
