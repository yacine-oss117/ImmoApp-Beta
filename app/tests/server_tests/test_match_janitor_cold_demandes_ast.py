"""Ensure janitor covers cold demandes."""

from pathlib import Path


def test_janitor_handles_cold_demandes() -> None:
    text = Path("server/api/tasks_integrity.py").read_text(encoding="utf-8")
    assert "janitor:cold" in text
    assert "NOT EXISTS (" in text
    assert "match_candidates" in text
    assert "match_pairs" in text
