"""Ensure rerun enqueue uses delay to avoid lock race."""

from pathlib import Path


def test_match_pairs_rerun_uses_countdown() -> None:
    text = Path("server/api/tasks_match_pairs.py").read_text(encoding="utf-8")
    assert "apply_async" in text
    assert "countdown=5" in text
