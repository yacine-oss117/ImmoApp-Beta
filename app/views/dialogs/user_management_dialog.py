"""User management dialog (thin client: API only)."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from app.services.api_client import ApiError
from app.services.users_repository import (
    create_user_invite,
    deactivate_user,
    list_user_invites,
    list_users,
    resend_user_invite,
    revoke_user_invite,
    update_user,
)
from app.utils.i18n import tr_factory
from app.utils.qt_async import run_background_result
from app.utils.time_humanize import humanize_relative
from app.views.dialogs.user_management_ui import setup_user_management_ui
from app.widgets.workspace_dialog import WorkspaceDialogSpec, apply_workspace_dialog

logger = logging.getLogger(__name__)
_TR = tr_factory("UserManagementDialog")


class UserManagementDialog(QDialog):
    """Dialog for managing team members."""

    _refresh_btn: QPushButton
    _show_inactive: QCheckBox
    _table: QTableWidget
    _new_btn: QPushButton
    _save_btn: QPushButton
    _invite_btn: QPushButton
    _resend_invite_btn: QPushButton
    _revoke_invite_btn: QPushButton
    _deactivate_btn: QPushButton
    _close_btn: QPushButton
    _username: QLineEdit
    _password: QLineEdit
    _role: QComboBox
    _is_owner: QCheckBox
    _manager: QComboBox
    _email: QLineEdit
    _first_name: QLineEdit
    _last_name: QLineEdit
    _is_active: QCheckBox
    _can_import: QCheckBox
    _can_hard_delete: QCheckBox

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._busy = False
        self._editing_id: int | None = None
        self._users: list[dict[str, object]] = []
        self._invites_by_email: dict[str, dict[str, object]] = {}
        setup_user_management_ui(self)
        apply_workspace_dialog(
            self,
            WorkspaceDialogSpec(
                settings_key="dialogs/user_management_geometry",
                default_width=1180,
                default_height=820,
                min_width=940,
                min_height=640,
                allow_maximize=True,
            ),
        )
        self._wire_events()
        self._refresh()

    def _wire_events(self) -> None:
        self._refresh_btn.clicked.connect(self._refresh)
        self._show_inactive.stateChanged.connect(self._refresh)
        self._table.itemSelectionChanged.connect(self._on_row_selected)
        self._role.currentIndexChanged.connect(lambda _idx: self._auto_assign_single_manager())
        self._new_btn.clicked.connect(self._reset_form)
        self._save_btn.clicked.connect(self._save_user)
        self._invite_btn.clicked.connect(self._invite_user)
        self._resend_invite_btn.clicked.connect(self._resend_invite)
        self._revoke_invite_btn.clicked.connect(self._revoke_invite)
        self._deactivate_btn.clicked.connect(self._deactivate_user)
        self._close_btn.clicked.connect(self.accept)

    def _refresh(self) -> None:
        include_inactive = self._show_inactive.isChecked()
        self._set_busy(True)
        run_background_result(
            lambda: self._load_user_snapshot(include_inactive),
            self._on_refresh_success,
            self._on_refresh_error,
        )

    def _load_user_snapshot(
        self, include_inactive: bool
    ) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
        users = list_users(include_inactive=include_inactive)
        invites = list_user_invites()
        invites_by_email: dict[str, dict[str, object]] = {}
        for invite in invites:
            invite_email = str(invite.get("invite_email") or "").strip().lower()
            if invite_email:
                invites_by_email[invite_email] = invite
        return users, invites_by_email

    def _on_refresh_success(
        self, result: tuple[list[dict[str, object]], dict[str, dict[str, object]]]
    ) -> None:
        self._users, self._invites_by_email = result
        self._populate_table()
        self._refresh_manager_choices()
        self._reset_form()
        self._set_busy(False)

    def _on_refresh_error(self, _exc: Exception) -> None:
        logger.error("Failed to load users", exc_info=True)
        QMessageBox.critical(self, _TR("Error"), _TR("Failed to load users."))
        self._users = []
        self._invites_by_email = {}
        self._populate_table()
        self._refresh_manager_choices()
        self._reset_form()
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._refresh_btn.setEnabled(not busy)
        self._show_inactive.setEnabled(not busy)
        self._table.setEnabled(not busy)
        self._new_btn.setEnabled(not busy)
        self._save_btn.setEnabled(not busy)
        self._invite_btn.setEnabled(not busy)
        self._resend_invite_btn.setEnabled(not busy)
        self._revoke_invite_btn.setEnabled(not busy)
        self._deactivate_btn.setEnabled(not busy)
        self._username.setEnabled((not busy) and self._editing_id is None)
        self._password.setEnabled(not busy)
        self._role.setEnabled(not busy)
        self._is_owner.setEnabled(not busy)
        self._manager.setEnabled(not busy)
        self._email.setEnabled(not busy)
        self._first_name.setEnabled(not busy)
        self._last_name.setEnabled(not busy)
        self._is_active.setEnabled(not busy)
        self._can_import.setEnabled(not busy)
        self._can_hard_delete.setEnabled(not busy)
        self._close_btn.setEnabled(not busy)
        self._update_invite_action_state()
        try:
            self.setCursor(Qt.CursorShape.WaitCursor if busy else Qt.CursorShape.ArrowCursor)
        except Exception:
            return

    def _populate_table(self) -> None:
        self._table.setRowCount(0)
        for user in self._users:
            row = self._table.rowCount()
            self._table.insertRow(row)
            first_name = str(user.get("first_name") or "").strip()
            last_name = str(user.get("last_name") or "").strip()
            full_name = " ".join(part for part in (first_name, last_name) if part).strip()
            self._table.setItem(row, 0, self._item(user.get("username")))
            self._table.setItem(row, 1, self._item(full_name))
            self._table.setItem(row, 2, self._item(user.get("role")))
            self._table.setItem(row, 3, self._item(self._bool_label(user.get("is_owner"))))
            self._table.setItem(row, 4, self._item(self._bool_label(user.get("is_active"))))
            self._table.setItem(row, 5, self._item(self._manager_label(user.get("manager_id"))))
            self._table.setItem(row, 6, self._item(self._bool_label(user.get("can_import"))))
            self._table.setItem(row, 7, self._item(self._bool_label(user.get("can_hard_delete"))))
            self._table.setItem(row, 8, self._item(user.get("email")))
            user_id = user.get("id")
            invite_status = self._invite_status_for_user(user)
            self._table.setItem(row, 9, self._item(invite_status))
            item = self._table.item(row, 0)
            if item is not None:
                item.setData(int(Qt.ItemDataRole.UserRole), user_id)

    def _refresh_manager_choices(self) -> None:
        self._manager.blockSignals(True)
        self._manager.clear()
        self._manager.addItem(_TR("Select manager"), None)
        managers = [u for u in self._users if str(u.get("role")) == "manager"]
        for manager in managers:
            manager_id = manager.get("id")
            label = str(manager.get("username") or "")
            self._manager.addItem(label, manager_id)
        self._manager.blockSignals(False)

    def _reset_form(self) -> None:
        self._editing_id = None
        self._username.setEnabled(True)
        self._username.clear()
        self._password.clear()
        role_index = self._role.findData("agent")
        self._role.setCurrentIndex(role_index if role_index >= 0 else 0)
        self._is_owner.setChecked(False)
        self._manager.setCurrentIndex(0)
        self._email.clear()
        self._first_name.clear()
        self._last_name.clear()
        self._is_active.setChecked(True)
        self._can_import.setChecked(False)
        self._can_hard_delete.setChecked(False)
        self._auto_assign_single_manager()
        self._update_invite_action_state()

    def _on_row_selected(self) -> None:
        if self._busy:
            return
        selected = self._table.selectedItems()
        if not selected:
            return
        user_id = selected[0].data(int(Qt.ItemDataRole.UserRole))
        if not isinstance(user_id, int):
            return
        user = self._find_user(user_id)
        if not user:
            return
        self._editing_id = int(user_id)
        self._username.setEnabled(False)
        self._username.setText(str(user.get("username") or ""))
        self._password.clear()
        role = str(user.get("role") or "agent")
        role_index = self._role.findData(role)
        self._role.setCurrentIndex(role_index if role_index >= 0 else 0)
        self._is_owner.setChecked(bool(user.get("is_owner")))
        self._email.setText(str(user.get("email") or ""))
        self._first_name.setText(str(user.get("first_name") or ""))
        self._last_name.setText(str(user.get("last_name") or ""))
        self._is_active.setChecked(bool(user.get("is_active")))
        self._can_import.setChecked(bool(user.get("can_import")))
        self._can_hard_delete.setChecked(bool(user.get("can_hard_delete")))
        manager_id = user.get("manager_id")
        if manager_id is None:
            self._manager.setCurrentIndex(0)
        else:
            index = self._manager.findData(manager_id)
            self._manager.setCurrentIndex(index if index >= 0 else 0)
        self._update_invite_action_state()

    def _save_user(self) -> None:
        if self._editing_id is None:
            QMessageBox.information(
                self,
                _TR("Invite only"),
                _TR("New team members are added by invitation."),
            )
            return
        payload = self._build_payload(include_username=False)
        user_id = int(self._editing_id)
        self._set_busy(True)

        def _work() -> dict[str, object]:
            return update_user(user_id, payload)

        def _on_success(_result: dict[str, object]) -> None:
            self._refresh()

        def _on_error(exc: Exception) -> None:
            if isinstance(exc, ApiError):
                QMessageBox.warning(self, _TR("Error"), str(exc))
            else:
                logger.error("Failed to save user", exc_info=True)
                QMessageBox.critical(self, _TR("Error"), str(exc))
            self._set_busy(False)

        run_background_result(_work, _on_success, _on_error)

    def _invite_user(self) -> None:
        if self._editing_id is not None:
            QMessageBox.information(
                self,
                _TR("Info"),
                _TR("Use resend invite for a pending team member."),
            )
            return
        payload = self._build_invite_payload()
        if payload is None:
            return
        self._set_busy(True)

        def _work() -> dict[str, object]:
            return create_user_invite(payload)

        def _on_success(result: dict[str, object]) -> None:
            invite_code = str(result.get("invite_code") or "")
            invite_email = str(result.get("invite_email") or payload.get("email") or "")
            expires_at = str(result.get("expires_at") or "")
            message = (
                _TR("Invitation sent to {email}.").format(email=invite_email)
                + f"\n{_TR('Invite code')}: {invite_code}\n{_TR('Expires')}: {humanize_relative(expires_at)}"
            )
            QMessageBox.information(self, _TR("Invite"), message)
            self._refresh()

        def _on_error(exc: Exception) -> None:
            if isinstance(exc, ApiError):
                QMessageBox.warning(self, _TR("Error"), str(exc))
            else:
                logger.error("Failed to create invite", exc_info=True)
                QMessageBox.critical(self, _TR("Error"), str(exc))
            self._set_busy(False)

        run_background_result(_work, _on_success, _on_error)

    def _resend_invite(self) -> None:
        invite_id = self._selected_invite_id()
        if not invite_id:
            QMessageBox.information(self, _TR("Info"), _TR("No pending invite for this email."))
            return
        self._set_busy(True)

        def _work() -> dict[str, object]:
            return resend_user_invite(invite_id)

        def _on_success(result: dict[str, object]) -> None:
            expires_at = str(result.get("expires_at") or "")
            msg = _TR("Invite resent.") + f"\n{_TR('Expires')}: {humanize_relative(expires_at)}"
            QMessageBox.information(self, _TR("Invite"), msg)
            self._refresh()

        def _on_error(exc: Exception) -> None:
            if isinstance(exc, ApiError):
                QMessageBox.warning(self, _TR("Error"), str(exc))
            else:
                logger.error("Failed to resend invite", exc_info=True)
                QMessageBox.critical(self, _TR("Error"), str(exc))
            self._set_busy(False)

        run_background_result(_work, _on_success, _on_error)

    def _revoke_invite(self) -> None:
        invite_id = self._selected_invite_id()
        if not invite_id:
            QMessageBox.information(self, _TR("Info"), _TR("No pending invite for this email."))
            return
        confirm = QMessageBox.question(
            self,
            _TR("Confirm Revoke"),
            _TR("Revoke this pending invite?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True)

        def _work() -> dict[str, object]:
            return revoke_user_invite(invite_id)

        def _on_success(_result: dict[str, object]) -> None:
            self._refresh()

        def _on_error(exc: Exception) -> None:
            if isinstance(exc, ApiError):
                QMessageBox.warning(self, _TR("Error"), str(exc))
            else:
                logger.error("Failed to revoke invite", exc_info=True)
                QMessageBox.critical(self, _TR("Error"), str(exc))
            self._set_busy(False)

        run_background_result(_work, _on_success, _on_error)

    def _deactivate_user(self) -> None:
        if self._editing_id is None:
            QMessageBox.information(self, _TR("Info"), _TR("Select a user first."))
            return
        confirm = QMessageBox.question(
            self,
            _TR("Confirm Deactivation"),
            _TR("Deactivate this user account?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        user_id = int(self._editing_id)
        self._set_busy(True)

        def _work() -> None:
            deactivate_user(user_id)
            return None

        def _on_success(_result: None) -> None:
            self._refresh()

        def _on_error(exc: Exception) -> None:
            if isinstance(exc, ApiError):
                QMessageBox.warning(self, _TR("Error"), str(exc))
            else:
                logger.error("Failed to deactivate user", exc_info=True)
                QMessageBox.critical(self, _TR("Error"), str(exc))
            self._set_busy(False)

        run_background_result(_work, _on_success, _on_error)

    def _build_payload(self, *, include_username: bool) -> dict[str, object]:
        payload: dict[str, object] = {
            "role": str(self._role.currentData() or self._role.currentText()),
            "is_owner": self._is_owner.isChecked(),
            "email": (self._email.text() or "").strip(),
            "first_name": (self._first_name.text() or "").strip(),
            "last_name": (self._last_name.text() or "").strip(),
            "is_active": self._is_active.isChecked(),
            "can_import": self._can_import.isChecked(),
            "can_hard_delete": self._can_hard_delete.isChecked(),
        }
        if include_username:
            payload["username"] = (self._username.text() or "").strip()
        password = (self._password.text() or "").strip()
        if password:
            payload["password"] = password
        manager_id = self._manager.currentData()
        if manager_id:
            payload["manager_id"] = manager_id
        return payload

    def _build_invite_payload(self) -> dict[str, object] | None:
        role = str(self._role.currentData() or self._role.currentText())
        email = (self._email.text() or "").strip()
        first_name = (self._first_name.text() or "").strip()
        last_name = (self._last_name.text() or "").strip()
        username = (self._username.text() or "").strip()
        invite_name = " ".join(part for part in (first_name, last_name) if part).strip() or username

        if not email:
            QMessageBox.warning(self, _TR("Missing email"), _TR("Email is required."))
            return None
        manager_id = self._manager.currentData()
        if role == "agent":
            manager_ids = [u.get("id") for u in self._users if str(u.get("role")) == "manager"]
            if not manager_ids:
                QMessageBox.warning(
                    self,
                    _TR("No manager available"),
                    _TR("Create a manager first before inviting an agent."),
                )
                return None
            if manager_id is None:
                if len(manager_ids) == 1:
                    manager_id = manager_ids[0]
                    index = self._manager.findData(manager_id)
                    if index >= 0:
                        self._manager.setCurrentIndex(index)
                else:
                    QMessageBox.warning(
                        self,
                        _TR("Manager required"),
                        _TR("Select a manager for this agent invitation."),
                    )
                    return None
        elif role == "manager":
            manager_id = None

        payload: dict[str, object] = {
            "email": email,
            "role": role,
            "invite_name": invite_name,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "is_owner": False,
        }
        if manager_id is not None:
            payload["manager_id"] = int(manager_id)
        return payload

    def _find_user(self, user_id: int) -> dict[str, object] | None:
        for user in self._users:
            if user.get("id") == user_id:
                return user
        return None

    def _selected_invite_id(self) -> str | None:
        email = (self._email.text() or "").strip().lower()
        if not email and self._editing_id is not None:
            user = self._find_user(self._editing_id)
            if user:
                email = str(user.get("email") or "").strip().lower()
        if not email:
            return None
        invite = self._invites_by_email.get(email)
        if not invite:
            return None
        invite_id = invite.get("invite_id")
        return str(invite_id) if invite_id else None

    def _invite_status_for_user(self, user: dict[str, object]) -> str:
        email = str(user.get("email") or "").strip().lower()
        if not email:
            return ""
        invite = self._invites_by_email.get(email)
        if not invite:
            return ""
        expires_at = str(invite.get("expires_at") or "")
        if not expires_at:
            return _TR("Pending")
        return f"{_TR('Pending')} ({humanize_relative(expires_at)})"

    def _update_invite_action_state(self) -> None:
        has_pending = bool(self._selected_invite_id())
        enabled = not self._busy
        self._invite_btn.setEnabled(enabled and self._editing_id is None)
        self._resend_invite_btn.setEnabled(enabled and has_pending)
        self._revoke_invite_btn.setEnabled(enabled and has_pending)

    def _auto_assign_single_manager(self) -> None:
        if str(self._role.currentData() or self._role.currentText()) != "agent":
            return
        managers = [u for u in self._users if str(u.get("role")) == "manager"]
        if len(managers) != 1:
            return
        manager_id = managers[0].get("id")
        index = self._manager.findData(manager_id)
        if index >= 0:
            self._manager.setCurrentIndex(index)

    @staticmethod
    def _item(value: object) -> QTableWidgetItem:
        item = QTableWidgetItem(str(value or ""))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    @staticmethod
    def _bool_label(value: object) -> str:
        return _TR("Yes") if value else _TR("No")

    def _manager_label(self, manager_id: object) -> str:
        if manager_id is None:
            return ""
        for user in self._users:
            if user.get("id") == manager_id:
                return str(user.get("username") or manager_id)
        return _TR("Unknown")


__all__ = ["UserManagementDialog"]
