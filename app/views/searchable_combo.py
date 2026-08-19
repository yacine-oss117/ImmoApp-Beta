"""
Searchable combo box with prefix filtering.
"""

from __future__ import annotations

import logging
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from typing import cast

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QComboBox, QCompleter, QLineEdit, QWidget

from app.utils.i18n import tr_factory

logger = logging.getLogger(__name__)
_TR = tr_factory("SearchableComboBox")


class SearchableComboBox(QComboBox):
    """
    A QComboBox that:
    - Shows full dropdown when clicked ANYWHERE (not just the arrow)
    - Allows typing to filter items case-insensitively
    - Matches from the beginning of the text (prefix search)
    """

    _MAX_FILTER_RESULTS = 500

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMaxVisibleItems(15)

        self._all_items: list[str] = []
        self._sorted_keys: list[str] = []
        self._sorted_items: list[str] = []

        self._completer = QCompleter(self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setFilterMode(Qt.MatchFlag.MatchStartsWith)
        self.setCompleter(self._completer)

        line_edit = cast(QLineEdit, self.lineEdit())
        line_edit.textEdited.connect(self._on_text_edited)
        line_edit.installEventFilter(self)
        self.destroyed.connect(self._cleanup)

    def _cleanup(self) -> None:
        """Remove event filters and disconnect signals on destroy."""
        line_edit = self.lineEdit()
        if line_edit is None:
            return
        try:
            line_edit.removeEventFilter(self)
        except RuntimeError:
            logger.debug("SearchableComboBox removeEventFilter failed", exc_info=True)
        try:
            line_edit.textEdited.disconnect(self._on_text_edited)
        except (RuntimeError, TypeError):
            logger.debug("SearchableComboBox textEdited disconnect failed", exc_info=True)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Show popup when clicking on the line edit area."""
        if obj == self.lineEdit() and event.type() == QEvent.Type.MouseButtonPress:
            self.showPopup()
            return False
        return bool(super().eventFilter(obj, event))

    def setItems(self, items: Sequence[str]) -> None:
        """Set the list of items and store them for filtering."""
        self._all_items = list(items)
        self._sorted_keys = []
        self._sorted_items = []
        if self._all_items:
            pairs = sorted((item.lower(), item) for item in self._all_items)
            self._sorted_keys = [key for key, _item in pairs]
            self._sorted_items = [item for _key, item in pairs]
        self.clear()
        self.addItems(self._all_items)

        from PySide6.QtCore import QStringListModel

        self._completer.setModel(QStringListModel(self._all_items))

    def _prefix_matches(self, query: str) -> list[str]:
        """Return prefix matches using binary search (fast for large lists)."""
        if not query:
            return self._all_items
        if not self._sorted_keys:
            return []
        start = bisect_left(self._sorted_keys, query)
        end = bisect_right(self._sorted_keys, f"{query}\uffff")
        matches = self._sorted_items[start:end]
        if len(matches) > self._MAX_FILTER_RESULTS:
            self.setToolTip(
                _TR("Showing first {count} results. Refine search.").format(
                    count=self._MAX_FILTER_RESULTS
                )
            )
            return matches[: self._MAX_FILTER_RESULTS]
        self.setToolTip("")
        return matches

    def _on_text_edited(self, text: str) -> None:
        """Filter items based on typed text (prefix, case-insensitive)."""
        if not text:
            self.clear()
            self.addItems(self._all_items)
            self.setToolTip("")
            return

        text_lower = text.lower()
        filtered = self._prefix_matches(text_lower)

        self.blockSignals(True)
        self.clear()
        self.addItems(filtered)
        self.setEditText(text)
        self.blockSignals(False)

        if filtered:
            self.showPopup()

    def showPopup(self) -> None:
        """Show dropdown. If no search text, show all items."""
        line_edit = cast(QLineEdit, self.lineEdit())
        current_text = line_edit.text()
        if not current_text or current_text in self._all_items:
            if self.count() != len(self._all_items):
                self.blockSignals(True)
                self.clear()
                self.addItems(self._all_items)
                self.setEditText(current_text)
                self.blockSignals(False)
        super().showPopup()

    def getCurrentId(self) -> str:
        """Extract the ID from the current selection (assumes format '[N] ID | ...')."""
        text = str(self.currentText())
        if not text:
            return ""
        parts = text.split("]", 1)
        if len(parts) == 2:
            tail = parts[1]
            if "|" in tail:
                return tail.split("|", 1)[0].strip()
            return tail.strip()

        if "|" in text:
            return text.split("|", 1)[0].strip()
        return text.strip()
