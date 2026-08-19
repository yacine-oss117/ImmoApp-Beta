"""UI builder for the quick-start onboarding chooser."""

from __future__ import annotations

from typing import Protocol, cast

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.utils.i18n import tr_factory

_TR = tr_factory("QuickStartDialog")


class _QuickStartAccess(Protocol):
    _title: QLabel
    _hint: QLabel
    _status: QLabel
    _btn_sign_in: QPushButton
    _btn_register: QPushButton
    _btn_join: QPushButton

    def _choose_sign_in(self) -> None: ...
    def _choose_register(self) -> None: ...
    def _choose_join(self) -> None: ...


def setup_quick_start_dialog(dialog: QDialog) -> None:
    ui = cast(_QuickStartAccess, dialog)
    dialog.setObjectName("QuickStartDialog")

    root = QVBoxLayout(dialog)
    root.setContentsMargins(20, 20, 20, 20)
    root.setSpacing(12)

    card = QFrame(dialog)
    card.setProperty("immoCard", "true")
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(18, 16, 18, 16)
    card_layout.setSpacing(10)

    ui._title = QLabel(_TR("Welcome to ImmoApp"), card)
    ui._title.setObjectName("dialogSectionTitle")
    card_layout.addWidget(ui._title)

    ui._hint = QLabel(
        _TR("Choose one option to continue. You can always change this later."),
        card,
    )
    ui._hint.setWordWrap(True)
    ui._hint.setProperty("immoState", "muted")
    card_layout.addWidget(ui._hint)

    ui._btn_sign_in = QPushButton(_TR("I already have an account"), card)
    ui._btn_sign_in.setObjectName("quickStartSignInButton")
    ui._btn_sign_in.setProperty("immoVariant", "primary")
    ui._btn_sign_in.setProperty("immoSize", "lg")
    card_layout.addWidget(ui._btn_sign_in)

    ui._btn_register = QPushButton(_TR("Create my agency"), card)
    ui._btn_register.setObjectName("quickStartRegisterButton")
    ui._btn_register.setProperty("immoVariant", "secondary")
    ui._btn_register.setProperty("immoSize", "lg")
    card_layout.addWidget(ui._btn_register)

    ui._btn_join = QPushButton(_TR("Join with an invite code"), card)
    ui._btn_join.setObjectName("quickStartJoinButton")
    ui._btn_join.setProperty("immoVariant", "secondary")
    ui._btn_join.setProperty("immoSize", "lg")
    card_layout.addWidget(ui._btn_join)

    ui._status = QLabel("", card)
    ui._status.setVisible(False)
    ui._status.setWordWrap(True)
    card_layout.addWidget(ui._status)

    root.addWidget(card)
    root.addStretch(1)

    buttons = QDialogButtonBox(dialog)
    close_btn = QPushButton(_TR("Close app"), dialog)
    close_btn.setProperty("immoVariant", "ghost")
    buttons.addButton(close_btn, QDialogButtonBox.ButtonRole.RejectRole)
    close_btn.clicked.connect(dialog.reject)
    root.addWidget(buttons)

    ui._btn_sign_in.clicked.connect(ui._choose_sign_in)
    ui._btn_register.clicked.connect(ui._choose_register)
    ui._btn_join.clicked.connect(ui._choose_join)


__all__ = ["setup_quick_start_dialog"]
