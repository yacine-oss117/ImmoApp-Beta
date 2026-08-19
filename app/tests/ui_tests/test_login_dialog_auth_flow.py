"""
Regression tests for login flow authentication behavior.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QDialog  # noqa: E402

from app.widgets import login_dialog as module  # noqa: E402

pytestmark = pytest.mark.ui


def test_login_dialog_is_resizable_with_dialog_minimums(qapp) -> None:
    dialog = module.LoginDialog()

    assert dialog.minimumWidth() == 840
    assert dialog.minimumHeight() == 520
    assert dialog.maximumWidth() > dialog.minimumWidth()
    assert dialog.maximumHeight() > dialog.minimumHeight()


def test_login_accepts_when_token_is_issued(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    monkeypatch.setattr(module, "run_blocking", lambda fn, timeout_ms=0: fn())
    monkeypatch.setattr(module, "get_access_token", lambda mfa_code=None: "token")
    monkeypatch.setattr(module, "flush_pending_network_work", lambda: None)

    dialog = module.LoginDialog()
    dialog._base_url.setText("http://localhost:8000")
    dialog._username.setText("admin")
    dialog._password.setText("admin")

    dialog._attempt_login()

    assert dialog.result() == int(QDialog.DialogCode.Accepted)


def test_login_shows_clear_status_for_invalid_credentials(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    monkeypatch.setattr(module, "run_blocking", lambda fn, timeout_ms=0: fn())
    monkeypatch.setattr(
        module,
        "get_access_token",
        lambda mfa_code=None: (_ for _ in ()).throw(
            module.ApiError(401, "No active account found with the given credentials")
        ),
    )
    monkeypatch.setattr(module, "flush_pending_network_work", lambda: None)
    monkeypatch.setattr(module, "show_error_with_diagnostics", lambda *a, **kw: None)
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *args, **kwargs: None)

    dialog = module.LoginDialog()
    dialog._base_url.setText("http://localhost:8000")
    dialog._username.setText("admin")
    dialog._password.setText("wrong")

    dialog._attempt_login()

    assert "invalid email or password" in dialog._status.text().lower()


def test_login_shows_lockout_status_when_server_temporarily_blocks_attempts(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    monkeypatch.setattr(module, "run_blocking", lambda fn, timeout_ms=0: fn())
    monkeypatch.setattr(
        module,
        "get_access_token",
        lambda mfa_code=None: (_ for _ in ()).throw(
            module.ApiError(401, "Too many failed attempts. Try again later.")
        ),
    )
    diagnostics_messages: list[str] = []
    monkeypatch.setattr(
        module,
        "show_error_with_diagnostics",
        lambda *args, **kwargs: diagnostics_messages.append(str(kwargs.get("message", ""))),
    )

    dialog = module.LoginDialog()
    dialog._base_url.setText("http://localhost:8000")
    dialog._username.setText("admin")
    dialog._password.setText("wrong")

    dialog._attempt_login()

    assert "too many failed attempts" in dialog._status.text().lower()
    assert diagnostics_messages == ["Too many failed attempts. Try again later."]


def test_login_shows_timeout_message_on_slow_server(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    monkeypatch.setattr(
        module,
        "run_blocking",
        lambda fn, timeout_ms=0: (_ for _ in ()).throw(TimeoutError("timed out")),
    )
    monkeypatch.setattr(module, "show_error_with_diagnostics", lambda *a, **kw: None)

    dialog = module.LoginDialog()
    dialog._base_url.setText("http://localhost:8000")
    dialog._username.setText("admin")
    dialog._password.setText("admin")

    dialog._attempt_login()

    assert "taking too long" in dialog._status.text().lower()
    assert dialog._status.property("immoState") == "error"


def test_login_shows_local_https_server_start_hint_when_connection_is_refused(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    monkeypatch.setattr(module, "run_blocking", lambda fn, timeout_ms=0: fn())
    monkeypatch.setattr(
        module,
        "get_access_token",
        lambda mfa_code=None: (_ for _ in ()).throw(
            RuntimeError(
                "API login failed: HTTPSConnectionPool(host='localhost', port=443): "
                "Max retries exceeded with url: /api/auth/token/ "
                "(Caused by NewConnectionError('HTTPSConnection(host=\\'localhost\\', port=443): "
                "Failed to establish a new connection: [WinError 10061] No connection could be made "
                "because the target machine actively refused it'))"
            )
        ),
    )
    diagnostics_messages: list[str] = []
    monkeypatch.setattr(
        module,
        "show_error_with_diagnostics",
        lambda *args, **kwargs: diagnostics_messages.append(str(kwargs.get("message", ""))),
    )

    dialog = module.LoginDialog()
    dialog._base_url.setText("https://localhost")
    dialog._username.setText("admin")
    dialog._password.setText("admin")

    dialog._attempt_login()

    assert "local secure server is not running" in dialog._status.text().lower()
    assert diagnostics_messages
    assert "start the docker server" in diagnostics_messages[0].lower()


def test_login_step_two_transition_uses_progression_state_not_error(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    monkeypatch.setattr(module, "run_blocking", lambda fn, timeout_ms=0: fn())

    calls: dict[str, int] = {"diagnostics": 0}

    def _token(mfa_code=None):
        if not mfa_code:
            raise module.ApiError(403, "MFA code required or invalid.")
        return "token"

    monkeypatch.setattr(module, "get_access_token", _token)
    monkeypatch.setattr(module, "flush_pending_network_work", lambda: None)
    monkeypatch.setattr(
        module,
        "show_error_with_diagnostics",
        lambda *a, **kw: calls.__setitem__("diagnostics", calls["diagnostics"] + 1),
    )

    dialog = module.LoginDialog()
    dialog._base_url.setText("http://localhost:8000")
    dialog._username.setText("admin")
    dialog._password.setText("admin")

    dialog._attempt_login()

    assert dialog.result() != int(QDialog.DialogCode.Accepted)
    assert dialog._step_two_active is True
    assert dialog._status.property("immoState") == "loading"
    assert "one more step" in dialog._status.text().lower()
    assert "failed" not in dialog._status.text().lower()
    assert calls["diagnostics"] == 0

    dialog._security_code.setText("123456")
    dialog._attempt_login()
    assert dialog.result() == int(QDialog.DialogCode.Accepted)


def test_login_step_two_normalizes_code_input(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    monkeypatch.setattr(module, "run_blocking", lambda fn, timeout_ms=0: fn())

    calls: dict[str, str | None] = {"code": None}

    def _token(mfa_code=None):
        if not mfa_code:
            raise module.ApiError(403, "MFA code required or invalid.")
        calls["code"] = str(mfa_code)
        return "token"

    monkeypatch.setattr(module, "get_access_token", _token)
    monkeypatch.setattr(module, "flush_pending_network_work", lambda: None)
    monkeypatch.setattr(module, "show_error_with_diagnostics", lambda *a, **kw: None)

    dialog = module.LoginDialog()
    dialog._base_url.setText("http://localhost:8000")
    dialog._username.setText("admin")
    dialog._password.setText("admin")

    dialog._attempt_login()
    assert dialog._step_two_active is True

    dialog._security_code.setText("12 34-56")
    dialog._attempt_login()

    assert calls["code"] == "123456"
    assert dialog._security_code.text() == "123456"
    assert dialog.result() == int(QDialog.DialogCode.Accepted)


def test_ensure_login_reuses_existing_token_without_dialog(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    monkeypatch.setattr(module, "set_api_config", lambda **kwargs: None)
    monkeypatch.setattr(module, "get_access_token", lambda mfa_code=None: "token")

    class _DialogShouldNotOpen:  # pragma: no cover
        def __init__(self) -> None:
            raise AssertionError("LoginDialog should not open when token already exists")

    monkeypatch.setattr(module, "LoginDialog", _DialogShouldNotOpen)

    assert module.ensure_login(qapp) is True


def test_login_shows_resume_setup_button_when_draft_exists(
    monkeypatch: pytest.MonkeyPatch, qapp
) -> None:
    monkeypatch.setattr(module, "resolve_resume_target", lambda: module.REGISTER_DRAFT_KEY)
    events: list[tuple[str, str]] = []
    monkeypatch.setattr(
        module,
        "record_onboarding_event",
        lambda event, **kwargs: events.append((str(event), str(kwargs.get("outcome") or ""))),
    )

    dialog = module.LoginDialog()

    assert dialog._btn_resume_setup.isHidden() is False
    assert dialog._resume_badge.isHidden() is False
    assert "continue where you left off" in dialog._resume_hint.text().lower()
    assert "continue" in dialog._btn_resume_setup.text().lower()
    assert ("resume_setup_available", "register") in events


def test_login_resume_setup_dispatches_to_target(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    monkeypatch.setattr(module, "resolve_resume_target", lambda: module.ACTIVATE_DRAFT_KEY)
    called: list[str] = []
    events: list[tuple[str, str]] = []
    monkeypatch.setattr(
        module.LoginDialog, "_open_activate_dialog", lambda self: called.append("ok")
    )
    monkeypatch.setattr(
        module,
        "record_onboarding_event",
        lambda event, **kwargs: events.append((str(event), str(kwargs.get("outcome") or ""))),
    )

    dialog = module.LoginDialog()
    dialog._open_resume_setup()

    assert called == ["ok"]
    assert ("resume_setup_opened", "activate") in events
