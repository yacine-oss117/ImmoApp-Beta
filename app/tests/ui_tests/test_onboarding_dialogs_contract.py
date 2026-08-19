from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox

from app.services.api_client import ApiError
from app.widgets import activate_dialog as activate_module
from app.widgets import join_team_dialog as join_module
from app.widgets import register_dialog as register_module

pytestmark = pytest.mark.ui


def test_activate_dialog_normalizes_activation_code(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    monkeypatch.setattr(activate_module, "load_onboarding_draft", lambda _key: {})
    monkeypatch.setattr(activate_module, "save_onboarding_draft", lambda _key, _payload: None)
    dialog = activate_module.ActivateDialog()
    dialog._email.setText("owner@example.com")
    dialog._activation_code.setText("ab-12 cd34")

    dialog._go_next()

    assert dialog._activation_code.text() == "AB12CD34"
    assert dialog._stack.currentIndex() == 1


def test_join_team_dialog_normalizes_invite_code(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    monkeypatch.setattr(join_module, "load_onboarding_draft", lambda _key: {})
    monkeypatch.setattr(join_module, "save_onboarding_draft", lambda _key, _payload: None)
    dialog = join_module.JoinTeamDialog()
    dialog._invite_code.setText("ab-12 c3")

    dialog._go_next()

    assert dialog._invite_code.text() == "AB12C3"
    assert dialog._stack.currentIndex() == 1


def test_owner_onboarding_dialogs_expose_stable_e2e_automation_ids(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    monkeypatch.setattr(register_module, "load_onboarding_draft", lambda _key: {})
    monkeypatch.setattr(register_module, "save_onboarding_draft", lambda _key, _payload: None)
    monkeypatch.setattr(activate_module, "load_onboarding_draft", lambda _key: {})
    monkeypatch.setattr(activate_module, "save_onboarding_draft", lambda _key, _payload: None)

    register_dialog = register_module.RegisterDialog()
    activate_dialog = activate_module.ActivateDialog()

    assert register_dialog.objectName() == "immoRegisterDialog"
    assert register_dialog._agency_name.objectName() == "registerAgencyNameInput"
    assert register_dialog._owner_email.objectName() == "registerOwnerEmailInput"
    assert register_dialog._terms_accepted.objectName() == "registerTermsAcceptedCheckbox"
    assert register_dialog._btn_next.objectName() == "registerNextButton"
    assert activate_dialog.objectName() == "immoActivateDialog"
    assert activate_dialog._email.objectName() == "activateEmailInput"
    assert activate_dialog._activation_code.objectName() == "activateCodeInput"
    assert activate_dialog._password.objectName() == "activatePasswordInput"
    assert activate_dialog._password_confirm.objectName() == "activatePasswordConfirmInput"
    assert activate_dialog._btn_next.objectName() == "activateNextButton"


def test_register_dialog_maps_api_error_to_friendly_copy(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    monkeypatch.setattr(
        register_module,
        "run_blocking",
        lambda fn, timeout_ms=0: (_ for _ in ()).throw(ApiError(409, "owner_email exists")),
    )

    dialog = register_module.RegisterDialog()
    dialog._agency_name.setText("Demo Agency")
    dialog._legal_name.setText("Demo LLC")
    dialog._registry_number.setText("REG-123")
    dialog._agency_address.setText("123 Main St")
    dialog._agency_city.setText("Algiers")
    dialog._agency_postal_code.setText("16000")
    dialog._go_next()

    dialog._owner_first_name.setText("Fatima")
    dialog._owner_last_name.setText("Agent")
    dialog._owner_email.setText("fatima@example.com")
    dialog._owner_phone.setText("+213555123456")
    dialog._terms_accepted.setChecked(True)
    dialog._go_next()

    assert "already used" in dialog._status.text().lower()


def test_register_dialog_maps_registration_unavailable_code(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    monkeypatch.setattr(
        register_module,
        "run_blocking",
        lambda fn, timeout_ms=0: (_ for _ in ()).throw(
            ApiError(
                503, "Registration is not available at this time.", code="REGISTRATION_UNAVAILABLE"
            )
        ),
    )

    dialog = register_module.RegisterDialog()
    dialog._agency_name.setText("Demo Agency")
    dialog._legal_name.setText("Demo LLC")
    dialog._registry_number.setText("REG-123")
    dialog._agency_address.setText("123 Main St")
    dialog._agency_city.setText("Algiers")
    dialog._agency_postal_code.setText("16000")
    dialog._go_next()

    dialog._owner_first_name.setText("Fatima")
    dialog._owner_last_name.setText("Agent")
    dialog._owner_email.setText("fatima@example.com")
    dialog._owner_phone.setText("+213555123456")
    dialog._terms_accepted.setChecked(True)
    dialog._go_next()

    assert "registration is not available" in dialog._status.text().lower()


def test_register_dialog_restores_draft_state(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    monkeypatch.setattr(
        register_module,
        "load_onboarding_draft",
        lambda _key: {
            "agency_name": "Demo Agency",
            "owner_email": "owner@example.com",
            "terms_accepted": True,
            "step": 1,
        },
    )
    monkeypatch.setattr(register_module, "save_onboarding_draft", lambda _key, _payload: None)

    dialog = register_module.RegisterDialog()

    assert dialog._agency_name.text() == "Demo Agency"
    assert dialog._owner_email.text() == "owner@example.com"
    assert dialog._terms_accepted.isChecked() is True
    assert dialog._stack.currentIndex() == 1


def test_activate_dialog_draft_excludes_password_fields(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(activate_module, "load_onboarding_draft", lambda _key: {})
    monkeypatch.setattr(
        activate_module,
        "save_onboarding_draft",
        lambda _key, payload: captured.update(payload),
    )

    dialog = activate_module.ActivateDialog()
    dialog._email.setText("owner@example.com")
    dialog._activation_code.setText("AB12CD34")
    dialog._password.setText("StrongPass!123")
    dialog._password_confirm.setText("StrongPass!123")
    dialog._save_draft()

    assert captured.get("email") == "owner@example.com"
    assert captured.get("activation_code") == "AB12CD34"
    assert "password" not in captured
    assert "password_confirm" not in captured


def test_join_dialog_clears_draft_after_success(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    cleared: list[str] = []
    monkeypatch.setattr(join_module, "load_onboarding_draft", lambda _key: {})
    monkeypatch.setattr(join_module, "save_onboarding_draft", lambda _key, _payload: None)
    monkeypatch.setattr(join_module, "clear_onboarding_draft", lambda key: cleared.append(key))
    monkeypatch.setattr(
        join_module,
        "run_blocking",
        lambda fn, timeout_ms=0: {
            "tokens": {"access": "token"},
            "agency_name": "Demo Agency",
        },
    )

    dialog = join_module.JoinTeamDialog()
    dialog._invite_code.setText("AB12C3")
    dialog._go_next()
    dialog._email.setText("agent@example.com")
    dialog._password.setText("StrongPass!123")
    dialog._password_confirm.setText("StrongPass!123")
    dialog._go_next()

    assert "join_team_dialog" in cleared


def test_register_dialog_discard_saved_progress_clears_fields(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    monkeypatch.setattr(
        register_module,
        "load_onboarding_draft",
        lambda _key: {"agency_name": "Demo Agency", "step": 1},
    )
    monkeypatch.setattr(register_module, "save_onboarding_draft", lambda _key, _payload: None)
    monkeypatch.setattr(register_module, "has_onboarding_draft", lambda _key: True)
    cleared: list[str] = []
    monkeypatch.setattr(register_module, "clear_onboarding_draft", lambda key: cleared.append(key))
    monkeypatch.setattr(
        register_module.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    dialog = register_module.RegisterDialog()
    dialog._discard_saved_progress()

    assert dialog._agency_name.text() == ""
    assert dialog._stack.currentIndex() == 0
    assert "register_dialog" in cleared


def test_activate_resume_completion_emits_resume_completed_event(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        activate_module,
        "record_onboarding_event",
        lambda event, **kwargs: events.append(str(event)),
    )
    monkeypatch.setattr(
        activate_module,
        "load_onboarding_draft",
        lambda _key: {"email": "owner@example.com", "activation_code": "AB12CD34", "step": 1},
    )
    monkeypatch.setattr(activate_module, "save_onboarding_draft", lambda _key, _payload: None)
    monkeypatch.setattr(activate_module, "clear_onboarding_draft", lambda _key: None)
    monkeypatch.setattr(
        activate_module,
        "run_blocking",
        lambda fn, timeout_ms=0: {"tokens": {"access": "token"}},
    )

    dialog = activate_module.ActivateDialog()
    dialog._password.setText("StrongPass!123")
    dialog._password_confirm.setText("StrongPass!123")
    dialog._go_next()

    assert "activate_resume_loaded" in events
    assert "activate_resume_completed" in events


def test_register_dialog_shows_timeout_message(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    monkeypatch.setattr(
        register_module,
        "run_blocking",
        lambda fn, timeout_ms=0: (_ for _ in ()).throw(TimeoutError("timed out")),
    )

    dialog = register_module.RegisterDialog()
    dialog._agency_name.setText("Demo Agency")
    dialog._legal_name.setText("Demo LLC")
    dialog._registry_number.setText("REG-123")
    dialog._agency_address.setText("123 Main St")
    dialog._agency_city.setText("Algiers")
    dialog._agency_postal_code.setText("16000")
    dialog._go_next()
    dialog._owner_first_name.setText("Fatima")
    dialog._owner_last_name.setText("Agent")
    dialog._owner_email.setText("fatima@example.com")
    dialog._owner_phone.setText("+213555123456")
    dialog._terms_accepted.setChecked(True)
    dialog._go_next()

    assert "taking too long" in dialog._status.text().lower()
    assert dialog._status.property("immoState") == "error"


def test_join_dialog_shows_timeout_message(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    monkeypatch.setattr(
        join_module,
        "run_blocking",
        lambda fn, timeout_ms=0: (_ for _ in ()).throw(TimeoutError("timed out")),
    )
    monkeypatch.setattr(join_module, "load_onboarding_draft", lambda _key: {})
    monkeypatch.setattr(join_module, "save_onboarding_draft", lambda _key, _payload: None)

    dialog = join_module.JoinTeamDialog()
    dialog._invite_code.setText("AB12C3")
    dialog._go_next()
    dialog._email.setText("agent@example.com")
    dialog._password.setText("StrongPass!123")
    dialog._password_confirm.setText("StrongPass!123")
    dialog._go_next()

    assert "taking too long" in dialog._status.text().lower()
    assert dialog._status.property("immoState") == "error"


def test_activate_dialog_shows_timeout_message(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    monkeypatch.setattr(
        activate_module,
        "run_blocking",
        lambda fn, timeout_ms=0: (_ for _ in ()).throw(TimeoutError("timed out")),
    )
    monkeypatch.setattr(activate_module, "load_onboarding_draft", lambda _key: {})
    monkeypatch.setattr(activate_module, "save_onboarding_draft", lambda _key, _payload: None)

    dialog = activate_module.ActivateDialog()
    dialog._email.setText("owner@example.com")
    dialog._activation_code.setText("AB12CD34")
    dialog._go_next()
    dialog._password.setText("StrongPass!123")
    dialog._password_confirm.setText("StrongPass!123")
    dialog._go_next()

    assert "taking too long" in dialog._status.text().lower()
    assert dialog._status.property("immoState") == "error"
