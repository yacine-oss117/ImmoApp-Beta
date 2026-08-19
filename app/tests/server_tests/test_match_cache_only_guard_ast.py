from pathlib import Path


def test_match_details_cache_only_guard() -> None:
    text = Path("core/matcher/match_details.py").read_text(encoding="utf-8")
    assert "build_demande_detail_matches_query" not in text
    assert "cache-only read path in effect" in text
    assert "fetch_pairs_with_offers" in text
    assert "count_pairs_for_demande" in text


def test_match_service_enqueues_missing_pairs() -> None:
    text = Path("server/services/matches.py").read_text(encoding="utf-8")
    assert "_MATCH_CACHE_ONLY" in text
    assert "_ensure_pairs_enqueued" in text
    assert "enqueue_rebuild_demande_pairs" in text
