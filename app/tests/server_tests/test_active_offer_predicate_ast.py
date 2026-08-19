"""
Anti-regression checks for offer active predicate.
"""

from __future__ import annotations

from pathlib import Path

_SQL_FILE = Path(__file__).parents[3] / "core" / "matcher" / "match_query_sql.py"


def test_active_offer_requires_available_status() -> None:
    source = _SQL_FILE.read_text(encoding="utf-8")
    assert "ACTIVE_OFFER" in source
    assert "o.status = 'available'" in source
    assert "o.deleted_at IS NULL" in source
