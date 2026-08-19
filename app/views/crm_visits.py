"""
Visits view for the CRM tab.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.services.crm_repository import delete_visit, fetch_visits, update_visit
from app.ui.theme_manager import current_theme
from app.ui.theme_tokens import get_theme_tokens
from app.utils.i18n import tr_factory
from app.views.base import (
    QColor,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from app.widgets.user_feedback import (
    UserFacingMessage,
    build_success_message,
    map_exception_to_user_message,
)

logger = logging.getLogger(__name__)
_TR = tr_factory("CRMVisits")


class VisitsWidget(QWidget):
    """Widget for managing visits."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        feedback_cb: Callable[[UserFacingMessage, int | None], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._feedback_cb = feedback_cb

        filter_layout = QHBoxLayout()
        filter_layout.setContentsMargins(10, 8, 10, 8)
        filter_layout.setSpacing(8)
        filter_layout.addWidget(QLabel(_TR("Status:")))
        self.status_filter = QComboBox()
        self.status_filter.setAccessibleName(_TR("Visit status filter"))
        self.status_filter.addItem(_TR("All"), None)
        self.status_filter.addItem(_TR("Scheduled"), "scheduled")
        self.status_filter.addItem(_TR("Completed"), "completed")
        self.status_filter.addItem(_TR("Cancelled"), "cancelled")
        self.status_filter.currentTextChanged.connect(self.refresh)
        filter_layout.addWidget(self.status_filter)
        filter_layout.addStretch()

        self.table = QTableWidget(0, 8)
        self.table.setAccessibleName(_TR("Visits table"))
        self.table.setAccessibleDescription(_TR("Table of visits and actions."))
        self.table.setHorizontalHeaderLabels(
            [
                _TR("ID"),
                _TR("Client"),
                _TR("Property"),
                _TR("Date"),
                _TR("Time"),
                _TR("Status"),
                _TR("Notes"),
                _TR("Actions"),
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setColumnWidth(7, 232)

        filters_card = QFrame(self)
        filters_card.setProperty("immoCard", True)
        filters_card.setProperty("immoRole", "crmFilters")
        filters_card.setLayout(filter_layout)

        table_card = QFrame(self)
        table_card.setProperty("immoCard", True)
        table_card.setProperty("immoRole", "crmTable")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(10, 10, 10, 10)
        table_layout.setSpacing(8)
        table_layout.addWidget(self.table)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        layout.addWidget(filters_card)
        layout.addWidget(table_card, 1)
        self.setLayout(layout)

        self.refresh()

    def refresh(self) -> None:
        """Refresh the visits table."""
        self.table.setRowCount(0)
        tokens = get_theme_tokens(current_theme())
        status_colors = {
            "scheduled": tokens["STATUS_SCHEDULED"],
            "completed": tokens["STATUS_COMPLETED"],
            "cancelled": tokens["STATUS_CANCELLED"],
        }

        status_obj = self.status_filter.currentData()
        status = status_obj if isinstance(status_obj, str) else None

        try:
            visits = fetch_visits(status=status)
        except Exception as exc:
            logger.error("Failed to fetch visits", exc_info=True)
            self._emit_feedback(map_exception_to_user_message(exc, context="crm.visits.refresh"))
            return
        self.table.setRowCount(len(visits))

        for i, v in enumerate(visits):
            self.table.setItem(i, 0, QTableWidgetItem(str(v.id)))
            self.table.setItem(i, 1, QTableWidgetItem(v.client_id))
            self.table.setItem(i, 2, QTableWidgetItem(v.listing_id))
            self.table.setItem(i, 3, QTableWidgetItem(v.scheduled_date))
            self.table.setItem(i, 4, QTableWidgetItem(v.scheduled_time))

            status_display = {
                "scheduled": _TR("Scheduled"),
                "completed": _TR("Completed"),
                "cancelled": _TR("Cancelled"),
            }
            status_item = QTableWidgetItem(status_display.get(v.status, v.status.title()))
            status_color = status_colors.get(v.status, tokens["TEXT_MUTED"])
            status_item.setForeground(QColor(status_color))
            self.table.setItem(i, 5, status_item)

            self.table.setItem(i, 6, QTableWidgetItem(v.notes))

            actions = QWidget(self.table)
            h = QHBoxLayout(actions)
            h.setContentsMargins(4, 2, 4, 2)
            h.setSpacing(4)

            if v.status == "scheduled":
                complete_btn = QPushButton(_TR("Complete"))
                complete_btn.setAccessibleName(_TR("Complete visit"))
                complete_btn.setProperty("visit_id", v.id)
                complete_btn.setProperty("row_version", v.row_version)
                complete_btn.clicked.connect(self._complete_visit)
                complete_btn.setProperty("immoVariant", "success")
                complete_btn.setMinimumWidth(62)
                h.addWidget(complete_btn)

                cancel_btn = QPushButton(_TR("Cancel"))
                cancel_btn.setAccessibleName(_TR("Cancel visit"))
                cancel_btn.setProperty("visit_id", v.id)
                cancel_btn.setProperty("row_version", v.row_version)
                cancel_btn.clicked.connect(self._cancel_visit)
                cancel_btn.setProperty("immoVariant", "danger")
                cancel_btn.setMinimumWidth(54)
                h.addWidget(cancel_btn)

            del_btn = QPushButton(_TR("Delete"))
            del_btn.setAccessibleName(_TR("Delete visit"))
            del_btn.setProperty("visit_id", v.id)
            del_btn.clicked.connect(self._delete_visit)
            del_btn.setProperty("immoVariant", "warning")
            del_btn.setMinimumWidth(50)
            h.addWidget(del_btn)

            h.addStretch()
            self.table.setCellWidget(i, 7, actions)

    def _complete_visit(self) -> None:
        visit_id = self.sender().property("visit_id")
        row_version = self.sender().property("row_version")
        try:
            update_visit(visit_id, {"status": "completed", "row_version": row_version})
            self._emit_feedback(
                build_success_message(
                    title=_TR("Visit updated"),
                    message=_TR("Visit marked as completed."),
                ),
                auto_dismiss_ms=5000,
            )
        except Exception as exc:
            logger.error("Complete visit failed", exc_info=True)
            self._emit_feedback(map_exception_to_user_message(exc, context="crm.visits.complete"))
        self.refresh()

    def _cancel_visit(self) -> None:
        visit_id = self.sender().property("visit_id")
        row_version = self.sender().property("row_version")
        try:
            update_visit(visit_id, {"status": "cancelled", "row_version": row_version})
            self._emit_feedback(
                build_success_message(
                    title=_TR("Visit updated"),
                    message=_TR("Visit cancelled."),
                ),
                auto_dismiss_ms=5000,
            )
        except Exception as exc:
            logger.error("Cancel visit failed", exc_info=True)
            self._emit_feedback(map_exception_to_user_message(exc, context="crm.visits.cancel"))
        self.refresh()

    def _delete_visit(self) -> None:
        visit_id = self.sender().property("visit_id")
        if (
            QMessageBox.question(self, _TR("Confirm"), _TR("Delete this visit?"))
            == QMessageBox.StandardButton.Yes
        ):
            try:
                delete_visit(visit_id)
                self._emit_feedback(
                    build_success_message(
                        title=_TR("Visit removed"),
                        message=_TR("Visit deleted."),
                    ),
                    auto_dismiss_ms=5000,
                )
            except Exception as exc:
                logger.error("Delete visit failed", exc_info=True)
                self._emit_feedback(map_exception_to_user_message(exc, context="crm.visits.delete"))
            self.refresh()

    def _emit_feedback(
        self, message: UserFacingMessage, auto_dismiss_ms: int | None = None
    ) -> None:
        if self._feedback_cb is not None:
            self._feedback_cb(message, auto_dismiss_ms)
            return
        body = message.message
        if message.action_hint:
            body = f"{body} {message.action_hint}".strip()
        if message.severity in {"success", "info"}:
            QMessageBox.information(self, message.title, body)
        else:
            QMessageBox.warning(self, message.title, body)
