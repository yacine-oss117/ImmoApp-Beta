"""UI builder for the activity history dialog."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.audit_schema import AUDIT_TABLES
from app.utils.i18n import tr_factory

_TR = tr_factory("AuditLogsDialog")

if TYPE_CHECKING:
    from app.views.dialogs.audit_logs_dialog import AuditLogsDialog


def setup_audit_logs_ui(dialog: AuditLogsDialog) -> None:
    """Build UI controls and attach them to the dialog."""
    dialog.setWindowTitle(_TR("Activity History"))
    dialog.setMinimumSize(900, 600)
    dialog.setModal(True)

    layout = QVBoxLayout(dialog)

    filter_group = QWidget(dialog)
    filter_layout = QFormLayout(filter_group)

    dialog._table_filter = QComboBox(dialog)
    dialog._table_filter.addItem(_TR("All"), "")
    for name in sorted(AUDIT_TABLES.keys()):
        dialog._table_filter.addItem(name, name)
    dialog._table_filter.setAccessibleName(_TR("Area filter"))
    dialog._table_filter.setAccessibleDescription(_TR("Filter history by area."))
    filter_layout.addRow(_TR("Area:"), dialog._table_filter)

    dialog._action_filter = QComboBox(dialog)
    dialog._action_filter.addItem(_TR("All"), "")
    dialog._action_filter.addItem(_TR("INSERT"), "INSERT")
    dialog._action_filter.addItem(_TR("UPDATE"), "UPDATE")
    dialog._action_filter.addItem(_TR("DELETE"), "DELETE")
    dialog._action_filter.setAccessibleName(_TR("Action filter"))
    dialog._action_filter.setAccessibleDescription(_TR("Filter history by action type."))
    filter_layout.addRow(_TR("Action:"), dialog._action_filter)

    dialog._actor_filter = QLineEdit(dialog)
    dialog._actor_filter.setPlaceholderText(_TR("Team member"))
    dialog._actor_filter.setAccessibleName(_TR("Team member filter"))
    dialog._actor_filter.setAccessibleDescription(_TR("Filter history by team member."))
    filter_layout.addRow(_TR("Team member:"), dialog._actor_filter)

    dialog._record_filter = QLineEdit(dialog)
    dialog._record_filter.setPlaceholderText(_TR("Item number"))
    dialog._record_filter.setAccessibleName(_TR("Item number filter"))
    dialog._record_filter.setAccessibleDescription(_TR("Filter history by item number."))
    filter_layout.addRow(_TR("Item number:"), dialog._record_filter)

    dialog._use_date_filter = QCheckBox(_TR("Filter by date range"), dialog)
    dialog._use_date_filter.setAccessibleName(_TR("Date range filter toggle"))
    filter_layout.addRow("", dialog._use_date_filter)

    dialog._start_date = QDateEdit(dialog)
    dialog._start_date.setCalendarPopup(True)
    dialog._start_date.setDate(QDate.currentDate().addMonths(-1))
    dialog._start_date.setAccessibleName(_TR("Start date"))
    dialog._end_date = QDateEdit(dialog)
    dialog._end_date.setCalendarPopup(True)
    dialog._end_date.setDate(QDate.currentDate())
    dialog._end_date.setAccessibleName(_TR("End date"))

    date_row = QHBoxLayout()
    date_row.addWidget(dialog._start_date)
    date_row.addWidget(QLabel(_TR("to")))
    date_row.addWidget(dialog._end_date)
    filter_layout.addRow(_TR("Date Range:"), date_row)

    dialog._page_size = QSpinBox(dialog)
    dialog._page_size.setRange(50, 5000)
    dialog._page_size.setValue(200)
    dialog._page_size.setAccessibleName(_TR("Page size"))
    filter_layout.addRow(_TR("Page size:"), dialog._page_size)

    layout.addWidget(filter_group)

    controls = QHBoxLayout()
    dialog._apply_btn = QPushButton(_TR("Apply Filters"))
    dialog._apply_btn.clicked.connect(dialog._apply_filters)
    dialog._apply_btn.setAccessibleName(_TR("Apply filters"))
    dialog._reset_btn = QPushButton(_TR("Reset"))
    dialog._reset_btn.clicked.connect(dialog._reset_filters)
    dialog._reset_btn.setAccessibleName(_TR("Reset filters"))
    dialog._export_btn = QPushButton(_TR("Export CSV"))
    dialog._export_btn.clicked.connect(dialog._export_csv)
    dialog._export_btn.setAccessibleName(_TR("Export CSV"))
    dialog._purge_btn = QPushButton(_TR("Clear History"))
    dialog._purge_btn.setToolTip(_TR("Delete all activity history"))
    dialog._purge_btn.clicked.connect(dialog._purge_logs)
    dialog._purge_btn.setAccessibleName(_TR("Purge logs"))
    controls.addWidget(dialog._apply_btn)
    controls.addWidget(dialog._reset_btn)
    controls.addStretch()
    controls.addWidget(dialog._purge_btn)
    controls.addWidget(dialog._export_btn)
    layout.addLayout(controls)

    dialog._table = QTableWidget(dialog)
    dialog._table.setAccessibleName(_TR("Activity history table"))
    dialog._table.setAccessibleDescription(_TR("Activity history entries."))
    dialog._table.setColumnCount(5)
    dialog._table.setHorizontalHeaderLabels(
        [_TR("When"), _TR("Team member"), _TR("Action"), _TR("Area"), _TR("Item number")]
    )
    dialog._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    dialog._table.setAlternatingRowColors(True)
    layout.addWidget(dialog._table, 1)

    footer = QHBoxLayout()
    dialog._prev_btn = QPushButton(_TR("Prev"))
    dialog._prev_btn.clicked.connect(dialog._prev_page)
    dialog._next_btn = QPushButton(_TR("Next"))
    dialog._next_btn.clicked.connect(dialog._next_page)
    dialog._count_label = QLabel("")
    dialog._prev_btn.setAccessibleName(_TR("Previous page"))
    dialog._next_btn.setAccessibleName(_TR("Next page"))
    dialog._count_label.setAccessibleName(_TR("Pagination status"))
    footer.addWidget(dialog._prev_btn)
    footer.addWidget(dialog._next_btn)
    footer.addStretch()
    footer.addWidget(dialog._count_label)
    layout.addLayout(footer)

    dialog.setTabOrder(dialog._table_filter, dialog._action_filter)
    dialog.setTabOrder(dialog._action_filter, dialog._actor_filter)
    dialog.setTabOrder(dialog._actor_filter, dialog._record_filter)
    dialog.setTabOrder(dialog._record_filter, dialog._use_date_filter)
    dialog.setTabOrder(dialog._use_date_filter, dialog._start_date)
    dialog.setTabOrder(dialog._start_date, dialog._end_date)
    dialog.setTabOrder(dialog._end_date, dialog._page_size)
    dialog.setTabOrder(dialog._page_size, dialog._apply_btn)
    dialog.setTabOrder(dialog._apply_btn, dialog._reset_btn)
    dialog.setTabOrder(dialog._reset_btn, dialog._purge_btn)
    dialog.setTabOrder(dialog._purge_btn, dialog._export_btn)
    dialog.setTabOrder(dialog._export_btn, dialog._prev_btn)
    dialog.setTabOrder(dialog._prev_btn, dialog._next_btn)
    dialog.setTabOrder(dialog._next_btn, dialog._table)
