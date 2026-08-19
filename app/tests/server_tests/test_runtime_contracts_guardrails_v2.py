from __future__ import annotations

from pathlib import Path

from scripts.repo_layout import COMPOSE_YML


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_no_legacy_cache_all_runtime_contract() -> None:
    assert "def get_all_cached_counts(" not in _read("core/data/match_cache_read.py")
    assert "def get_all_cached_counts(" not in _read("server/services/match_cache.py")
    assert "def get_all_cached_counts(" not in _read("app/services/match_cache.py")


def test_no_legacy_beat_interval_schedule() -> None:
    text = _read("server/immoapp_server/settings_database.py")
    assert '"schedule": 60 * 60 * 24' not in text
    assert '"schedule": 60 * 60 * 24 * 7' not in text


def test_worker_and_beat_healthchecks_not_disabled() -> None:
    compose = COMPOSE_YML.read_text(encoding="utf-8")
    assert "disable: true" not in compose
