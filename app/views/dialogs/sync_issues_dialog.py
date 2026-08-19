"""Review and resolve offline sync issues conservatively."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.offline_account_scope import get_active_account_scope
from app.services.offline_conflicts import list_conflicts, remove_conflict
from app.services.offline_op_log import discard_operation, get_operation, update_operation_status
from app.services.offline_projection import mark_projection_status
from app.services.upload_queue import discard_media_upload, retry_media_upload
from app.utils.i18n import tr_factory
from app.widgets.workspace_dialog import WorkspaceDialogSpec, apply_workspace_dialog

_TR = tr_factory("SyncIssuesDialog")


class SyncIssuesDialog(QDialog):
    """Show offline operations that require explicit user review."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scope = get_active_account_scope()
        self.setWindowTitle(_TR("Sync Issues"))
        self.setModal(True)
        apply_workspace_dialog(
            self,
            WorkspaceDialogSpec(
                settings_key="dialogs/sync_issues_geometry",
                default_width=980,
                default_height=680,
                min_width=760,
                min_height=420,
                allow_maximize=True,
            ),
        )

        layout = QVBoxLayout(self)
        self._summary = QLabel("", self)
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self._table = QTableWidget(self)
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(
            [
                _TR("Entity"),
                _TR("Reason"),
                _TR("Message"),
                _TR("Created"),
                _TR("Local ID"),
            ]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._update_action_state)
        header = self._table.horizontalHeader()
        if header is not None:
            header.setStretchLastSection(True)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._refresh_btn = QPushButton(_TR("Refresh"), self)
        self._retry_btn = QPushButton(_TR("Retry"), self)
        self._discard_btn = QPushButton(_TR("Discard"), self)
        close_btn = QPushButton(_TR("Close"), self)
        self._refresh_btn.clicked.connect(self._refresh)
        self._retry_btn.clicked.connect(self._retry_selected)
        self._discard_btn.clicked.connect(self._discard_selected)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._refresh_btn)
        btn_row.addWidget(self._retry_btn)
        btn_row.addWidget(self._discard_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._refresh()

    def _selected_op_id(self) -> str | None:
        selected = self._table.selectedItems()
        if not selected:
            return None
        item = selected[0]
        raw = item.data(Qt.ItemDataRole.UserRole)
        return str(raw) if raw else None

    def _update_action_state(self) -> None:
        enabled = self._selected_op_id() is not None
        self._retry_btn.setEnabled(enabled)
        self._discard_btn.setEnabled(enabled)

    def _refresh(self) -> None:
        if self._scope is None:
            self._table.setRowCount(0)
            self._summary.setText(_TR("Sign in to review sync issues for this account."))
            self._update_action_state()
            return
        conflicts = list_conflicts(scope=self._scope)
        self._table.setRowCount(0)
        self._summary.setText(
            _TR(
                "Items listed here could not be synced automatically. Retry after fixing the problem, or discard the local change."
            )
        )
        for conflict in conflicts:
            row = self._table.rowCount()
            self._table.insertRow(row)
            values = [
                str(conflict.entity_type),
                str(conflict.reason_code),
                str(conflict.message),
                str(conflict.created_at),
                str(conflict.local_id),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, conflict.op_id)
                self._table.setItem(row, column, item)
        self._update_action_state()

    def _retry_selected(self) -> None:
        op_id = self._selected_op_id()
        if not op_id or self._scope is None:
            return
        if op_id.startswith("media:"):
            queue_id = op_id.split(":", 1)[1]
            retry_media_upload(queue_id, scope=self._scope)
            remove_conflict(op_id, scope=self._scope)
            self._refresh()
            return
        op = get_operation(op_id, scope=self._scope)
        remove_conflict(op_id, scope=self._scope)
        if op is not None:
            update_operation_status(op_id, "pending", scope=self._scope)
            if op.entity_type != "generic":
                mark_projection_status(
                    op.entity_type,
                    op.local_id,
                    sync_status="pending",
                    sync_error="",
                    scope=self._scope,
                )
        self._refresh()

    def _discard_selected(self) -> None:
        op_id = self._selected_op_id()
        if not op_id or self._scope is None:
            return
        confirm = QMessageBox.question(
            self,
            _TR("Discard local change"),
            _TR("Discard this local change and remove it from the sync queue?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        remove_conflict(op_id, scope=self._scope)
        if op_id.startswith("media:"):
            queue_id = op_id.split(":", 1)[1]
            discard_media_upload(queue_id, scope=self._scope)
            self._refresh()
            return
        discard_operation(op_id, scope=self._scope)
        self._refresh()


__all__ = ["SyncIssuesDialog"]
