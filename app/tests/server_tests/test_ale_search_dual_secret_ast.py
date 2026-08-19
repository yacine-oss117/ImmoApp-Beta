"""Anti-regression checks for versioned ALE search-key wiring."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_uow_sets_dual_search_secret_context() -> None:
    source = _read("server/pg/uow_internal.py")
    assert "app.ale_search_secrets" in source
    assert "app.ale_search_secret_version" in source
    assert "app.ale_search_secret_prev_version" in source


def test_db_hash_function_supports_dual_secret_mode() -> None:
    source = _read("server/alembic/versions/20260205_0005_ale_search_key_versioning.py")
    assert "current_setting('app.ale_search_secrets'" in source
    assert "string_to_array(secrets_text, ';')" in source
    assert "CROSS JOIN unnest(secrets)" in source
