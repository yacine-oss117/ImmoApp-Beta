from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.services import dashboard_cache as cache_module
from app.services.dashboard_cache import DashboardStats
from app.views import dashboard as module

pytestmark = pytest.mark.ui


def test_dashboard_shows_next_steps_card_when_enabled(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    stats = DashboardStats(client_count=0, listing_count=0, is_stale=False)
    monkeypatch.setattr(module, "should_show_next_steps_card", lambda: True)
    monkeypatch.setattr(module, "dismiss_next_steps_card", lambda dismissed=True: None)
    monkeypatch.setattr(module, "record_onboarding_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(cache_module, "is_cache_stale", lambda: False)
    monkeypatch.setattr(cache_module, "get_dashboard_stats", lambda: stats)

    dialog = module.DashboardTab()

    assert dialog._ui.next_steps_card.isHidden() is False
    hint = dialog._ui.next_steps_hint.text().lower()
    assert "client" in hint
    assert "match" in hint
    assert dialog._ui.next_steps_clients_btn.isEnabled() is True
    assert dialog._ui.next_steps_properties_btn.isEnabled() is False
    assert dialog._ui.next_steps_matches_btn.isEnabled() is False


def test_dashboard_next_steps_actions_trigger_callbacks(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    stats = DashboardStats(client_count=1, listing_count=1, is_stale=False)
    monkeypatch.setattr(module, "should_show_next_steps_card", lambda: True)
    monkeypatch.setattr(module, "dismiss_next_steps_card", lambda dismissed=True: None)
    monkeypatch.setattr(module, "record_onboarding_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(cache_module, "is_cache_stale", lambda: False)
    monkeypatch.setattr(cache_module, "get_dashboard_stats", lambda: stats)

    called: list[str] = []
    dashboard = module.DashboardTab(
        on_open_clients_cb=lambda: called.append("clients"),
        on_open_properties_cb=lambda: called.append("properties"),
        on_open_matches_cb=lambda: called.append("matches"),
    )

    dashboard._ui.next_steps_clients_btn.click()
    dashboard._ui.next_steps_properties_btn.click()
    dashboard._ui.next_steps_matches_btn.click()

    assert called == ["clients", "properties", "matches"]
    assert dashboard._ui.next_steps_clients_btn.isEnabled() is True
    assert dashboard._ui.next_steps_properties_btn.isEnabled() is True
    assert dashboard._ui.next_steps_matches_btn.isEnabled() is True
