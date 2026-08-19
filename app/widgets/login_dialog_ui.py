"""
UI builder for the login dialog.
"""

from __future__ import annotations

from typing import Protocol, cast

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.utils.i18n import tr_factory

_TR = tr_factory("LoginDialog")


class _LoginDialogAccess(Protocol):
    _base_url: QLineEdit
    _username: QLineEdit
    _password: QLineEdit
    _security_code: QLineEdit
    _remember: QCheckBox
    _remember_session: QCheckBox
    _status: QLabel
    _step_one_panel: QFrame
    _step_two_panel: QFrame
    _server_settings_panel: QFrame
    _btn_server_settings: QPushButton
    _btn_back: QPushButton
    _btn_primary: QPushButton
    _btn_register: QPushButton
    _btn_join_team: QPushButton
    _btn_activate: QPushButton
    _btn_resume_setup: QPushButton
    _resume_badge: QLabel
    _resume_hint: QLabel

    def _attempt_login(self) -> None: ...
    def _back_to_password_step(self) -> None: ...
    def _toggle_server_settings(self) -> None: ...
    def _open_register_dialog(self) -> None: ...
    def _open_join_team_dialog(self) -> None: ...
    def _open_activate_dialog(self) -> None: ...
    def _open_resume_setup(self) -> None: ...


def setup_login_dialog(dialog: QDialog) -> None:
    ui = cast(_LoginDialogAccess, dialog)
    dialog.setObjectName("immoLoginDialog")

    layout = QHBoxLayout(dialog)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    brand_panel = QFrame(dialog)
    brand_panel.setObjectName("immoLoginBrand")
    brand_panel.setMinimumWidth(240)
    brand_panel.setMaximumWidth(340)
    brand_layout = QVBoxLayout(brand_panel)
    brand_layout.setContentsMargins(28, 28, 28, 28)
    brand_layout.setSpacing(14)

    title = QLabel(_TR("ImmoApp"), brand_panel)
    title.setObjectName("immoLoginTitle")
    brand_layout.addWidget(title)

    tagline = QLabel(_TR("Welcome back.\nLet's get you signed in."), brand_panel)
    tagline.setObjectName("immoLoginTagline")
    tagline.setWordWrap(True)
    brand_layout.addWidget(tagline)

    badge = QLabel(_TR("Secure workspace"), brand_panel)
    badge.setObjectName("immoLoginBadge")
    brand_layout.addWidget(badge)
    brand_layout.addStretch(1)

    footer = QLabel(_TR("Need help? Use the buttons on the right."), brand_panel)
    footer.setObjectName("immoLoginFooter")
    brand_layout.addWidget(footer)

    form_panel = QFrame(dialog)
    form_panel.setObjectName("immoLoginForm")
    form_layout = QVBoxLayout(form_panel)
    form_layout.setContentsMargins(28, 30, 28, 24)
    form_layout.setSpacing(12)

    form_title = QLabel(_TR("Sign in"), form_panel)
    form_title.setObjectName("immoLoginHeading")
    form_layout.addWidget(form_title)

    hint = QLabel(_TR("Type your email and password."), form_panel)
    hint.setObjectName("immoLoginHint")
    hint.setWordWrap(True)
    form_layout.addWidget(hint)

    ui._step_one_panel = QFrame(form_panel)
    step_one_layout = QVBoxLayout(ui._step_one_panel)
    step_one_layout.setContentsMargins(0, 0, 0, 0)
    step_one_layout.setSpacing(12)

    settings_row = QHBoxLayout()
    ui._btn_server_settings = QPushButton(_TR("Change server"), ui._step_one_panel)
    ui._btn_server_settings.setProperty("immoVariant", "ghost")
    settings_row.addWidget(ui._btn_server_settings)
    settings_row.addStretch(1)
    step_one_layout.addLayout(settings_row)

    ui._server_settings_panel = QFrame(ui._step_one_panel)
    server_layout = QVBoxLayout(ui._server_settings_panel)
    server_layout.setContentsMargins(0, 0, 0, 0)
    server_layout.setSpacing(6)
    ui._base_url.setPlaceholderText(_TR("Server address (https://example.com)"))
    ui._base_url.setObjectName("immoLoginBaseUrlInput")
    ui._base_url.setAccessibleName(_TR("Server address"))
    ui._base_url.setMinimumHeight(40)
    server_layout.addWidget(ui._base_url)
    ui._server_settings_panel.setVisible(False)
    step_one_layout.addWidget(ui._server_settings_panel)

    ui._username.setPlaceholderText(_TR("Email"))
    ui._username.setObjectName("immoLoginUsernameInput")
    ui._username.setAccessibleName(_TR("Email"))
    ui._username.setMinimumHeight(40)
    ui._password.setPlaceholderText(_TR("Password"))
    ui._password.setObjectName("immoLoginPasswordInput")
    ui._password.setEchoMode(QLineEdit.EchoMode.Password)
    ui._password.setAccessibleName(_TR("Password"))
    ui._password.setMinimumHeight(40)

    step_one_layout.addWidget(ui._username)
    step_one_layout.addWidget(ui._password)

    links_row = QHBoxLayout()
    ui._btn_register = QPushButton(_TR("I need a new agency"), ui._step_one_panel)
    ui._btn_register.setObjectName("immoLoginRegisterButton")
    ui._btn_register.setProperty("immoVariant", "ghost")
    ui._btn_join_team = QPushButton(_TR("I have an invite code"), ui._step_one_panel)
    ui._btn_join_team.setObjectName("immoLoginJoinTeamButton")
    ui._btn_join_team.setProperty("immoVariant", "ghost")
    ui._btn_activate = QPushButton(_TR("I have an activation code"), ui._step_one_panel)
    ui._btn_activate.setObjectName("immoLoginActivateButton")
    ui._btn_activate.setProperty("immoVariant", "ghost")
    links_row.addWidget(ui._btn_register)
    links_row.addWidget(ui._btn_join_team)
    links_row.addWidget(ui._btn_activate)
    step_one_layout.addLayout(links_row)

    resume_row = QHBoxLayout()
    ui._resume_badge = QLabel(_TR("Saved setup"), ui._step_one_panel)
    ui._resume_badge.setObjectName("immoLoginResumeBadge")
    ui._resume_badge.setVisible(False)
    ui._resume_hint = QLabel("", ui._step_one_panel)
    ui._resume_hint.setObjectName("immoLoginHint")
    ui._resume_hint.setWordWrap(True)
    ui._resume_hint.setVisible(False)
    ui._btn_resume_setup = QPushButton(_TR("Continue setup"), ui._step_one_panel)
    ui._btn_resume_setup.setObjectName("immoLoginResumeSetupButton")
    ui._btn_resume_setup.setProperty("immoVariant", "secondary")
    ui._btn_resume_setup.setVisible(False)
    resume_row.addWidget(ui._resume_badge)
    resume_row.addWidget(ui._btn_resume_setup)
    resume_row.addStretch(1)
    step_one_layout.addLayout(resume_row)
    step_one_layout.addWidget(ui._resume_hint)

    step_one_layout.addWidget(ui._remember)
    step_one_layout.addWidget(ui._remember_session)
    form_layout.addWidget(ui._step_one_panel)

    ui._step_two_panel = QFrame(form_panel)
    step_two_layout = QVBoxLayout(ui._step_two_panel)
    step_two_layout.setContentsMargins(0, 0, 0, 0)
    step_two_layout.setSpacing(10)
    step_two_hint = QLabel(
        _TR("Great, one more step. Enter the 6-digit code from your phone app."),
        ui._step_two_panel,
    )
    step_two_hint.setWordWrap(True)
    step_two_hint.setObjectName("immoLoginHint")
    ui._security_code.setPlaceholderText(_TR("6-digit code"))
    ui._security_code.setObjectName("immoLoginSecurityCodeInput")
    ui._security_code.setAccessibleName(_TR("Phone app code"))
    ui._security_code.setMaxLength(12)
    ui._security_code.setMinimumHeight(40)
    step_two_layout.addWidget(step_two_hint)
    step_two_layout.addWidget(ui._security_code)
    ui._step_two_panel.setVisible(False)
    form_layout.addWidget(ui._step_two_panel)

    ui._status.setObjectName("immoLoginStatus")
    ui._status.setWordWrap(True)
    ui._status.setVisible(False)
    form_layout.addWidget(ui._status)

    buttons = QDialogButtonBox(form_panel)
    ui._btn_primary = QPushButton(_TR("Sign in"))
    ui._btn_primary.setObjectName("immoLoginPrimaryButton")
    ui._btn_primary.setProperty("immoVariant", "primary")
    ui._btn_back = QPushButton(_TR("Back"))
    ui._btn_back.setObjectName("immoLoginBackButton")
    ui._btn_back.setProperty("immoVariant", "ghost")
    ui._btn_back.setVisible(False)
    btn_cancel = QPushButton(_TR("Exit"))
    btn_cancel.setObjectName("immoLoginExitButton")
    btn_cancel.setProperty("immoVariant", "ghost")
    buttons.addButton(ui._btn_back, QDialogButtonBox.ButtonRole.ActionRole)
    buttons.addButton(btn_cancel, QDialogButtonBox.ButtonRole.RejectRole)
    buttons.addButton(ui._btn_primary, QDialogButtonBox.ButtonRole.AcceptRole)
    ui._btn_primary.clicked.connect(ui._attempt_login)
    ui._btn_back.clicked.connect(ui._back_to_password_step)
    ui._btn_server_settings.clicked.connect(ui._toggle_server_settings)
    ui._btn_register.clicked.connect(ui._open_register_dialog)
    ui._btn_join_team.clicked.connect(ui._open_join_team_dialog)
    ui._btn_activate.clicked.connect(ui._open_activate_dialog)
    ui._btn_resume_setup.clicked.connect(ui._open_resume_setup)
    btn_cancel.clicked.connect(dialog.reject)

    form_layout.addStretch(1)
    form_layout.addWidget(buttons)

    layout.addWidget(brand_panel)
    layout.addWidget(form_panel, 1)
    layout.setStretch(0, 0)
    layout.setStretch(1, 1)
