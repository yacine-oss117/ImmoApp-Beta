from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QScrollArea

from app.views.dialogs import agency_settings_dialog as module

pytestmark = pytest.mark.ui


def _setup_common_mocks(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    calls: dict[str, object] = {}
    monkeypatch.setattr(module, "get_agency_name", lambda: "Demo Agency")
    monkeypatch.setattr(module, "get_contract_serial_prefix", lambda: "C21")
    monkeypatch.setattr(module, "get_agency_logo_path", lambda: "")
    monkeypatch.setattr(module, "get_agency_signature_path", lambda: "")
    monkeypatch.setattr(module, "set_agency_name", lambda value: calls.__setitem__("name", value))
    monkeypatch.setattr(
        module,
        "set_agency_setting",
        lambda key, value: calls.__setitem__(f"setting:{key}", value),
    )
    monkeypatch.setattr(
        module,
        "set_onboarding_analytics_enabled",
        lambda enabled: calls.__setitem__("analytics", bool(enabled)),
    )
    monkeypatch.setattr(
        module,
        "get_onboarding_draft_statuses",
        lambda: {
            module.REGISTER_DRAFT_KEY: {"exists": False, "updated_at": ""},
            module.ACTIVATE_DRAFT_KEY: {"exists": False, "updated_at": ""},
            module.JOIN_TEAM_DRAFT_KEY: {"exists": False, "updated_at": ""},
        },
    )
    monkeypatch.setattr(module, "resolve_resume_target", lambda: None)
    monkeypatch.setattr(
        module,
        "get_onboarding_funnel_snapshot",
        lambda lookback_days=7: {
            "register_started": 0,
            "register_completed": 0,
            "register_abandoned": 0,
            "activate_started": 0,
            "activate_completed": 0,
            "activate_abandoned": 0,
            "join_started": 0,
            "join_completed": 0,
            "join_abandoned": 0,
        },
    )
    monkeypatch.setattr(module, "clear_all_onboarding_drafts", lambda: None)
    return calls


def test_agency_settings_loads_analytics_preference(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    _setup_common_mocks(monkeypatch)
    monkeypatch.setattr(module, "is_onboarding_analytics_enabled", lambda: False)

    dialog = module.AgencySettingsDialog()

    assert dialog._analytics_opt_in.isChecked() is False


def test_agency_settings_save_persists_analytics_and_profile(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    calls = _setup_common_mocks(monkeypatch)
    monkeypatch.setattr(module, "is_onboarding_analytics_enabled", lambda: True)

    dialog = module.AgencySettingsDialog()
    dialog._name_edit.setText("Blue Homes")
    dialog._prefix_edit.setText("")
    dialog._analytics_opt_in.setChecked(False)

    dialog._on_save()

    assert calls.get("name") == "Blue Homes"
    assert calls.get("analytics") is False
    assert calls.get("setting:contract_serial_prefix") == ""


def test_agency_settings_reset_welcome_guide_updates_status(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    _setup_common_mocks(monkeypatch)
    monkeypatch.setattr(module, "is_onboarding_analytics_enabled", lambda: True)
    called: dict[str, bool] = {"reset": False}
    monkeypatch.setattr(
        module,
        "reset_quick_start_seen",
        lambda: called.__setitem__("reset", True),
    )
    monkeypatch.setattr(module, "reset_next_steps_card", lambda: None)

    dialog = module.AgencySettingsDialog()
    dialog._on_reset_welcome_guide()

    assert called["reset"] is True
    assert "next launch" in dialog._status.text().lower()


def test_agency_settings_health_panel_shows_continue_target(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    _setup_common_mocks(monkeypatch)
    monkeypatch.setattr(module, "is_onboarding_analytics_enabled", lambda: True)
    monkeypatch.setattr(
        module,
        "get_onboarding_draft_statuses",
        lambda: {
            module.REGISTER_DRAFT_KEY: {"exists": True, "updated_at": ""},
            module.ACTIVATE_DRAFT_KEY: {"exists": False, "updated_at": ""},
            module.JOIN_TEAM_DRAFT_KEY: {"exists": False, "updated_at": ""},
        },
    )
    monkeypatch.setattr(module, "resolve_resume_target", lambda: module.REGISTER_DRAFT_KEY)

    dialog = module.AgencySettingsDialog()

    assert dialog._btn_continue_saved_setup.isEnabled() is True
    assert "continue agency setup" in dialog._btn_continue_saved_setup.text().lower()


def test_agency_settings_discard_saved_setup_clears_all(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    _setup_common_mocks(monkeypatch)
    monkeypatch.setattr(module, "is_onboarding_analytics_enabled", lambda: True)
    monkeypatch.setattr(
        module,
        "get_onboarding_draft_statuses",
        lambda: {
            module.REGISTER_DRAFT_KEY: {"exists": True, "updated_at": ""},
            module.ACTIVATE_DRAFT_KEY: {"exists": True, "updated_at": ""},
            module.JOIN_TEAM_DRAFT_KEY: {"exists": False, "updated_at": ""},
        },
    )
    called: dict[str, bool] = {"cleared": False}
    monkeypatch.setattr(
        module,
        "clear_all_onboarding_drafts",
        lambda: called.__setitem__("cleared", True),
    )
    monkeypatch.setattr(
        module.QMessageBox,
        "question",
        lambda *args, **kwargs: module.QMessageBox.StandardButton.Yes,
    )

    dialog = module.AgencySettingsDialog()
    dialog._on_discard_saved_setup()

    assert called["cleared"] is True
    assert "removed" in dialog._status.text().lower()


def test_agency_settings_dialog_uses_scrollable_content(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    _setup_common_mocks(monkeypatch)
    monkeypatch.setattr(module, "is_onboarding_analytics_enabled", lambda: True)

    dialog = module.AgencySettingsDialog()

    assert isinstance(dialog._scroll_area, QScrollArea)
    assert dialog._scroll_area.widgetResizable() is True
    assert dialog._scroll_area.widget() is not None
    assert dialog._status.parent() is dialog
