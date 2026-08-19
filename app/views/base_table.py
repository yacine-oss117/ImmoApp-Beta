"""
Base table tab behaviors shared across views.
"""

from __future__ import annotations

from typing import cast

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QTableWidget, QWidget

from app.constants import APP, ORG
from app.utils.geo import map_link_to_url
from app.utils.wa import ensure_whatsapp_open_then_open_chat
from app.widgets.common import SelectiveSortHeader


class BaseTableTab(QWidget):
    """
    Base class for tabs that display data in a table.

    Subclasses should:
    1. Define SORTABLE_COLS as a set of column indices that can be sorted
    2. Call _setup_base_table() to create the table
    3. Override refresh_table() to populate data
    """

    SORTABLE_COLS: set[int] = set()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sort_col: int | None = None
        self._sort_order = Qt.SortOrder.AscendingOrder

    def _setup_base_table(
        self,
        column_count: int,
        headers: list[str],
        column_widths: dict[int, int] | None = None,
    ) -> QTableWidget:
        """
        Create and configure the table widget with consistent styling.

        Args:
            column_count: Number of columns
            headers: List of column header labels
            column_widths: Dict mapping column index to width (optional)
        """
        self.table = QTableWidget(0, column_count)

        header = SelectiveSortHeader(Qt.Orientation.Horizontal, allowed=self.SORTABLE_COLS)
        self.table.setHorizontalHeader(header)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setSortingEnabled(True)
        header.sectionClicked.connect(self._on_header_clicked)

        self.table.verticalHeader().setDefaultSectionSize(45)

        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(header_view.ResizeMode.Interactive)
        header_view.setMinimumSectionSize(40)
        header_view.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if column_widths:
            for col, width in column_widths.items():
                self.table.setColumnWidth(col, width)

        return self.table

    def _on_header_clicked(self, col: int) -> None:
        """Handle column header click for sorting."""
        if col not in self.SORTABLE_COLS:
            return

        if self._sort_col == col:
            self._sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._sort_col = col
            self._sort_order = Qt.SortOrder.AscendingOrder

        self.table.sortItems(col, self._sort_order)

    def _phone_clicked(self) -> None:
        """Handle phone button click - opens WhatsApp chat."""
        btn = self.sender()
        if btn is None:
            return
        phone = cast(str, btn.property("phone") or "")
        if phone:
            ensure_whatsapp_open_then_open_chat(self, phone)

    def _link_clicked(self) -> None:
        """Handle link/position button click - opens URL in browser."""
        btn = self.sender()
        if btn is None:
            return
        link = cast(str, btn.property("link") or "")
        url = map_link_to_url(link)
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _get_cached_location(self) -> str:
        """Get cached location from settings (populated by time service)."""
        s = QSettings(ORG, APP)
        region = cast(str, s.value("cache/geo_region", "", str) or "")
        country = cast(str, s.value("cache/geo_country", "", str) or "")
        if region or country:
            return ", ".join(p for p in (region, country) if p)
        return ""

    def _save_column_widths(self, tab_name: str) -> None:
        """Save current column widths to persistent cache."""
        if not hasattr(self, "table"):
            return

        s = QSettings(ORG, APP)
        widths: list[int] = []
        for col in range(self.table.columnCount()):
            widths.append(self.table.columnWidth(col))
        s.setValue(f"ui/{tab_name}/column_widths", widths)

    def _load_column_widths(
        self, tab_name: str, default_widths: dict[int, int] | None = None
    ) -> None:
        """Load saved column widths from persistent cache."""
        if not hasattr(self, "table"):
            return

        s = QSettings(ORG, APP)
        widths = cast(list[int] | None, s.value(f"ui/{tab_name}/column_widths", None))

        if widths:
            for col, width in enumerate(widths):
                if col < self.table.columnCount():
                    try:
                        self.table.setColumnWidth(col, int(width))
                    except (ValueError, TypeError) as exc:
                        import logging

                        logging.getLogger(__name__).debug(
                            "Failed to restore column %d width: %s", col, exc
                        )
        elif default_widths:
            for col, width in default_widths.items():
                if col < self.table.columnCount():
                    self.table.setColumnWidth(col, width)

    def _connect_column_resize_save(self, tab_name: str) -> None:
        """Connect column resize signal to auto-save widths."""
        if not hasattr(self, "table"):
            return

        def save_widths(logical_index: int, old_size: int, new_size: int) -> None:
            self._save_column_widths(tab_name)

        self.table.horizontalHeader().sectionResized.connect(save_widths)
