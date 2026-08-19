"""UI builder for user management dialog."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)

from app.utils.i18n import tr_factory

_TR = tr_factory("UserManagementDialog")

if TYPE_CHECKING:
    from app.views.dialogs.user_management_dialog import UserManagementDialog


def setup_user_management_ui(dialog: UserManagementDialog) -> None:
    dialog.setWindowTitle(_TR("Team Members"))
    dialog.setMinimumWidth(900)

    layout = QVBoxLayout(dialog)
    layout.setSpacing(10)

    header_row = QHBoxLayout()
    title = QLabel(_TR("Manage Your Team"), dialog)
    title.setAccessibleName(_TR("Team members title"))
    header_row.addWidget(title)
    header_row.addStretch()

    dialog._show_inactive = QCheckBox(_TR("Show inactive team members"), dialog)
    dialog._show_inactive.setAccessibleName(_TR("Show inactive team members"))
    header_row.addWidget(dialog._show_inactive)

    dialog._refresh_btn = QPushButton(_TR("Refresh"), dialog)
    dialog._refresh_btn.setAccessibleName(_TR("Refresh users list"))
    header_row.addWidget(dialog._refresh_btn)
    layout.addLayout(header_row)

    dialog._table = QTableWidget(dialog)
    dialog._table.setColumnCount(10)
    dialog._table.setHorizontalHeaderLabels(
        [
            _TR("Username"),
            _TR("Name"),
            _TR("Role"),
            _TR("Owner"),
            _TR("Active"),
            _TR("Reports to"),
            _TR("Can Import"),
            _TR("Hard Delete"),
            _TR("Email"),
            _TR("Invite status"),
        ]
    )
    dialog._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    dialog._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    dialog._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    dialog._table.horizontalHeader().setStretchLastSection(True)
    dialog._table.setAccessibleName(_TR("Users table"))
    layout.addWidget(dialog._table, 2)

    form = QFormLayout()
    dialog._username = QLineEdit(dialog)
    dialog._username.setAccessibleName(_TR("Username"))
    dialog._password = QLineEdit(dialog)
    dialog._password.setAccessibleName(_TR("Password"))
    dialog._password.setEchoMode(QLineEdit.EchoMode.Password)
    dialog._role = QComboBox(dialog)
    dialog._role.addItem(_TR("Agent"), "agent")
    dialog._role.addItem(_TR("Manager"), "manager")
    dialog._role.setAccessibleName(_TR("Role"))
    dialog._is_owner = QCheckBox(_TR("Owner"), dialog)
    dialog._is_owner.setAccessibleName(_TR("Is owner"))
    dialog._manager = QComboBox(dialog)
    dialog._manager.setAccessibleName(_TR("Manager"))
    dialog._manager.addItem(_TR("Select manager"), None)
    dialog._email = QLineEdit(dialog)
    dialog._email.setAccessibleName(_TR("Email"))
    dialog._first_name = QLineEdit(dialog)
    dialog._first_name.setAccessibleName(_TR("First name"))
    dialog._last_name = QLineEdit(dialog)
    dialog._last_name.setAccessibleName(_TR("Last name"))
    dialog._is_active = QCheckBox(_TR("Active"), dialog)
    dialog._is_active.setAccessibleName(_TR("Active"))
    dialog._can_import = QCheckBox(_TR("Can import"), dialog)
    dialog._can_import.setAccessibleName(_TR("Can import"))
    dialog._can_hard_delete = QCheckBox(_TR("Can hard delete"), dialog)
    dialog._can_hard_delete.setAccessibleName(_TR("Can hard delete"))

    form.addRow(_TR("Username"), dialog._username)
    form.addRow(_TR("Password"), dialog._password)
    form.addRow(_TR("Role"), dialog._role)
    form.addRow(_TR("Owner"), dialog._is_owner)
    form.addRow(_TR("Manager"), dialog._manager)
    form.addRow(_TR("Email"), dialog._email)
    form.addRow(_TR("First name"), dialog._first_name)
    form.addRow(_TR("Last name"), dialog._last_name)
    form.addRow(_TR("Active"), dialog._is_active)
    form.addRow(_TR("Can import"), dialog._can_import)
    form.addRow(_TR("Can hard delete"), dialog._can_hard_delete)
    layout.addLayout(form)

    actions = QHBoxLayout()
    dialog._new_btn = QPushButton(_TR("New Invitation"), dialog)
    dialog._new_btn.setAccessibleName(_TR("New team member"))
    dialog._save_btn = QPushButton(_TR("Save Changes"), dialog)
    dialog._save_btn.setAccessibleName(_TR("Save team member"))
    dialog._invite_btn = QPushButton(_TR("Send Invite"), dialog)
    dialog._invite_btn.setAccessibleName(_TR("Send invite"))
    dialog._resend_invite_btn = QPushButton(_TR("Resend Invite"), dialog)
    dialog._resend_invite_btn.setAccessibleName(_TR("Resend invite"))
    dialog._revoke_invite_btn = QPushButton(_TR("Revoke Invite"), dialog)
    dialog._revoke_invite_btn.setAccessibleName(_TR("Revoke invite"))
    dialog._deactivate_btn = QPushButton(_TR("Deactivate"), dialog)
    dialog._deactivate_btn.setAccessibleName(_TR("Deactivate team member"))
    dialog._close_btn = QPushButton(_TR("Close"), dialog)
    dialog._close_btn.setAccessibleName(_TR("Close"))
    actions.addWidget(dialog._new_btn)
    actions.addWidget(dialog._save_btn)
    actions.addWidget(dialog._invite_btn)
    actions.addWidget(dialog._resend_invite_btn)
    actions.addWidget(dialog._revoke_invite_btn)
    actions.addWidget(dialog._deactivate_btn)
    actions.addStretch()
    actions.addWidget(dialog._close_btn)
    layout.addLayout(actions)
