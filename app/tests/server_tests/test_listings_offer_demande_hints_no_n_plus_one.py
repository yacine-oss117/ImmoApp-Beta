from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_collect_offer_demande_hints_has_no_per_offer_fallback_query_loop() -> None:
    text = _read("server/services/listings.py")
    assert "missing_offer_ids =" not in text
    assert "get_demande_ids_for_offer(session, offer_id)" not in text
    assert "def _enqueue_offer_rebuild_fallbacks(" in text
