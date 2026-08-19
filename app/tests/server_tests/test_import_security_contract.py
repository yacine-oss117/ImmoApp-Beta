from __future__ import annotations

from core.importer.security import (
    import_security_limits,
    import_security_limits_snapshot,
    reload_import_security_limits,
)


def test_import_security_limits_are_process_cached_until_cache_clear(monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_IMPORT_MAX_ROWS", "20001")
    import_security_limits.cache_clear()
    try:
        first = import_security_limits()

        monkeypatch.setenv("IMMOAPP_IMPORT_MAX_ROWS", "20002")
        cached = import_security_limits()

        assert first.max_rows == 20001
        assert cached.max_rows == 20001

        import_security_limits.cache_clear()
        refreshed = import_security_limits()
        assert refreshed.max_rows == 20002
    finally:
        import_security_limits.cache_clear()


def test_reload_import_security_limits_refreshes_the_cached_snapshot(monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_IMPORT_MAX_ROWS", "21001")
    import_security_limits.cache_clear()
    try:
        assert import_security_limits().max_rows == 21001

        monkeypatch.setenv("IMMOAPP_IMPORT_MAX_ROWS", "21002")
        reloaded = reload_import_security_limits()

        assert reloaded.max_rows == 21002
        assert import_security_limits().max_rows == 21002
    finally:
        import_security_limits.cache_clear()


def test_import_security_limits_snapshot_exposes_live_cache_policy() -> None:
    import_security_limits.cache_clear()
    try:
        snapshot = import_security_limits_snapshot()

        assert snapshot["cache_policy"] == "process_cached_until_reload_or_restart"
        assert snapshot["reload_supported"] is True
        assert int(snapshot["max_rows"]) == import_security_limits().max_rows
    finally:
        import_security_limits.cache_clear()
