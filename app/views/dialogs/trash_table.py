"""Reusable trash table widgets for soft-deleted records."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial
from typing import Generic, Protocol, TypeVar

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.utils.i18n import tr_factory

logger = logging.getLogger(__name__)
_TR = tr_factory("TrashDialog")


class TrashItem(Protocol):
    """Protocol for items that can appear in the trash."""

    id: int
    deleted_at: str


TTrash = TypeVar("TTrash", bound=TrashItem)


class TrashTable(QWidget, Generic[TTrash]):
    """Reusable table widget for soft-deleted items."""

    def __init__(
        self,
        *,
        headers: list[str],
        fetch_items: Callable[[int, int], list[TTrash]],
        render_row: Callable[[TTrash], list[str]],
        restore_item: Callable[[int], None],
        purge_item: Callable[[int], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._fetch_items = fetch_items
        self._render_row = render_row
        self._restore_item = restore_item
        self._purge_item = purge_item
        self._limit = 200
        self._offset = 0

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self._count_label = QLabel(_TR("0 items"), self)
        refresh_btn = QPushButton(_TR("Refresh"), self)
        refresh_btn.setToolTip(_TR("Reload deleted items"))
        refresh_btn.setAccessibleName(_TR("Refresh trash table"))
        refresh_btn.clicked.connect(self.refresh)
        load_more_btn = QPushButton(_TR("Load More"), self)
        load_more_btn.setToolTip(_TR("Load more deleted items"))
        load_more_btn.setAccessibleName(_TR("Load more trash items"))
        load_more_btn.clicked.connect(self.load_more)

        toolbar.addWidget(self._count_label)
        toolbar.addStretch()
        toolbar.addWidget(refresh_btn)
        toolbar.addWidget(load_more_btn)
        layout.addLayout(toolbar)

        self._table = QTableWidget(0, len(headers) + 1, self)
        self._table.setAccessibleName(_TR("Trash table"))
        self._table.setAccessibleDescription(_TR("Table of deleted records and actions."))
        self._table.setHorizontalHeaderLabels(headers + [_TR("Actions")])
        self._table.verticalHeader().setDefaultSectionSize(38)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, 1)

        self.setTabOrder(refresh_btn, load_more_btn)
        self.setTabOrder(load_more_btn, self._table)

        self.refresh()

    def refresh(self) -> None:
        """Reload items from the database."""
        self._offset = 0
        self._table.setRowCount(0)
        self._load_page(reset=True)

    def load_more(self) -> None:
        """Load the next page of deleted items."""
        self._offset += self._limit
        self._load_page(reset=False)

    def _load_page(self, *, reset: bool) -> None:
        try:
            items = self._fetch_items(self._limit, self._offset)
        except Exception:
            logger.error("Failed to load trash items", exc_info=True)
            QMessageBox.warning(self, _TR("Error"), _TR("Failed to load deleted items."))
            return

        if reset:
            self._table.setRowCount(0)

        for item in items:
            self._append_row(item)

        total = self._table.rowCount()
        self._count_label.setText(_TR("{count} items").format(count=total))

    def _append_row(self, item: TTrash) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        values = self._render_row(item)
        for col, value in enumerate(values):
            cell = QTableWidgetItem(value)
            cell.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, col, cell)

        actions = QWidget(self._table)
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)

        restore_btn = QPushButton(_TR("Restore"), actions)
        restore_btn.setToolTip(_TR("Restore this item"))
        restore_btn.setAccessibleName(_TR("Restore item"))
        restore_btn.clicked.connect(partial(self._restore, item.id))

        purge_btn = QPushButton(_TR("Purge"), actions)
        purge_btn.setToolTip(_TR("Permanently delete this item"))
        purge_btn.setAccessibleName(_TR("Purge item"))
        purge_btn.clicked.connect(partial(self._purge, item.id))

        actions_layout.addWidget(restore_btn)
        actions_layout.addWidget(purge_btn)
        actions_layout.addStretch()

        self._table.setCellWidget(row, len(values), actions)

    def _restore(self, item_id: int, checked: bool = False) -> None:
        _ = checked
        confirm = QMessageBox.question(
            self,
            _TR("Restore Item"),
            _TR("Restore this item and its linked data?"),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self._restore_item(item_id)
        except Exception:
            logger.error("Failed to restore item %s", item_id, exc_info=True)
            QMessageBox.warning(self, _TR("Error"), _TR("Failed to restore item."))
            return
        self.refresh()

    def _purge(self, item_id: int, checked: bool = False) -> None:
        _ = checked
        confirm = QMessageBox.warning(
            self,
            _TR("Permanently Delete"),
            _TR("This will permanently delete the item and cannot be undone.\nContinue?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self._purge_item(item_id)
        except Exception:
            logger.error("Failed to purge item %s", item_id, exc_info=True)
            QMessageBox.warning(self, _TR("Error"), _TR("Failed to purge item."))
            return
        self.refresh()
