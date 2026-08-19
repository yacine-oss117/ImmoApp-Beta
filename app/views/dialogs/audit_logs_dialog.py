"""Activity history viewer dialog."""

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from app.services.audit_repository import count_audit_logs, fetch_audit_logs, purge_audit_logs
from app.utils.csv_safety import csv_safe
from app.utils.i18n import tr_factory
from app.utils.time_humanize import humanize_relative
from app.views.dialogs.audit_logs_ui import setup_audit_logs_ui
from app.widgets.workspace_dialog import WorkspaceDialogSpec, apply_workspace_dialog

_TR = tr_factory("AuditLogsDialog")


class AuditLogsDialog(QDialog):
    """Dialog for viewing and exporting activity history."""

    _table_filter: QComboBox
    _action_filter: QComboBox
    _actor_filter: QLineEdit
    _record_filter: QLineEdit
    _use_date_filter: QCheckBox
    _start_date: QDateEdit
    _end_date: QDateEdit
    _page_size: QSpinBox
    _apply_btn: QPushButton
    _reset_btn: QPushButton
    _export_btn: QPushButton
    _purge_btn: QPushButton
    _table: QTableWidget
    _prev_btn: QPushButton
    _next_btn: QPushButton
    _count_label: QLabel

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._offset = 0
        self._total_count = 0
        setup_audit_logs_ui(self)
        apply_workspace_dialog(
            self,
            WorkspaceDialogSpec(
                settings_key="dialogs/audit_logs_geometry",
                default_width=1180,
                default_height=820,
                min_width=920,
                min_height=620,
                allow_maximize=True,
            ),
        )
        self._refresh_logs()

    def _apply_filters(self) -> None:
        self._offset = 0
        self._refresh_logs()

    def _reset_filters(self) -> None:
        self._table_filter.setCurrentIndex(0)
        self._action_filter.setCurrentIndex(0)
        self._actor_filter.clear()
        self._record_filter.clear()
        self._use_date_filter.setChecked(False)
        self._start_date.setDate(QDate.currentDate().addMonths(-1))
        self._end_date.setDate(QDate.currentDate())
        self._page_size.setValue(200)
        self._offset = 0
        self._refresh_logs()

    def _prev_page(self) -> None:
        page_size = self._page_size.value()
        self._offset = max(0, self._offset - page_size)
        self._refresh_logs()

    def _next_page(self) -> None:
        page_size = self._page_size.value()
        if self._offset + page_size < self._total_count:
            self._offset += page_size
        self._refresh_logs()

    def _get_filters(self) -> dict[str, str | None]:
        table_obj = self._table_filter.currentData()
        table_name = table_obj if isinstance(table_obj, str) else ""

        action_obj = self._action_filter.currentData()
        action = action_obj if isinstance(action_obj, str) else ""

        actor = self._actor_filter.text().strip()
        record_id = self._record_filter.text().strip()

        start_ts = None
        end_ts = None
        if self._use_date_filter.isChecked():
            start_ts = f"{self._start_date.date().toString(Qt.DateFormat.ISODate)} 00:00:00"
            end_ts = f"{self._end_date.date().toString(Qt.DateFormat.ISODate)} 23:59:59"

        return {
            "table_name": table_name or None,
            "action": action or None,
            "actor": actor or None,
            "record_id": record_id or None,
            "start_ts": start_ts,
            "end_ts": end_ts,
        }

    def _refresh_logs(self) -> None:
        filters = self._get_filters()
        page_size = self._page_size.value()
        self._total_count = count_audit_logs(**filters)
        rows = fetch_audit_logs(limit=page_size, offset=self._offset, **filters)

        self._table.setRowCount(len(rows))
        for row_idx, log in enumerate(rows):
            self._table.setItem(row_idx, 0, QTableWidgetItem(humanize_relative(log.ts)))
            self._table.setItem(row_idx, 1, QTableWidgetItem(log.actor or ""))
            self._table.setItem(row_idx, 2, QTableWidgetItem(log.action))
            self._table.setItem(row_idx, 3, QTableWidgetItem(log.table_name))
            self._table.setItem(row_idx, 4, QTableWidgetItem(log.record_id))

        start = self._offset + 1 if rows else 0
        end = self._offset + len(rows)
        self._count_label.setText(
            _TR("Showing {start}-{end} of {total} entries").format(
                start=start, end=end, total=self._total_count
            )
        )

        self._prev_btn.setEnabled(self._offset > 0)
        self._next_btn.setEnabled(self._offset + page_size < self._total_count)

    def _export_csv(self) -> None:
        filters = self._get_filters()
        filename, _ = QFileDialog.getSaveFileName(
            self,
            _TR("Export Activity History"),
            "activity_history.csv",
            _TR("CSV Files (*.csv)"),
        )
        if not filename:
            return

        path = Path(filename)
        try:
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["timestamp", "actor", "action", "area", "item_number"])

                offset = 0
                page_size = 1000
                while True:
                    rows = fetch_audit_logs(limit=page_size, offset=offset, **filters)
                    if not rows:
                        break
                    for log in rows:
                        writer.writerow(
                            [
                                csv_safe(log.ts),
                                csv_safe(log.actor or ""),
                                csv_safe(log.action),
                                csv_safe(log.table_name),
                                csv_safe(log.record_id),
                            ]
                        )
                    offset += page_size
        except OSError as exc:
            QMessageBox.critical(
                self,
                _TR("Export Failed"),
                _TR("Failed to export history: {error}").format(error=exc),
            )
            return

        QMessageBox.information(
            self, _TR("Export Complete"), _TR("History exported to {path}").format(path=path)
        )

    def _purge_logs(self) -> None:
        reply = QMessageBox.warning(
            self,
            _TR("Clear Activity History"),
            _TR("This will delete all activity history permanently.\n\nContinue?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        deleted = purge_audit_logs()
        self._offset = 0
        self._refresh_logs()
        QMessageBox.information(
            self,
            _TR("Clear Complete"),
            _TR("Deleted {count} history entries.").format(count=deleted),
        )
