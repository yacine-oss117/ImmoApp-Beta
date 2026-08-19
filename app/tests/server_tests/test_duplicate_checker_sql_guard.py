from __future__ import annotations

from pathlib import Path


def test_duplicate_checker_uses_deleted_at_not_is_deleted() -> None:
    src = Path("server/services/duplicate_checker.py").read_text(encoding="utf-8")
    assert "deleted_at IS NULL" in src
    assert "is_deleted = FALSE" not in src


def test_duplicate_checker_has_no_hard_row_cap_limit() -> None:
    src = Path("server/services/duplicate_checker.py").read_text(encoding="utf-8")
    assert "LIMIT 1000" not in src


def test_duplicate_checker_phone_lookup_is_storage_aware_and_not_a_mixed_probe_bag() -> None:
    src = Path("server/services/duplicate_checker.py").read_text(encoding="utf-8")

    assert "lookup_tokens" not in src
    assert "def _masked_phone_probes" in src
    assert "def _plaintext_phone_probes" in src
    assert "_fetch_rows(sorted(masked_lookup_map.keys()))" in src
    assert "_fetch_rows(sorted(plaintext_lookup_map.keys()))" in src
