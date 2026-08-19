from __future__ import annotations

import importlib

import pytest

import app.services.ui_capabilities as ui_caps

pytestmark = pytest.mark.ui


def _reload_module():
    return importlib.reload(ui_caps)


def test_ui_capabilities_default_false_without_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    mod = _reload_module()
    key = mod.normalize_account_key(api_base="https://api.example.test", username="owner")
    mod.clear_memory_capabilities(key)
    caps = mod.load_capabilities(key)
    assert caps == mod.UiCapabilities()


def test_ui_capabilities_loads_cached_values(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    mod = _reload_module()
    key = mod.normalize_account_key(api_base="https://api.example.test", username="owner")
    expected = mod.UiCapabilities(
        can_manage_team=True,
        can_view_activity=True,
        can_view_security=True,
        can_open_admin_tools=True,
    )
    mod._store_cached(key, expected)
    mod.clear_memory_capabilities(key)
    loaded = mod.load_capabilities(key)
    assert loaded == expected


def test_ui_capabilities_refresh_uses_cached_on_probe_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    mod = _reload_module()
    key = mod.normalize_account_key(api_base="https://api.example.test", username="owner")
    cached = mod.UiCapabilities(
        can_manage_team=True,
        can_view_activity=False,
        can_view_security=False,
        can_open_admin_tools=False,
    )
    mod._store_cached(key, cached)
    mod.clear_memory_capabilities(key)

    def _fake_runner(func, on_success, on_error, *args, **kwargs):
        on_error(RuntimeError("offline"))

    monkeypatch.setattr(mod, "run_background_result", _fake_runner)

    seen: list[mod.UiCapabilities] = []
    mod.refresh_capabilities_async(key, callback=seen.append)
    assert seen and seen[-1] == cached


def test_ui_capabilities_account_key_separates_tenants_and_users() -> None:
    mod = _reload_module()

    key_a = mod.normalize_account_key(
        api_base="https://api.example.test",
        agency_id=1,
        user_id=2,
    )
    key_b = mod.normalize_account_key(
        api_base="https://api.example.test",
        agency_id=2,
        user_id=2,
    )
    key_c = mod.normalize_account_key(
        api_base="https://api.example.test",
        agency_id=1,
        user_id=3,
    )

    assert key_a != key_b
    assert key_a != key_c
