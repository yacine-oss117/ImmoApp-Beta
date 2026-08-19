"""
Prefix Search ComboBox - Autocomplete with strict prefix matching.

Features:
- Typing filters items by prefix
- Case and accent insensitive
- Optional: allow adding new items (for customizable lists)
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtWidgets import QComboBox, QWidget

from app.services.locations import normalize_for_lookup
from app.utils.i18n import tr_factory
from app.widgets.prefix_combo_index import PrefixSearchIndex
from app.widgets.prefix_validator import PrefixValidator

logger = logging.getLogger(__name__)
_TR = tr_factory("PrefixComboBox")


class PrefixComboBox(QComboBox):
    """
    A ComboBox with prefix search filtering.

    Args:
        force_selection: If True, only allows items from list (wilayas)
        allow_add: If True, allows adding new items (locations/communes)
        on_add_callback: Function to call when new item is added
    """

    textChanged = Signal(str)
    itemAdded = Signal(str)  # Emits when new item is added

    _MAX_FILTER_RESULTS = 500
    _ADD_ITEM_TAG = "add_item"

    def __init__(
        self, parent: QWidget | None = None, force_selection: bool = True, allow_add: bool = False
    ) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMaxVisibleItems(15)

        self._all_items: list[str] = []
        self._force_selection = force_selection
        self._allow_add = allow_add
        self._on_add_callback: Callable[[str], str | bool | None] | None = None
        self._validator: PrefixValidator | None = None
        self._index = PrefixSearchIndex()

        line_edit = self.lineEdit()
        if line_edit is None:
            return
        # Connect text changes to filter
        line_edit.textEdited.connect(self._on_text_edited)
        self.currentTextChanged.connect(self._on_selection_changed)

        # Handle Enter key for adding new items
        line_edit.returnPressed.connect(self._on_enter_pressed)

        # Click on line edit shows popup
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
            logger.debug("PrefixComboBox removeEventFilter failed", exc_info=True)
        try:
            line_edit.textEdited.disconnect(self._on_text_edited)
        except (RuntimeError, TypeError):
            logger.debug("PrefixComboBox textEdited disconnect failed", exc_info=True)
        try:
            line_edit.returnPressed.disconnect(self._on_enter_pressed)
        except (RuntimeError, TypeError):
            logger.debug("PrefixComboBox returnPressed disconnect failed", exc_info=True)
        try:
            self.currentTextChanged.disconnect(self._on_selection_changed)
        except (RuntimeError, TypeError):
            logger.debug("PrefixComboBox currentTextChanged disconnect failed", exc_info=True)

    @staticmethod
    def _add_item_label(text: str) -> str:
        return _TR('Add "{text}"').format(text=text)

    @staticmethod
    def _is_add_item(data: object) -> bool:
        return (
            isinstance(data, tuple) and len(data) == 2 and data[0] == PrefixComboBox._ADD_ITEM_TAG
        )

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Show popup when clicking on the line edit area."""
        if obj == self.lineEdit() and event.type() == QEvent.Type.MouseButtonPress:
            self.showPopup()
            return False
        return bool(super().eventFilter(obj, event))

    def setItems(self, items: list[str]) -> None:
        """Set the list of items."""
        self._all_items = list(items)
        self._rebuild_index()
        self.blockSignals(True)
        self.clear()
        self.addItems(self._all_items)
        self.setCurrentIndex(-1)
        line_edit = self.lineEdit()
        if line_edit is None:
            return
        line_edit.clear()
        self.blockSignals(False)

        # Create validator
        self._validator = PrefixValidator(self._all_items, allow_new=self._allow_add)
        line_edit.setValidator(self._validator)

    def setOnAddCallback(self, callback: Callable[[str], str | bool | None] | None) -> None:
        """Set callback for when new item is added."""
        self._on_add_callback = callback

    def _rebuild_index(self) -> None:
        self._index.rebuild(self._all_items)
        if self._validator:
            self._validator.set_items(self._all_items)

    def _prefix_matches(self, normalized_query: str) -> list[str]:
        """Return prefix matches using binary search."""
        matches = self._index.prefix_matches(normalized_query, self._MAX_FILTER_RESULTS)
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
        """Filter items based on typed text using prefix matching."""
        if not text:
            self.blockSignals(True)
            self.clear()
            self.addItems(self._all_items)
            self.setCurrentIndex(-1)
            line_edit = self.lineEdit()
            if line_edit is None:
                return
            line_edit.setText("")
            self.blockSignals(False)
            self.showPopup()
            return

        filtered = self._prefix_matches(normalize_for_lookup(text))

        self.blockSignals(True)
        self.clear()

        if filtered:
            self.addItems(filtered)
        elif self._allow_add:
            self.addItem(self._add_item_label(text), (self._ADD_ITEM_TAG, text))
        else:
            self.addItems(self._all_items)

        self.setEditText(text)
        self.blockSignals(False)

        if filtered or self._allow_add:
            self.showPopup()

    def _on_enter_pressed(self) -> None:
        """Handle Enter key - add new item if allowed."""
        line_edit = self.lineEdit()
        if line_edit is None:
            return
        text = line_edit.text().strip()
        if not text:
            return

        if text in self._all_items:
            return

        if self._allow_add:
            self._add_new_item(text)

    def _add_new_item(self, text: str) -> None:
        """Add a new item to the list."""
        if text in self._all_items:
            return

        if self._on_add_callback:
            result = self._on_add_callback(text)
            if not result:
                return
            if isinstance(result, str):
                text = result

        if text not in self._all_items:
            self._all_items.append(text)
            self._all_items.sort()
        self._rebuild_index()

        self.blockSignals(True)
        self.clear()
        self.addItems(self._all_items)
        index = self.findText(text)
        if index >= 0:
            self.setCurrentIndex(index)
        else:
            self.setEditText(text)
        line_edit = self.lineEdit()
        if line_edit is not None:
            line_edit.setText(text)
        self.blockSignals(False)

        self.itemAdded.emit(text)

    def _on_selection_changed(self, text: str) -> None:
        """Emit change signal when a valid selection is made."""
        data = self.currentData()
        if self._is_add_item(data):
            _tag, new_text = data
            self._add_new_item(str(new_text))
            return

        if text in self._all_items:
            self.textChanged.emit(text)

    def showPopup(self) -> None:
        """Show dropdown."""
        line_edit = self.lineEdit()
        if line_edit is None:
            return
        current_text = line_edit.text()
        if not current_text:
            if self.count() != len(self._all_items):
                self.blockSignals(True)
                self.clear()
                self.addItems(self._all_items)
                self.blockSignals(False)
        super().showPopup()

    def value(self) -> str:
        """Get the current selected value."""
        if self._is_add_item(self.currentData()):
            return ""
        text = self.currentText()
        return text if text in self._all_items else ""

    def setValue(self, value: str) -> None:
        """Set the current value."""
        if value in self._all_items:
            self.setCurrentText(value)
            return

        mapped = self._index.resolve(value)
        if mapped:
            self.setCurrentText(mapped)
            return

        self.setCurrentIndex(-1)
        line_edit = self.lineEdit()
        if line_edit is not None:
            line_edit.clear()

    def resolve_text(self, text: str) -> str:
        """Resolve raw text to a valid item (add if allowed)."""
        text = (text or "").strip()
        if not text:
            return ""
        if text not in self._all_items and self._allow_add:
            self._add_new_item(text)
        else:
            self.setValue(text)
        return self.value()
