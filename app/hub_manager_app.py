"""Installed ImmoApp Hub Manager application.

This UI is intentionally a thin control surface over scripts/hub_manager.ps1.
The PowerShell layer remains the audited runtime authority; this module only
turns those actions into a user-facing app.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.hub_manager_actions import (
    ACTION_BY_KEY,
    ACTIONS,
    HubManagerAction,
    HubManagerCommandResult,
    action_output_json,
    build_hub_manager_command,
    create_owner_authorization_evidence_file,
    hidden_child_process_kwargs,
    hub_manager_output_dir,
    load_json_payload,
    resolve_hub_manager_script,
)
from app.hub_manager_owner_state import (
    OWNER_ACCOUNT_MISSING,
    OWNER_ACTIVATION_PENDING,
    HubOwnerState,
    resolve_hub_owner_state,
    unavailable_owner_state,
)
from app.hub_manager_status import normalize_hub_status
from app.hub_manager_style import (
    HUB_MANAGER_STYLESHEET,
)
from app.hub_manager_style import (
    card as _card,
)
from app.hub_manager_style import (
    configure_button as _configure_button,
)
from app.hub_manager_style import (
    field_label as _field_label,
)
from app.services.api_config import set_api_config
from app.ui.theme_manager import apply_theme

_STATUS_REFRESH_ACTIONS = {
    "start",
    "stop",
    "restart",
    "finish-hub-setup",
    "rename-hub",
    "install-runtime-artifact",
    "delete-hub-data",
    "backup-now",
}


def _status_line(label: str, ok: bool) -> str:
    return f"[OK] {label}" if ok else f"[ ] {label}"


def create_register_dialog(parent: QWidget) -> QDialog:
    from app.widgets.register_dialog import RegisterDialog

    return RegisterDialog(parent)


def create_activate_dialog(parent: QWidget) -> QDialog:
    from app.widgets.activate_dialog import ActivateDialog

    return ActivateDialog(parent)


class HubManagerWorker(QThread):
    completed = Signal(object)

    def __init__(
        self,
        action: HubManagerAction,
        *,
        script_path: Path,
        hub_base_url: str = "",
        hub_display_name: str = "",
        typed_confirmation: str = "",
        owner_authorization_evidence_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._action = action
        self._script_path = script_path
        self._hub_base_url = hub_base_url
        self._hub_display_name = hub_display_name
        self._typed_confirmation = typed_confirmation
        self._owner_authorization_evidence_path = owner_authorization_evidence_path

    def run(self) -> None:
        output_json = action_output_json(self._action.key)
        owner_authorization_evidence_json = ""
        if self._action.requires_owner_authorization:
            evidence_path = self._owner_authorization_evidence_path
            evidence_payload = load_json_payload(evidence_path) if evidence_path else None
            if (
                evidence_path is None
                or str((evidence_payload or {}).get("proof_result", "")) != "GO"
            ):
                if evidence_path is not None:
                    try:
                        evidence_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                self.completed.emit(
                    HubManagerCommandResult(
                        action=self._action.key,
                        exit_code=1,
                        stdout="",
                        stderr="",
                        output_json=evidence_path or output_json,
                        payload=evidence_payload,
                        timed_out=False,
                        error="Owner/admin authorization failed.",
                    )
                )
                return
            owner_authorization_evidence_json = str(evidence_path)
        command = build_hub_manager_command(
            action=self._action.key,
            script_path=self._script_path,
            output_json=output_json,
            hub_display_name=self._hub_display_name,
            hub_base_url=self._hub_base_url,
            use_windows_volumes=self._action.use_windows_volumes,
            confirm_runtime_artifact=self._action.key == "install-runtime-artifact",
            confirm_delete_hub_data=self._action.key == "delete-hub-data",
            typed_confirmation=self._typed_confirmation,
            owner_authorization_evidence_json=owner_authorization_evidence_json,
        )
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._action.timeout_seconds,
                check=False,
                **hidden_child_process_kwargs(),
            )
            payload = load_json_payload(output_json)
            completed = HubManagerCommandResult(
                action=self._action.key,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                output_json=output_json,
                payload=payload,
                timed_out=False,
                error="",
            )
        except subprocess.TimeoutExpired as exc:
            completed = HubManagerCommandResult(
                action=self._action.key,
                exit_code=124,
                stdout=exc.stdout if isinstance(exc.stdout, str) else "",
                stderr=exc.stderr if isinstance(exc.stderr, str) else "",
                output_json=output_json,
                payload=load_json_payload(output_json),
                timed_out=True,
                error=f"Action timed out after {self._action.timeout_seconds} seconds.",
            )
        except OSError as exc:
            completed = HubManagerCommandResult(
                action=self._action.key,
                exit_code=1,
                stdout="",
                stderr="",
                output_json=output_json,
                payload=None,
                timed_out=False,
                error=str(exc),
            )
        finally:
            if self._owner_authorization_evidence_path is not None:
                try:
                    self._owner_authorization_evidence_path.unlink(missing_ok=True)
                except OSError:
                    pass
        self.completed.emit(completed)


class HubManagerLoginDialog(QDialog):
    """Owner/admin sign-in gate for protected Hub Manager actions."""

    def __init__(self, *, hub_base_url: str, authorization_action: str) -> None:
        super().__init__()
        self._hub_base_url = hub_base_url
        self._authorization_action = authorization_action
        self.authorization_evidence_path: Path | None = None
        self.setWindowTitle("ImmoApp Hub Manager")
        self.setObjectName("hubManagerLoginDialog")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("Owner/admin sign in")
        title.setObjectName("hubManagerLoginTitle")
        title.setWordWrap(True)
        subtitle = QLabel(
            "Use an active Hub owner or admin account for protected Hub Manager actions. "
            "Owner setup happens in ImmoApp Desktop onboarding."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(10)
        self._username = QLineEdit(self)
        self._username.setObjectName("hubManagerLoginUsername")
        self._username.setPlaceholderText("Owner/admin email or username")
        self._password = QLineEdit(self)
        self._password.setObjectName("hubManagerLoginPassword")
        self._password.setPlaceholderText("Password")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Email or username", self._username)
        form.addRow("Password", self._password)
        layout.addLayout(form)

        self._status = QLabel("")
        self._status.setObjectName("hubManagerLoginStatus")
        self._status.setWordWrap(True)
        self._status.setVisible(False)
        layout.addWidget(self._status)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._cancel = _configure_button(QPushButton("Cancel"))
        self._cancel.setObjectName("hubManagerLoginCancel")
        self._login = _configure_button(QPushButton("Sign in"))
        self._login.setObjectName("hubManagerLoginButton")
        self._login.setDefault(True)
        self._cancel.clicked.connect(self.reject)
        self._login.clicked.connect(self._attempt_login)
        self._password.returnPressed.connect(self._attempt_login)
        button_row.addWidget(self._cancel)
        button_row.addWidget(self._login)
        layout.addLayout(button_row)

    def _set_status(self, message: str) -> None:
        self._status.setText(message)
        self._status.setVisible(bool(message))

    @staticmethod
    def _failure_message(reason_code: str) -> str:
        if reason_code in {
            "hub_owner_authorization_hub_state_unreadable",
            "hub_owner_authorization_hub_state_mismatch",
        }:
            return "Hub Manager cannot verify this Hub yet. Start or check the Hub, then try again."
        if reason_code == "hub_owner_authorization_user_inactive":
            return "This owner account is not active yet. Activate it from ImmoApp Desktop first."
        if reason_code == "hub_owner_authorization_role_not_allowed":
            return "This account is not allowed to manage the Hub. Sign in with an owner/admin account."
        return (
            "Owner/admin sign-in failed. Use an active Hub owner/admin account, "
            "or complete owner setup from ImmoApp Desktop onboarding."
        )

    def _attempt_login(self) -> None:
        username = self._username.text().strip()
        password = self._password.text()
        if not username:
            self._set_status("Enter the owner/admin email or username.")
            self._username.setFocus()
            return
        if not password:
            self._set_status("Enter the owner/admin password.")
            self._password.setFocus()
            return
        self._login.setEnabled(False)
        self._cancel.setEnabled(False)
        self._set_status("Checking owner/admin access...")
        QApplication.processEvents()
        try:
            evidence_path, payload = create_owner_authorization_evidence_file(
                username,
                password,
                base_url=self._hub_base_url,
                action=self._authorization_action,
            )
        except Exception:
            self._set_status(
                "Owner/admin sign-in is unavailable. Start or check the Hub, then try again."
            )
            self._password.clear()
            self._login.setEnabled(True)
            self._cancel.setEnabled(True)
            self._password.setFocus()
            return
        if str(payload.get("proof_result", "")) != "GO":
            try:
                evidence_path.unlink(missing_ok=True)
            except OSError:
                pass
            reason_code = str(payload.get("reason_code", ""))
            self._set_status(self._failure_message(reason_code))
            self._password.clear()
            self._login.setEnabled(True)
            self._cancel.setEnabled(True)
            self._password.setFocus()
            return
        self.authorization_evidence_path = evidence_path
        self.accept()

    def done(self, result: int) -> None:
        self._username.clear()
        self._password.clear()
        super().done(result)


class HubManagerWindow(QMainWindow):
    def __init__(self, initial_action: str = "") -> None:
        super().__init__()
        self._script_path = resolve_hub_manager_script()
        self._worker: HubManagerWorker | None = None
        self._buttons: list[QPushButton] = []
        self._action_buttons: dict[str, QPushButton] = {}
        self._last_status_payload: dict[str, Any] = {}
        self._owner_state: HubOwnerState = unavailable_owner_state("owner_state_not_loaded")
        self._primary_action_key = "status"
        self._secondary_action_key = "connection-details"
        self._hero_status = QLabel("Needs setup")
        self._readiness = QLabel("Needs setup")
        self._hero_title = QLabel("Office Hub")
        self._hero_subtitle = QLabel("Refresh status to see what needs attention.")
        self._hub_name = QLabel("Not loaded")
        self._front_door = QLabel("Not loaded")
        self._runtime = QLabel("Not loaded")
        self._next_action = QLabel("Refresh status to see the next step.")
        self._checklist = QLabel("Refresh status to load the setup checklist.")
        self._owner_setup_status = QLabel("Refresh status to load owner setup.")
        self._owner_setup_message = QLabel("")
        self._create_owner_button = _configure_button(QPushButton("Create owner account"))
        self._activate_owner_button = _configure_button(QPushButton("Activate owner account"))
        self._network_summary = QLabel("Refresh status to load network status.")
        self._backup_restore = QLabel("Refresh status to load backup and restore status.")
        self._danger_zone = QLabel(
            "Deleting Hub data requires agency owner/admin login evidence, Windows "
            "administrator approval, stopped runtime, and typing DELETE HUB DATA. "
            "Uninstall keeps Hub data by default."
        )
        self._last_result = QLabel("Idle")
        self._technical = QPlainTextEdit()
        self._technical.setReadOnly(True)
        self._technical.setMinimumHeight(260)
        self._technical_group = QGroupBox("Technical details")
        self._technical_toggle = _configure_button(QPushButton("Show technical details"))
        self._primary_action_button = _configure_button(
            QPushButton("Refresh status"), min_height=58
        )
        self._secondary_action_button = _configure_button(
            QPushButton("Connection details"), min_height=58
        )
        self.setWindowTitle("ImmoApp Hub Manager")
        self.setObjectName("hub-manager-window")
        self.resize(1100, 820)
        self._build_ui()
        QTimer.singleShot(200, lambda: self.run_action("status"))
        if initial_action:
            QTimer.singleShot(500, lambda: self.run_action(initial_action))

    def _build_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setObjectName("hub-main-scroll")
        scroll.setWidgetResizable(True)

        page = QWidget()
        page.setObjectName("hub-manager-root")
        page.setStyleSheet(HUB_MANAGER_STYLESHEET)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)

        hero = QFrame()
        hero.setObjectName("hub-hero")
        hero_layout = QGridLayout(hero)
        hero_layout.setContentsMargins(28, 24, 28, 24)
        hero_layout.setHorizontalSpacing(18)
        hero_layout.setVerticalSpacing(16)
        self._hero_title.setObjectName("hub-hero-title")
        self._hero_subtitle.setObjectName("hub-hero-subtitle")
        self._hero_subtitle.setWordWrap(True)
        self._hero_status.setObjectName("hub-status-badge")
        self._readiness.setObjectName("hub-status-badge")
        self._primary_action_button.setObjectName("hub-primary-action")
        self._secondary_action_button.setObjectName("hub-secondary-action")
        self._primary_action_button.clicked.connect(
            lambda: self.run_action(self._primary_action_key)
        )
        self._secondary_action_button.clicked.connect(
            lambda: self.run_action(self._secondary_action_key)
        )
        hero_layout.addWidget(self._hero_title, 0, 0, 1, 2)
        hero_layout.addWidget(self._hero_status, 0, 2, Qt.AlignmentFlag.AlignRight)
        hero_layout.addWidget(self._hero_subtitle, 1, 0, 1, 3)
        hero_layout.addWidget(self._primary_action_button, 2, 0)
        hero_layout.addWidget(self._secondary_action_button, 2, 1)
        hero_layout.setColumnStretch(0, 1)
        hero_layout.setColumnStretch(1, 1)
        hero_layout.setColumnStretch(2, 1)
        layout.addWidget(hero)

        summary, summary_layout = _card("Dashboard", object_name="hub-dashboard-card")
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        for label in (
            self._readiness,
            self._hub_name,
            self._front_door,
            self._runtime,
            self._next_action,
            self._last_result,
        ):
            label.setWordWrap(True)
        grid.addWidget(_field_label("Hub readiness"), 0, 0)
        grid.addWidget(self._readiness, 0, 1)
        grid.addWidget(_field_label("Hub name"), 1, 0)
        grid.addWidget(self._hub_name, 1, 1)
        grid.addWidget(_field_label("Connection"), 2, 0)
        grid.addWidget(self._front_door, 2, 1)
        grid.addWidget(_field_label("Hub engine"), 3, 0)
        grid.addWidget(self._runtime, 3, 1)
        grid.addWidget(_field_label("Next step"), 4, 0)
        grid.addWidget(self._next_action, 4, 1)
        grid.addWidget(_field_label("Last action"), 5, 0)
        grid.addWidget(self._last_result, 5, 1)
        grid.setColumnStretch(1, 1)
        summary_layout.addLayout(grid)
        layout.addWidget(summary)

        owner_card, owner_layout = _card("Owner setup", object_name="hub-owner-setup-card")
        self._owner_setup_status.setObjectName("hub-owner-setup-status")
        self._owner_setup_message.setObjectName("hub-owner-setup-message")
        self._owner_setup_status.setWordWrap(True)
        self._owner_setup_message.setWordWrap(True)
        owner_layout.addWidget(self._owner_setup_status)
        owner_layout.addWidget(self._owner_setup_message)
        owner_button_row = QHBoxLayout()
        self._create_owner_button.setObjectName("hubManagerCreateOwnerButton")
        self._activate_owner_button.setObjectName("hubManagerActivateOwnerButton")
        self._create_owner_button.setVisible(False)
        self._activate_owner_button.setVisible(False)
        self._create_owner_button.clicked.connect(self.open_owner_registration)
        self._activate_owner_button.clicked.connect(self.open_owner_activation)
        owner_button_row.addWidget(self._create_owner_button)
        owner_button_row.addWidget(self._activate_owner_button)
        owner_button_row.addStretch(1)
        owner_layout.addLayout(owner_button_row)
        self._buttons.extend([self._create_owner_button, self._activate_owner_button])
        layout.addWidget(owner_card)

        overview_grid = QGridLayout()
        overview_grid.setHorizontalSpacing(14)
        overview_grid.setVerticalSpacing(14)
        overview_cards = (
            ("Setup checklist", self._checklist),
            ("Network", self._network_summary),
            ("Backup and restore", self._backup_restore),
            ("Danger Zone", self._danger_zone),
        )
        for index, (title, label) in enumerate(overview_cards):
            card, card_layout = _card(title)
            card.setMinimumHeight(210)
            label.setWordWrap(True)
            card_layout.addWidget(label)
            card_layout.addStretch(1)
            overview_grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(overview_grid)

        actions_card, actions_layout = _card("Hub actions", object_name="hub-action-card")
        action_grid = QGridLayout()
        action_grid.setHorizontalSpacing(14)
        action_grid.setVerticalSpacing(14)
        group_positions = {
            "Status": (0, 0),
            "Control": (0, 1),
            "Setup": (0, 2),
            "Maintenance": (1, 0),
            "Utilities": (1, 1),
        }
        for group, position in group_positions.items():
            group_card, group_layout = _card(group)
            group_card.setMinimumWidth(230)
            for action in ACTIONS:
                if action.group != group:
                    continue
                button = _configure_button(QPushButton(action.label))
                button.setObjectName(f"hubManagerAction_{action.key}")
                button.setToolTip(action.description)
                button.clicked.connect(lambda _checked=False, key=action.key: self.run_action(key))
                group_layout.addWidget(button)
                self._buttons.append(button)
                self._action_buttons[action.key] = button
            group_layout.addStretch(1)
            action_grid.addWidget(group_card, *position)
        action_grid.setColumnStretch(0, 1)
        action_grid.setColumnStretch(1, 1)
        action_grid.setColumnStretch(2, 1)
        actions_layout.addLayout(action_grid)
        layout.addWidget(actions_card)

        self._technical_toggle.setObjectName("hub-technical-toggle")
        self._technical_toggle.clicked.connect(self.toggle_technical_details)
        layout.addWidget(self._technical_toggle)
        details_layout = QVBoxLayout(self._technical_group)
        details_layout.addWidget(self._technical)
        open_logs = _configure_button(QPushButton("Open evidence folder"))
        open_logs.clicked.connect(self.open_evidence_folder)
        details_layout.addWidget(open_logs)
        self._technical_group.setVisible(False)
        layout.addWidget(self._technical_group)
        layout.addStretch(1)

        scroll.setWidget(page)
        self.setCentralWidget(scroll)

    def set_busy(self, busy: bool) -> None:
        for button in self._buttons:
            button.setEnabled(not busy)
        self._primary_action_button.setEnabled(not busy)
        self._secondary_action_button.setEnabled(not busy)
        if busy:
            self._last_result.setText("Working...")

    def toggle_technical_details(self) -> None:
        visible = not self._technical_group.isVisible()
        self._technical_group.setVisible(visible)
        self._technical_toggle.setText(
            "Hide technical details" if visible else "Show technical details"
        )

    def run_action(self, action_key: str) -> None:
        if action_key == "owner-register":
            self.open_owner_registration()
            return
        if action_key == "owner-activate":
            self.open_owner_activation()
            return
        action = ACTION_BY_KEY.get(action_key)
        if action is None:
            QMessageBox.warning(self, "Unknown action", f"Unknown Hub Manager action: {action_key}")
            return
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, "Action running", "Wait for the current action to finish."
            )
            return
        hub_display_name = ""
        typed_confirmation = ""
        owner_authorization_evidence_path: Path | None = None
        if action.requires_owner_authorization and not self._owner_authorization_available():
            return
        if action.key == "rename-hub":
            hub_display_name, accepted = QInputDialog.getText(
                self,
                "Rename Hub",
                "Give this office Hub a simple name your team will recognize:",
            )
            if not accepted:
                return
            hub_display_name = hub_display_name.strip()
            if not hub_display_name:
                QMessageBox.warning(self, "Hub name required", "Enter a Hub name first.")
                return
        if action.key == "delete-hub-data":
            typed_confirmation, accepted = QInputDialog.getText(
                self,
                "Confirm permanent deletion",
                "Type DELETE HUB DATA to permanently delete this Hub data:",
            )
            if not accepted:
                return
            typed_confirmation = typed_confirmation.strip()
        if action.needs_confirmation:
            answer = QMessageBox.question(
                self,
                action.label,
                f"{action.description}\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if action.requires_owner_authorization:
            owner_authorization_evidence_path = self._request_owner_authorization(action.key)
            if owner_authorization_evidence_path is None:
                return
        self.set_busy(True)
        self._technical.appendPlainText(f"\n> {action.label}\n")
        self._worker = HubManagerWorker(
            action,
            script_path=self._script_path,
            hub_base_url=self._current_hub_base_url(),
            hub_display_name=hub_display_name,
            typed_confirmation=typed_confirmation,
            owner_authorization_evidence_path=owner_authorization_evidence_path,
        )
        self._worker.completed.connect(self.on_action_completed)
        self._worker.start()

    def _owner_authorization_available(self) -> bool:
        if not self._owner_state.owner_active:
            QMessageBox.information(
                self,
                "Owner account required",
                "Create and activate the Hub owner account before using protected Hub Manager actions.",
            )
            return False
        hub_base_url = self._current_hub_base_url()
        if not hub_base_url:
            QMessageBox.information(
                self,
                "Hub connection needed",
                "Start or check the Hub before signing in for a protected action.",
            )
            return False
        return True

    def _request_owner_authorization(self, action: str) -> Path | None:
        hub_base_url = self._current_hub_base_url()
        login = HubManagerLoginDialog(
            hub_base_url=hub_base_url,
            authorization_action=action,
        )
        if int(login.exec()) != int(QDialog.DialogCode.Accepted):
            return None
        return login.authorization_evidence_path

    def on_action_completed(self, result: HubManagerCommandResult) -> None:
        self.set_busy(False)
        status = "GO" if result.succeeded else "NO-GO"
        self._last_result.setText(f"{ACTION_BY_KEY[result.action].label}: {status}")
        if result.error:
            self._technical.appendPlainText(result.error)
        if result.stdout.strip():
            self._technical.appendPlainText(result.stdout.strip())
        if result.stderr.strip():
            self._technical.appendPlainText(result.stderr.strip())
        self._technical.appendPlainText(f"Evidence: {result.output_json}")
        if result.payload:
            self._technical.appendPlainText(json.dumps(result.payload, indent=2, sort_keys=True))
            if result.action == "status":
                self.update_summary(result.payload)
        if result.succeeded and result.action in _STATUS_REFRESH_ACTIONS:
            QTimer.singleShot(0, lambda: self.run_action("status"))
        if not result.succeeded and result.action not in {"status", "runtime-status"}:
            QMessageBox.warning(
                self,
                "Hub action did not complete",
                f"{ACTION_BY_KEY[result.action].label} returned {status}. "
                "The technical evidence panel has the reason.",
            )

    def _set_readiness_text(self, text: str) -> None:
        self._readiness.setText(text)
        self._hero_status.setText(text)

    def update_summary(self, payload: dict[str, Any]) -> None:
        self._last_status_payload = dict(payload)
        status = normalize_hub_status(payload)
        self._owner_state = resolve_hub_owner_state(status.front_door)
        if status.hub_name:
            self._hub_name.setText(status.hub_name)
            self._hero_title.setText(f"{status.hub_name} Hub")
        if status.front_door:
            self._front_door.setText(
                "Connection details are available. Technical values stay hidden unless support asks."
            )

        if status.ready:
            self._set_readiness_text("Ready")
            self._runtime.setText("Ready")
            self._hero_subtitle.setText(
                "Your office Hub is running. Employees can connect through the verified front door."
            )
            self._primary_action_key = "backup-now"
            self._primary_action_button.setText("Backup now")
            self._secondary_action_key = "connection-details"
            self._secondary_action_button.setText("Connection details")
            self._next_action.setText(
                "Employees can connect using Hub Manager > Connection details."
            )
        elif not status.runtime_artifact_ok:
            self._set_readiness_text("Needs setup")
            self._runtime.setText("Runtime missing")
            self._hero_subtitle.setText(
                "The Hub engine is not installed yet. Install it before employees connect."
            )
            self._primary_action_key = "install-runtime-artifact"
            self._primary_action_button.setText("Install Hub engine")
            self._secondary_action_key = "status"
            self._secondary_action_button.setText("Refresh status")
            self._next_action.setText("Install the bundled Hub engine from Hub Manager.")
        elif not status.runtime_start_ok:
            self._set_readiness_text("Needs setup")
            self._runtime.setText("Hub not started")
            self._hero_subtitle.setText(
                "The Hub engine is installed, but the Hub is not running yet."
            )
            self._primary_action_key = "start"
            self._primary_action_button.setText("Start Hub")
            self._secondary_action_key = "runtime-status"
            self._secondary_action_button.setText("Check Hub engine")
            self._next_action.setText("Start Hub, then check the employee connection.")
        elif not status.front_door_ok:
            self._set_readiness_text("Needs setup")
            self._runtime.setText("Network blocked")
            self._hero_subtitle.setText(
                "The Hub started, but the employee connection check is not passing."
            )
            self._primary_action_key = "health"
            self._primary_action_button.setText("Check connection")
            self._secondary_action_key = "firewall-status"
            self._secondary_action_button.setText("Check network access")
            self._next_action.setText("Check the employee connection and network access.")
        else:
            self._set_readiness_text("Needs setup")
            self._runtime.setText("Needs setup")
            self._hero_subtitle.setText("Refresh status and follow the setup checklist.")
            self._primary_action_key = "status"
            self._primary_action_button.setText("Refresh status")
            self._secondary_action_key = "connection-details"
            self._secondary_action_button.setText("Connection details")
            self._next_action.setText("Refresh status and follow the setup checklist.")

        owner_setup_line = self._apply_owner_setup_state(status.front_door)
        self._checklist.setText(
            "\n".join(
                [
                    owner_setup_line,
                    _status_line("Hub identity saved", status.identity_ok),
                    _status_line("Saved Hub state found", status.state_ok),
                    _status_line("Hub engine installed", status.runtime_artifact_ok),
                    _status_line("Hub started", status.runtime_start_ok),
                    _status_line("Employee connection verified", status.front_door_ok),
                    _status_line("Private-network access checked", status.firewall_ok),
                    _status_line("Backup/restore checked", status.backup_ok),
                    _status_line("LAN employee computer checked", status.lan_ok),
                ]
            )
        )
        if status.front_door_ok:
            self._network_summary.setText(
                "Employee connection is responding. Address, port, and raw proof stay in Technical details."
            )
        elif status.raw_front_door_ok:
            self._network_summary.setText(
                "A local connection answered, but the Hub must be running before employees connect."
            )
        elif status.front_door:
            self._network_summary.setText(
                "Connection details exist, but employee connection is not verified yet."
            )
        else:
            self._network_summary.setText(
                "No verified employee connection is loaded yet. Check network access and Connection details."
            )
        if status.backup_ok:
            self._backup_restore.setText(
                "Backup/restore check is present. Review Technical details before release."
            )
        else:
            self._backup_restore.setText(
                "Backup/restore check is not complete yet. Use Backup now before release."
            )

    def _apply_owner_setup_state(self, front_door_url: str) -> str:
        owner_state = self._owner_state
        self._create_owner_button.setVisible(False)
        self._activate_owner_button.setVisible(False)
        if owner_state.owner_active:
            self._owner_setup_status.setText("Owner account is active.")
            self._owner_setup_message.setText(
                "Protected actions ask for owner/admin sign-in when needed."
            )
            return _status_line("Owner account active", True)

        if owner_state.state == OWNER_ACCOUNT_MISSING:
            if owner_state.setup_available:
                self._owner_setup_status.setText("Owner account is not created yet.")
                self._owner_setup_message.setText(
                    "Create the owner account using the existing agency registration flow."
                )
                self._create_owner_button.setVisible(True)
                self._primary_action_key = "owner-register"
                self._primary_action_button.setText("Create owner account")
                self._secondary_action_key = "status"
                self._secondary_action_button.setText("Refresh status")
                self._next_action.setText("Create the owner account, then wait for approval.")
                return _status_line("Create owner account", False)
            if owner_state.reason_code == "platform_admin_email_missing":
                self._owner_setup_status.setText("Owner setup is unavailable.")
                self._owner_setup_message.setText(
                    "Platform approval email is not configured. Ask support to finish setup."
                )
                self._primary_action_key = "status"
                self._primary_action_button.setText("Refresh status")
                self._secondary_action_key = "connection-details"
                self._secondary_action_button.setText("Connection details")
                self._next_action.setText(
                    "Owner setup is unavailable until platform approval is configured."
                )
                return _status_line("Owner setup available", False)

            self._owner_setup_status.setText("Owner setup status is unavailable.")
            self._owner_setup_message.setText(
                "Start or check the Hub, then refresh status before owner setup."
            )
            if front_door_url:
                self._primary_action_key = "status"
                self._primary_action_button.setText("Refresh status")
                self._secondary_action_key = "connection-details"
                self._secondary_action_button.setText("Connection details")
            else:
                self._primary_action_key = "start"
                self._primary_action_button.setText("Start Hub")
                self._secondary_action_key = "runtime-status"
                self._secondary_action_button.setText("Check Hub engine")
            self._next_action.setText("Start or check the Hub, then refresh owner setup.")
            return _status_line("Owner setup status loaded", False)

        if owner_state.state == OWNER_ACTIVATION_PENDING and owner_state.activation_available:
            self._owner_setup_status.setText("Owner account is approved.")
            self._owner_setup_message.setText(
                "Activate the owner account with the code sent by email."
            )
            self._activate_owner_button.setVisible(True)
            self._primary_action_key = "owner-activate"
            self._primary_action_button.setText("Activate owner account")
            self._secondary_action_key = "status"
            self._secondary_action_button.setText("Refresh status")
            self._next_action.setText("Activate the owner account before protected actions.")
            return _status_line("Activate owner account", False)

        if owner_state.reason_code == "registration_approved_without_inactive_owner":
            self._owner_setup_status.setText("Owner activation is unavailable.")
            self._owner_setup_message.setText(
                "The approved owner account could not be prepared. Ask support to check setup."
            )
            self._primary_action_key = "status"
            self._primary_action_button.setText("Refresh status")
            self._secondary_action_key = "connection-details"
            self._secondary_action_button.setText("Connection details")
            self._next_action.setText("Ask support to check the approved owner account.")
            return _status_line("Owner activation available", False)

        self._owner_setup_status.setText("Owner request is waiting for approval.")
        self._owner_setup_message.setText(
            "The platform admin must approve the request before activation is available."
        )
        self._primary_action_key = "status"
        self._primary_action_button.setText("Refresh status")
        self._secondary_action_key = "connection-details"
        self._secondary_action_button.setText("Connection details")
        self._next_action.setText("Wait for platform approval, then refresh status.")
        return _status_line("Owner request approved", False)

    def _prepare_owner_setup_api(self) -> bool:
        status = normalize_hub_status(self._last_status_payload)
        if not status.front_door:
            QMessageBox.information(
                self,
                "Hub connection needed",
                "Start or check the Hub first, then try owner setup again.",
            )
            return False
        set_api_config(
            base_url=status.front_door,
            connection_source="local_hub",
            hub_display_name=status.hub_name or None,
            password="",
            token="",
        )
        return True

    def _current_hub_base_url(self) -> str:
        return normalize_hub_status(self._last_status_payload).front_door

    def open_owner_registration(self) -> None:
        if not self._prepare_owner_setup_api():
            return
        dialog = create_register_dialog(self)
        dialog.exec()
        if self._last_status_payload:
            self.update_summary(self._last_status_payload)

    def open_owner_activation(self) -> None:
        if not self._prepare_owner_setup_api():
            return
        dialog = create_activate_dialog(self)
        dialog.exec()
        if self._last_status_payload:
            self.update_summary(self._last_status_payload)

    def open_evidence_folder(self) -> None:
        QDesktopServices.openUrl(hub_manager_output_dir().as_uri())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ImmoApp Hub Manager")
    parser.add_argument("--action", choices=sorted(ACTION_BY_KEY), default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    app = QApplication(sys.argv[:1])
    apply_theme(app)
    window = HubManagerWindow(initial_action=args.action)
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
