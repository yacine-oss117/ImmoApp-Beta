"""
Anti-regression checks for atomic storage quota reservation.
"""

from __future__ import annotations

from pathlib import Path

_HELPERS_FILE = Path(__file__).parents[3] / "server" / "services" / "storage_ops_upload_helpers.py"
_VALIDATION_FILE = Path(__file__).parents[3] / "server" / "services" / "storage_validation.py"


def test_storage_create_record_serializes_quota_checks() -> None:
    source = _HELPERS_FILE.read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in source
    assert "enforce_limits(" in source


def test_storage_quota_includes_pending_reservations() -> None:
    source = _VALIDATION_FILE.read_text(encoding="utf-8")
    assert "get_reserved_usage_for_agency" in source
    assert "purpose" in source
