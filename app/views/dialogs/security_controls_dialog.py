"""Security controls dialog (MFA, sessions, permissions, compliance)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.api_client import ApiError
from app.services.security_repository import (
    create_compliance_delete,
    create_compliance_export,
    get_compliance_job,
    get_mfa_status,
    list_permission_grants,
    list_sessions,
    permissions_matrix,
    revoke_all_sessions,
    revoke_session,
    step_up_auth,
)
from app.utils.i18n import tr_factory
from app.utils.qt_async import run_background_result
from app.widgets.workspace_dialog import WorkspaceDialogSpec, apply_workspace_dialog

_TR = tr_factory("SecurityControlsDialog")
logger = logging.getLogger(__name__)


class SecurityControlsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_TR("Security Controls"))
        self.setObjectName("securityControlsDialog")
        apply_workspace_dialog(
            self,
            WorkspaceDialogSpec(
                settings_key="dialogs/security_controls_geometry",
                default_width=1180,
                default_height=840,
                min_width=920,
                min_height=700,
                allow_maximize=True,
            ),
        )
        self._step_up_token: str = ""
        self._pending_requests = 0
        self._build_ui()
        self._refresh_all()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        step_group = QFormLayout()
        self._password = QLineEdit(self)
        self._password.setObjectName("securityControlsPasswordInput")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._mfa_code = QLineEdit(self)
        self._mfa_code.setObjectName("securityControlsMfaInput")
        self._step_token = QLineEdit(self)
        self._step_token.setObjectName("securityControlsStepUpToken")
        self._step_token.setReadOnly(True)
        issue_step_up = QPushButton(_TR("Issue Step-Up Token"), self)
        issue_step_up.setObjectName("securityControlsIssueStepUpButton")
        issue_step_up.clicked.connect(self._issue_step_up_token)
        step_group.addRow(_TR("Password"), self._password)
        step_group.addRow(_TR("MFA Code (if enabled)"), self._mfa_code)
        step_group.addRow(issue_step_up)
        step_group.addRow(_TR("Step-Up Token"), self._step_token)
        root.addLayout(step_group)

        mfa_row = QHBoxLayout()
        self._mfa_status = QLabel("-", self)
        self._mfa_status.setObjectName("securityControlsMfaStatus")
        mfa_refresh = QPushButton(_TR("Refresh MFA Status"), self)
        mfa_refresh.setObjectName("securityControlsRefreshMfaButton")
        mfa_refresh.clicked.connect(self._refresh_mfa_status)
        mfa_row.addWidget(QLabel(_TR("MFA Status:"), self))
        mfa_row.addWidget(self._mfa_status, 1)
        mfa_row.addWidget(mfa_refresh)
        root.addLayout(mfa_row)

        sessions_row = QHBoxLayout()
        sessions_row.addWidget(QLabel(_TR("Sessions"), self))
        sessions_refresh = QPushButton(_TR("Refresh Sessions"), self)
        sessions_refresh.setObjectName("securityControlsRefreshSessionsButton")
        sessions_refresh.clicked.connect(self._refresh_sessions)
        sessions_row.addWidget(sessions_refresh)
        revoke_selected = QPushButton(_TR("Revoke Selected"), self)
        revoke_selected.setObjectName("securityControlsRevokeSelectedButton")
        revoke_selected.clicked.connect(self._revoke_selected_session)
        sessions_row.addWidget(revoke_selected)
        self._keep_current = QCheckBox(_TR("Keep current on revoke-all"), self)
        self._keep_current.setObjectName("securityControlsKeepCurrentCheckbox")
        self._keep_current.setChecked(True)
        sessions_row.addWidget(self._keep_current)
        revoke_all = QPushButton(_TR("Revoke All"), self)
        revoke_all.setObjectName("securityControlsRevokeAllButton")
        revoke_all.clicked.connect(self._revoke_all_sessions)
        sessions_row.addWidget(revoke_all)
        sessions_row.addStretch()
        root.addLayout(sessions_row)

        self._sessions = QTableWidget(self)
        self._sessions.setObjectName("securityControlsSessionsTable")
        self._sessions.setColumnCount(5)
        self._sessions.setHorizontalHeaderLabels(
            [_TR("Session ID"), _TR("Current"), _TR("IP"), _TR("Last Seen"), _TR("Status")]
        )
        self._sessions.horizontalHeader().setStretchLastSection(True)
        self._sessions.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._sessions.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._sessions.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self._sessions)

        perm_row = QHBoxLayout()
        perm_row.addWidget(QLabel(_TR("Permissions"), self))
        perm_refresh = QPushButton(_TR("Refresh Permission Data"), self)
        perm_refresh.setObjectName("securityControlsRefreshPermissionsButton")
        perm_refresh.clicked.connect(self._refresh_permissions)
        perm_row.addWidget(perm_refresh)
        root.addLayout(perm_row)

        self._permissions_view = QTextEdit(self)
        self._permissions_view.setObjectName("securityControlsPermissionsView")
        self._permissions_view.setReadOnly(True)
        root.addWidget(self._permissions_view)

        compliance_form = QFormLayout()
        self._target_user_id = QLineEdit(self)
        self._target_user_id.setObjectName("securityControlsTargetUserInput")
        self._compliance_reason = QLineEdit(self)
        self._compliance_reason.setObjectName("securityControlsComplianceReasonInput")
        self._job_id = QLineEdit(self)
        self._job_id.setObjectName("securityControlsJobIdInput")
        self._job_status = QTextEdit(self)
        self._job_status.setObjectName("securityControlsJobStatusView")
        self._job_status.setReadOnly(True)
        compliance_buttons = QHBoxLayout()
        export_btn = QPushButton(_TR("Create Export Job"), self)
        export_btn.setObjectName("securityControlsCreateExportButton")
        export_btn.clicked.connect(self._create_export_job)
        delete_btn = QPushButton(_TR("Create Delete Job"), self)
        delete_btn.setObjectName("securityControlsCreateDeleteButton")
        delete_btn.clicked.connect(self._create_delete_job)
        status_btn = QPushButton(_TR("Refresh Job Status"), self)
        status_btn.setObjectName("securityControlsRefreshJobButton")
        status_btn.clicked.connect(self._refresh_job_status)
        compliance_buttons.addWidget(export_btn)
        compliance_buttons.addWidget(delete_btn)
        compliance_buttons.addWidget(status_btn)
        compliance_buttons.addStretch()
        compliance_form.addRow(_TR("Target User ID"), self._target_user_id)
        compliance_form.addRow(_TR("Reason"), self._compliance_reason)
        compliance_form.addRow(compliance_buttons)
        compliance_form.addRow(_TR("Job ID"), self._job_id)
        compliance_form.addRow(self._job_status)
        root.addLayout(compliance_form)

        close_btn = QPushButton(_TR("Close"), self)
        close_btn.setObjectName("securityControlsCloseButton")
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _refresh_all(self) -> None:
        self._refresh_mfa_status()
        self._refresh_sessions()
        self._refresh_permissions()

    def _set_busy(self, busy: bool) -> None:
        self.setEnabled(not busy)
        self.setCursor(Qt.CursorShape.WaitCursor if busy else Qt.CursorShape.ArrowCursor)

    def _begin_async(self) -> None:
        self._pending_requests += 1
        self._set_busy(True)

    def _end_async(self) -> None:
        self._pending_requests = max(0, self._pending_requests - 1)
        self._set_busy(self._pending_requests > 0)

    def _run_async(
        self,
        work: Callable[[], object],
        on_success: Callable[[object], None],
    ) -> None:
        self._begin_async()

        def _success(result: object) -> None:
            try:
                on_success(result)
            except Exception:
                logger.warning("Security controls async success callback failed", exc_info=True)
            finally:
                self._end_async()

        def _error(exc: Exception) -> None:
            try:
                self._show_error(exc)
            finally:
                self._end_async()

        run_background_result(work, _success, _error)

    def _issue_step_up_token(self) -> None:
        def _work() -> object:
            return step_up_auth(
                password=self._password.text().strip(),
                mfa_code=self._mfa_code.text().strip() or None,
            )

        def _on_success(result: object) -> None:
            payload = result if isinstance(result, dict) else {}
            token = str(payload.get("step_up_token") or "")
            self._step_up_token = token
            self._step_token.setText(token)

        self._run_async(_work, _on_success)

    def _refresh_mfa_status(self) -> None:
        def _work() -> object:
            return get_mfa_status()

        def _on_success(result: object) -> None:
            payload = result if isinstance(result, dict) else {}
            self._mfa_status.setText(json.dumps(payload, ensure_ascii=False))

        self._run_async(_work, _on_success)

    def _refresh_sessions(self) -> None:
        def _work() -> object:
            return list_sessions()

        def _on_success(result: object) -> None:
            rows = result if isinstance(result, list) else []
            self._sessions.setRowCount(0)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                idx = self._sessions.rowCount()
                self._sessions.insertRow(idx)
                session_id = str(row.get("session_id") or "")
                status_text = str(row.get("revoke_reason") or "active")
                values = [
                    session_id,
                    "yes" if row.get("is_current") else "no",
                    str(row.get("source_ip") or ""),
                    str(row.get("last_seen_at") or ""),
                    status_text,
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if col == 0:
                        item.setData(Qt.ItemDataRole.UserRole, session_id)
                    self._sessions.setItem(idx, col, item)

        self._run_async(_work, _on_success)

    def _selected_session_id(self) -> str | None:
        items = self._sessions.selectedItems()
        if not items:
            return None
        return str(items[0].data(Qt.ItemDataRole.UserRole) or "")

    def _revoke_selected_session(self) -> None:
        sid = self._selected_session_id()
        if not sid:
            QMessageBox.information(self, _TR("Info"), _TR("Select a session first."))
            return
        if not self._step_up_token:
            QMessageBox.warning(self, _TR("Missing Step-Up"), _TR("Issue a step-up token first."))
            return

        def _work() -> object:
            revoke_session(session_id=sid, step_up_token=self._step_up_token)
            return None

        def _on_success(_result: object) -> None:
            self._refresh_sessions()

        self._run_async(_work, _on_success)

    def _revoke_all_sessions(self) -> None:
        if not self._step_up_token:
            QMessageBox.warning(self, _TR("Missing Step-Up"), _TR("Issue a step-up token first."))
            return

        def _work() -> object:
            return revoke_all_sessions(
                keep_current=self._keep_current.isChecked(),
                step_up_token=self._step_up_token,
            )

        def _on_success(_result: object) -> None:
            self._refresh_sessions()

        self._run_async(_work, _on_success)

    def _refresh_permissions(self) -> None:
        def _work() -> object:
            return {
                "matrix": permissions_matrix(),
                "grants": list_permission_grants(),
            }

        def _on_success(result: object) -> None:
            payload = result if isinstance(result, dict) else {"matrix": [], "grants": []}
            self._permissions_view.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False))

        self._run_async(_work, _on_success)

    def _create_export_job(self) -> None:
        self._create_compliance_job(is_delete=False)

    def _create_delete_job(self) -> None:
        self._create_compliance_job(is_delete=True)

    def _create_compliance_job(self, *, is_delete: bool) -> None:
        if not self._step_up_token:
            QMessageBox.warning(self, _TR("Missing Step-Up"), _TR("Issue a step-up token first."))
            return
        try:
            user_id = int((self._target_user_id.text() or "").strip())
        except ValueError:
            QMessageBox.warning(
                self, _TR("Invalid User"), _TR("Target user id must be an integer.")
            )
            return
        reason = (self._compliance_reason.text() or "").strip()

        def _work() -> object:
            if is_delete:
                return create_compliance_delete(
                    user_id=user_id,
                    reason=reason,
                    step_up_token=self._step_up_token,
                )
            return create_compliance_export(
                user_id=user_id,
                reason=reason,
                step_up_token=self._step_up_token,
            )

        def _on_success(result: object) -> None:
            payload = result if isinstance(result, dict) else {}
            self._job_id.setText(str(payload.get("job_id") or ""))
            self._job_status.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False))

        self._run_async(_work, _on_success)

    def _refresh_job_status(self) -> None:
        job_id = (self._job_id.text() or "").strip()
        if not job_id:
            QMessageBox.information(self, _TR("Info"), _TR("Enter or create a job id first."))
            return

        def _work() -> object:
            return get_compliance_job(job_id=job_id)

        def _on_success(result: object) -> None:
            payload = result if isinstance(result, dict) else {}
            self._job_status.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False))

        self._run_async(_work, _on_success)

    def _show_error(self, exc: Exception) -> None:
        if isinstance(exc, ApiError):
            QMessageBox.warning(self, _TR("Error"), str(exc))
            return
        QMessageBox.critical(self, _TR("Error"), str(exc))


__all__ = ["SecurityControlsDialog"]
