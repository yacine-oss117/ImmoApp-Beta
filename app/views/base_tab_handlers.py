"""
Shared event handler helpers for tab mixins.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import cast

from PySide6.QtCore import QEvent, QObject, QSettings, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QComboBox, QLineEdit, QTreeView, QWidget

from app.constants import APP, ORG

logger = logging.getLogger(__name__)


class BaseTabHandlersMixin:
    """Common event handler helpers for Clients/Listings tabs."""

    _column_settings_prefix: str
    _first_paint_log_label: str
    _first_paint_logged: bool
    _swap_started_at: float | None
    _model: object
    search_bar: QLineEdit
    filter_handicap: QComboBox | None
    tree: QTreeView

    def _get_first_paint_callback(self) -> Callable[[], None] | None:
        return None

    def _apply_filters(self, search: str, handicap_index: int) -> None:
        if hasattr(self._model, "set_filters"):
            try:
                self._model.set_filters(search, handicap_index)
            except TypeError:
                self._model.set_filters(search)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_F and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.search_bar.setFocus()
            self.search_bar.selectAll()
            event.accept()
        else:
            QWidget.keyPressEvent(cast(QWidget, self), event)

    def _on_column_resized(self, column: int, old_width: int, new_width: int) -> None:
        """Save column width to settings when user resizes."""
        settings = QSettings(ORG, APP)
        settings.setValue(f"{self._column_settings_prefix}/column_{column}_width", new_width)

    def _on_search_changed(self, text: str) -> None:
        """Apply search filter via SQL."""
        handicap_index = self.filter_handicap.currentIndex() if self.filter_handicap else 0
        self._apply_filters(text.strip(), handicap_index)

    def _on_handicap_filter_changed(self, index: int) -> None:
        """Apply handicap filter via SQL."""
        self._apply_filters(self.search_bar.text().strip(), index)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj == self.tree.viewport() and event.type() == QEvent.Type.Paint:
            self._log_first_paint()
        return bool(QObject.eventFilter(cast(QObject, self), obj, event))

    def _log_first_paint(self) -> None:
        if self._first_paint_logged:
            return
        self._first_paint_logged = True
        started_at = getattr(self, "_swap_started_at", None)
        if isinstance(started_at, float):
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            logger.info(
                "%s first paint: %.1fms after selection", self._first_paint_log_label, elapsed_ms
            )
        callback = self._get_first_paint_callback()
        if callback:
            callback()
