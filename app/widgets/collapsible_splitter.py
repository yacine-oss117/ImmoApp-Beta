"""
Splitter with a chevron handle to collapse/expand a side panel.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import QSplitter, QSplitterHandle, QToolButton, QWidget

from app.constants import APP, ORG


class ChevronSplitterHandle(QSplitterHandle):
    """Splitter handle that renders a chevron toggle."""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self._button = QToolButton(self)
        self._button.setAutoRaise(True)
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.setFixedSize(16, 16)
        self._button.clicked.connect(self._on_toggle)
        self._button.setToolTip("Show/Hide map panel")

    def _on_toggle(self) -> None:
        splitter = self.splitter()
        if isinstance(splitter, CollapsibleSplitter):
            splitter.toggle_panel()

    def update_arrow(self) -> None:
        splitter = self.splitter()
        if not isinstance(splitter, CollapsibleSplitter):
            return
        self._button.setArrowType(splitter.arrow_for_state())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        x = (self.width() - self._button.width()) // 2
        y = (self.height() - self._button.height()) // 2
        self._button.move(max(0, x), max(0, y))


class CollapsibleSplitter(QSplitter):
    """Splitter with a collapsible panel and persisted state."""

    def __init__(
        self,
        orientation: Qt.Orientation,
        parent: QWidget | None = None,
        *,
        settings_key: str,
        panel_index: int = 1,
        collapsed_default: bool = False,
    ) -> None:
        super().__init__(orientation, parent)
        self._settings_key = settings_key
        self._panel_index = panel_index
        self._collapsed_default = collapsed_default
        self._last_sizes: list[int] | None = None
        self._state_applied = False
        self.setHandleWidth(16)
        self.splitterMoved.connect(self._on_splitter_moved)

    def createHandle(self) -> QSplitterHandle:
        handle = ChevronSplitterHandle(self.orientation(), self)
        handle.update_arrow()
        return handle

    def showEvent(self, event: QShowEvent) -> None:
        if not self._state_applied:
            self.apply_persisted_state()
            self._state_applied = True
        super().showEvent(event)

    def apply_persisted_state(self) -> None:
        sizes = self._load_sizes()
        collapsed = self._load_collapsed()
        if sizes:
            self._last_sizes = sizes
        if collapsed is None:
            collapsed = self._collapsed_default

        if collapsed:
            self._collapse_panel()
        elif sizes:
            self.setSizes(sizes)
        else:
            self.setSizes(self._default_sizes())

        self._update_handle()
        self._save_state()

    def toggle_panel(self) -> None:
        if self.is_panel_collapsed():
            sizes = self._last_sizes or self._default_sizes()
            self.setSizes(sizes)
        else:
            self._last_sizes = self.sizes()
            self._collapse_panel()
        self._update_handle()
        self._save_state()

    def is_panel_collapsed(self) -> bool:
        sizes = [int(size) for size in self.sizes()]
        if self._panel_index >= len(sizes):
            return False
        return sizes[self._panel_index] <= 0

    def arrow_for_state(self) -> Qt.ArrowType:
        collapsed = self.is_panel_collapsed()
        on_trailing = self._panel_index >= self.count() - 1
        if self.orientation() == Qt.Orientation.Horizontal:
            if on_trailing:
                return Qt.ArrowType.RightArrow if collapsed else Qt.ArrowType.LeftArrow
            return Qt.ArrowType.LeftArrow if collapsed else Qt.ArrowType.RightArrow
        if on_trailing:
            return Qt.ArrowType.DownArrow if collapsed else Qt.ArrowType.UpArrow
        return Qt.ArrowType.UpArrow if collapsed else Qt.ArrowType.DownArrow

    def _collapse_panel(self) -> None:
        sizes = self.sizes()
        if not sizes:
            return
        total = sum(sizes)
        new_sizes = [0 for _ in sizes]
        main_index = 0 if self._panel_index != 0 else 1
        if main_index < len(new_sizes):
            new_sizes[main_index] = total
        self.setSizes(new_sizes)

    def _default_sizes(self) -> list[int]:
        sizes = self.sizes()
        total = sum(sizes)
        if total <= 0:
            total = 1000
        panel = min(360, max(220, int(total * 0.28)))
        main = max(200, total - panel)
        if self._panel_index == 0:
            return [panel, total - panel]
        if self._panel_index == 1 and len(sizes) == 2:
            return [main, total - main]
        result = [0 for _ in range(max(2, len(sizes)))]
        result[0] = total - panel
        result[self._panel_index] = panel
        return result

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        sizes = self.sizes()
        if self._panel_index < len(sizes) and sizes[self._panel_index] > 0:
            self._last_sizes = sizes
        self._save_state()
        self._update_handle()

    def _update_handle(self) -> None:
        handle = self.handle(1)
        if isinstance(handle, ChevronSplitterHandle):
            handle.update_arrow()

    def _save_state(self) -> None:
        settings = QSettings(ORG, APP)
        settings.setValue(f"{self._settings_key}/sizes", self.sizes())
        settings.setValue(f"{self._settings_key}/collapsed", self.is_panel_collapsed())

    def _load_sizes(self) -> list[int] | None:
        settings = QSettings(ORG, APP)
        raw = settings.value(f"{self._settings_key}/sizes", None)
        if not isinstance(raw, list):
            return None
        sizes: list[int] = []
        for item in raw:
            try:
                sizes.append(int(item))
            except (TypeError, ValueError):
                return None
        if len(sizes) != self.count():
            return None
        return sizes

    def _load_collapsed(self) -> bool | None:
        settings = QSettings(ORG, APP)
        raw = settings.value(f"{self._settings_key}/collapsed", None)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            value = str(raw)
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return None
