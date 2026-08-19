"""UI builder for team invite acceptance dialog."""

from __future__ import annotations

from typing import Protocol, cast

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.utils.i18n import tr_factory

_TR = tr_factory("JoinTeamDialog")


class _JoinTeamDialogAccess(Protocol):
    _stack: QStackedWidget
    _status: QLabel
    _btn_back: QPushButton
    _btn_discard: QPushButton
    _btn_next: QPushButton
    _invite_code: QLineEdit
    _email: QLineEdit
    _password: QLineEdit
    _password_confirm: QLineEdit
    _summary: QLabel

    def _go_back(self) -> None: ...
    def _go_next(self) -> None: ...
    def _discard_saved_progress(self) -> None: ...


def _line(parent: QWidget, placeholder: str, *, password: bool = False) -> QLineEdit:
    line = QLineEdit(parent)
    line.setPlaceholderText(placeholder)
    line.setMinimumHeight(38)
    if password:
        line.setEchoMode(QLineEdit.EchoMode.Password)
    return line


def setup_join_team_dialog(dialog: QDialog) -> None:
    ui = cast(_JoinTeamDialogAccess, dialog)
    dialog.setWindowTitle(_TR("Join your team"))
    dialog.setMinimumWidth(500)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)

    title = QLabel(_TR("Join your agency in 2 steps"), dialog)
    title.setObjectName("immoDialogTitle")
    layout.addWidget(title)

    ui._stack = QStackedWidget(dialog)
    layout.addWidget(ui._stack, 1)

    page_one = QWidget(ui._stack)
    page_one_layout = QVBoxLayout(page_one)
    page_one_layout.addWidget(QLabel(_TR("Step 1 of 2 - Enter invite code"), page_one))
    ui._invite_code = _line(page_one, _TR("Invite code from your manager (6 characters)"))
    page_one_layout.addWidget(ui._invite_code)
    page_one_layout.addStretch(1)
    ui._stack.addWidget(page_one)

    page_two = QWidget(ui._stack)
    page_two_layout = QVBoxLayout(page_two)
    page_two_layout.addWidget(QLabel(_TR("Step 2 of 2 - Create your password"), page_two))
    ui._email = _line(page_two, _TR("Email"))
    ui._password = _line(page_two, _TR("Choose password"), password=True)
    ui._password_confirm = _line(page_two, _TR("Confirm password"), password=True)
    page_two_layout.addWidget(ui._email)
    page_two_layout.addWidget(ui._password)
    page_two_layout.addWidget(ui._password_confirm)
    page_two_layout.addStretch(1)
    ui._stack.addWidget(page_two)

    page_three = QWidget(ui._stack)
    page_three_layout = QVBoxLayout(page_three)
    ui._summary = QLabel("", page_three)
    ui._summary.setWordWrap(True)
    page_three_layout.addWidget(ui._summary)
    page_three_layout.addStretch(1)
    ui._stack.addWidget(page_three)

    ui._status = QLabel("", dialog)
    ui._status.setWordWrap(True)
    ui._status.setVisible(False)
    layout.addWidget(ui._status)

    actions = QHBoxLayout()
    ui._btn_back = QPushButton(_TR("Back"), dialog)
    ui._btn_discard = QPushButton(_TR("Discard saved progress"), dialog)
    ui._btn_discard.setProperty("immoVariant", "ghost")
    btn_cancel = QPushButton(_TR("Cancel"), dialog)
    ui._btn_next = QPushButton(_TR("Continue"), dialog)
    ui._btn_next.setProperty("immoVariant", "primary")
    actions.addWidget(ui._btn_back)
    actions.addWidget(ui._btn_discard)
    actions.addStretch(1)
    actions.addWidget(btn_cancel)
    actions.addWidget(ui._btn_next)
    layout.addLayout(actions)

    ui._btn_back.clicked.connect(ui._go_back)
    ui._btn_discard.clicked.connect(ui._discard_saved_progress)
    ui._btn_next.clicked.connect(ui._go_next)
    btn_cancel.clicked.connect(dialog.reject)


__all__ = ["setup_join_team_dialog"]
