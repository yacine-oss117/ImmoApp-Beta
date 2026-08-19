"""Read-path guardrails for match cache: no JOIN clients."""

from pathlib import Path


def test_match_cache_read_avoids_clients_join() -> None:
    text = Path("core/data/match_cache_read.py").read_text(encoding="utf-8")
    assert "JOIN clients" not in text
