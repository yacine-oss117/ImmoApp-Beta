from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHeaderView, QTableWidgetItem, QWidget

SortableKey = int | float | str


class KeyItem(QTableWidgetItem):
    """Table item that sorts by a hidden key, falling back to text."""

    def __init__(self, text: str = "", sort_key: SortableKey | None = None) -> None:
        super().__init__(text)
        self._key = sort_key

    def key(self) -> SortableKey | None:
        return getattr(self, "_key", None)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        # Get keys for comparison
        a = self.key()
        b = other.key() if isinstance(other, KeyItem) else None

        # If both have valid keys, compare them
        if a is not None and b is not None:
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return a < b
            if isinstance(a, str) and isinstance(b, str):
                return a < b

        # If one has a key and other doesn't, key comes first
        if a is not None and b is None:
            return True
        if a is None and b is not None:
            return False

        # Both None or incompatible - compare by text (no recursion)
        return str(self.text()) < str(other.text())


class SelectiveSortHeader(QHeaderView):
    """Horizontal header that allows sorting only on a whitelist of columns.

    Usage:
        header = SelectiveSortHeader(Qt.Horizontal, allowed={0, 2, 5})
        table.setHorizontalHeader(header)
        table.setSortingEnabled(True)
    """

    def __init__(
        self,
        orientation: Qt.Orientation,
        allowed: Iterable[int] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(orientation, parent)
        self.setSectionsClickable(True)
        self._allowed: set[int] | None = set(allowed) if allowed is not None else None

    def setAllowed(self, cols: Iterable[int] | None) -> None:
        self._allowed = set(cols) if cols is not None else None

    def allowed(self) -> set[int] | None:
        return self._allowed

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Intercept clicks on disallowed sections to prevent sorting.
        if event and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position() if hasattr(event, "position") else event.pos()
            if isinstance(pos, QPoint):
                x = pos.x()
            else:
                # Qt6 API: position() returns QPointF
                x = int(pos.x())
            section = self.logicalIndexAt(x)
            if self._allowed is not None and section not in self._allowed:
                # Ignore click; do not pass to base => no sort action
                return
        super().mousePressEvent(event)
