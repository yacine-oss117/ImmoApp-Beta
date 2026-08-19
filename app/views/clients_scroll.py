"""Smart dual-scroll helpers for the Clients workspace.

The Clients page has two independent vertical scroll domains:
- an outer page scroll that brings the records workspace into full view;
- the records tree's own scroll bar for browsing client rows.

Mouse-wheel input is handed from the outer page to the table only after the
records card reaches its focused position. Scrolling back to the first table
row hands the wheel back to the outer page so the editor naturally returns.
Both scroll bars remain real, draggable Qt scroll bars for accessibility and
for users who prefer mouse dragging over the wheel.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QResizeEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QFrame, QScrollArea, QScrollBar, QTreeView, QWidget


class ClientsPageScrollArea(QScrollArea):
    """Outer Clients-page scroll area with table-focus handoff."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._records_widget: QWidget | None = None
        self._table_view: QTreeView | None = None
        self.setObjectName("clientsPageScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setProperty("immoRole", "clientsPageScroll")
        self.setProperty("immoScrollRole", "compact")
        self.verticalScrollBar().setSingleStep(28)
        self.verticalScrollBar().setProperty("immoScrollRole", "compact")
        self.horizontalScrollBar().setProperty("immoScrollRole", "compact")

    def set_records_widget(self, widget: QWidget) -> None:
        """Register the records card that should fill the page at scroll end."""
        self._records_widget = widget
        QTimer.singleShot(0, self._sync_records_height)

    def set_table_view(self, table: QTreeView) -> None:
        """Register the inner records table used once the page is focused."""
        self._table_view = table

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        keep_focused = self.records_are_focused() if self._records_widget is not None else False
        super().resizeEvent(event)
        self._sync_records_height()
        if keep_focused:
            QTimer.singleShot(0, self.scroll_to_records)

    def _sync_records_height(self) -> None:
        records = self._records_widget
        if records is None:
            return
        # The content layout has a 12 px bottom margin. Subtracting it makes
        # the outer scroll maximum line up with the records card's top edge,
        # which gives the table the full Clients-tab viewport when focused.
        target = max(360, self.viewport().height() - 12)
        if records.minimumHeight() != target:
            records.setMinimumHeight(target)
            records.updateGeometry()

    def records_focus_value(self) -> int:
        """Return the outer-scroll value that aligns the records card at top."""
        records = self._records_widget
        content = self.widget()
        bar = self.verticalScrollBar()
        if records is None or content is None:
            return bar.maximum()
        try:
            y = records.mapTo(content, QPoint(0, 0)).y()
        except RuntimeError:
            return bar.maximum()
        return max(bar.minimum(), min(int(y), bar.maximum()))

    def records_are_focused(self, *, tolerance: int = 3) -> bool:
        bar = self.verticalScrollBar()
        return bar.value() >= self.records_focus_value() - tolerance

    def scroll_to_records(self) -> None:
        """Bring the client records workspace into full-screen focus."""
        self.verticalScrollBar().setValue(self.records_focus_value())

    def scroll_to_editor(self) -> None:
        """Return the Clients page to the editor at the top."""
        self.verticalScrollBar().setValue(self.verticalScrollBar().minimum())

    @staticmethod
    def _wheel_distance(event: QWheelEvent, bar: QScrollBar) -> int:
        """Translate a wheel/trackpad event into a scrollbar delta."""
        pixel_y = event.pixelDelta().y()
        if pixel_y:
            return -int(pixel_y)

        angle_y = event.angleDelta().y()
        if not angle_y:
            return 0
        app = QApplication.instance()
        lines = app.wheelScrollLines() if isinstance(app, QApplication) else 3
        single_step = max(8, int(bar.singleStep() or 20))
        return int(-(angle_y / 120.0) * max(1, lines) * single_step)

    @classmethod
    def move_bar_from_wheel(cls, bar: QScrollBar, event: QWheelEvent) -> bool:
        distance = cls._wheel_distance(event, bar)
        if not distance:
            return False
        before = bar.value()
        bar.setValue(before + distance)
        return bar.value() != before

    def consume_outer_wheel(self, event: QWheelEvent) -> bool:
        """Move the outer page from a wheel event and report whether it moved."""
        return self.move_bar_from_wheel(self.verticalScrollBar(), event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt API
        # When the records card is already the dominant workspace, wheel
        # events over its toolbar/empty areas should continue scrolling rows.
        table = self._table_view
        delta_y = event.pixelDelta().y() or event.angleDelta().y()
        if table is not None and self.records_are_focused() and delta_y:
            table_bar = table.verticalScrollBar()
            if delta_y < 0 and table_bar.value() < table_bar.maximum():
                if self.move_bar_from_wheel(table_bar, event):
                    event.accept()
                    return
            if delta_y > 0 and table_bar.value() > table_bar.minimum():
                if self.move_bar_from_wheel(table_bar, event):
                    event.accept()
                    return
        super().wheelEvent(event)


class ClientsTreeView(QTreeView):
    """Records tree that hands wheel input to/from the outer Clients page."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._outer_scroll: ClientsPageScrollArea | None = None
        self.setProperty("immoScrollRole", "compact")
        self.verticalScrollBar().setProperty("immoScrollRole", "compact")
        self.horizontalScrollBar().setProperty("immoScrollRole", "compact")

    def set_outer_scroll_area(self, scroll: ClientsPageScrollArea) -> None:
        self._outer_scroll = scroll

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt API
        outer = self._outer_scroll
        delta_y = event.pixelDelta().y() or event.angleDelta().y()
        if outer is None or not delta_y:
            super().wheelEvent(event)
            return

        # Before table focus, the wheel always belongs to the page. This
        # prevents a half-visible table from scrolling internally while the
        # editor remains stuck above it.
        if not outer.records_are_focused():
            outer.consume_outer_wheel(event)
            event.accept()
            return

        table_bar = self.verticalScrollBar()
        # At the first row, an upward gesture naturally reveals the editor.
        if delta_y > 0 and table_bar.value() <= table_bar.minimum():
            if outer.consume_outer_wheel(event):
                event.accept()
                return

        super().wheelEvent(event)
