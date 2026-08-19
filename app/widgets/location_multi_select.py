"""
Location Multi-Select Widget.

Chips/tags input with autocomplete. Values are stored as a semicolon-separated
string for compatibility.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.utils.common import split_location_tokens
from app.utils.i18n import tr_factory
from app.utils.qt_async import is_qt_object_alive
from app.widgets.location_chip import LocationChip
from app.widgets.location_events import LOCATION_EVENTS
from app.widgets.location_flow_layout import FlowLayout
from app.widgets.prefix_combo import PrefixComboBox

logger = logging.getLogger(__name__)
_TR = tr_factory("LocationMultiSelect")
_CHIP_AREA_MIN_HEIGHT = 38
_CHIP_AREA_MAX_HEIGHT = 120


class LocationMultiSelect(QWidget):
    """Multi-select for locations using a searchable combobox + chips."""

    valueChanged = Signal()
    itemsChanged = Signal()

    def __init__(self, parent: QWidget | None = None, allow_add: bool = True) -> None:
        super().__init__(parent)
        self._locations: list[str] = []

        self._combo = PrefixComboBox(force_selection=False, allow_add=allow_add)
        self._combo.setAccessibleName(_TR("Location selector"))
        combo_edit = self._combo.lineEdit()
        if combo_edit is not None:
            combo_edit.setPlaceholderText(_TR("Type commune and press Enter/Add"))
            combo_edit.returnPressed.connect(self._add_current)
        self._combo.itemAdded.connect(self._on_combo_item_added)
        self._combo.textChanged.connect(self._on_combo_selection_changed)
        LOCATION_EVENTS.locationsChanged.connect(self.itemsChanged.emit)

        self._add_btn = QPushButton(_TR("Add"), self)
        self._add_btn.setProperty("immoVariant", "secondary")
        self._add_btn.setMaximumWidth(60)
        self._add_btn.clicked.connect(self._add_current)
        self._add_btn.setAccessibleName(_TR("Add location"))

        self._chips_container = QWidget(self)
        self._chips_layout = FlowLayout(self._chips_container)

        self._chips_scroll = QScrollArea(self)
        self._chips_scroll.setWidgetResizable(True)
        self._chips_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._chips_scroll.setWidget(self._chips_container)
        self._chips_scroll.setMinimumHeight(0)
        self._chips_scroll.setMaximumHeight(0)
        self._chips_scroll.setVisible(False)

        self._clear_btn = QPushButton(_TR("Clear"), self)
        self._clear_btn.setProperty("immoVariant", "ghost")
        self._clear_btn.setMaximumWidth(70)
        self._clear_btn.clicked.connect(self.clear)
        self._clear_btn.setVisible(False)
        self._clear_btn.setAccessibleName(_TR("Clear locations"))

        self._status_label = QLabel("", self)
        self._status_label.setObjectName("locationStatusLabel")
        self._status_label.setProperty("immoState", "muted")
        self._status_label.setVisible(False)

        self._retry_btn = QPushButton(_TR("Retry"), self)
        self._retry_btn.setProperty("immoVariant", "ghost")
        self._retry_btn.setMaximumWidth(80)
        self._retry_btn.setVisible(False)
        self._retry_callback: Callable[[], None] | None = None
        self._retry_btn.clicked.connect(self._on_retry_clicked)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self._combo, 1)
        top.addWidget(self._add_btn)

        chips_row = QHBoxLayout()
        chips_row.setContentsMargins(0, 0, 0, 0)
        chips_row.addWidget(self._chips_scroll, 1)
        chips_row.addWidget(self._clear_btn)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(6)
        status_row.addWidget(self._status_label, 1)
        status_row.addWidget(self._retry_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(top)
        layout.addLayout(chips_row)
        layout.addLayout(status_row)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._refresh_chips()
        self.destroyed.connect(self._cleanup)

    def _cleanup(self) -> None:
        """Disconnect global events and input handlers on destroy."""
        try:
            LOCATION_EVENTS.locationsChanged.disconnect(self.itemsChanged.emit)
        except (RuntimeError, TypeError):
            logger.debug("LocationMultiSelect locationsChanged disconnect failed", exc_info=True)
        try:
            self._combo.itemAdded.disconnect(self._on_combo_item_added)
        except (RuntimeError, TypeError):
            logger.debug("LocationMultiSelect itemAdded disconnect failed", exc_info=True)
        try:
            self._combo.textChanged.disconnect(self._on_combo_selection_changed)
        except (RuntimeError, TypeError):
            logger.debug("LocationMultiSelect textChanged disconnect failed", exc_info=True)
        combo_edit = self._combo.lineEdit()
        if combo_edit is not None:
            try:
                combo_edit.returnPressed.disconnect(self._add_current)
            except (RuntimeError, TypeError):
                logger.debug("LocationMultiSelect returnPressed disconnect failed", exc_info=True)

    def _on_combo_item_added(self, text: str) -> None:
        if text:
            self._add_location(text)
            self._combo.setCurrentIndex(-1)
            combo_edit = self._combo.lineEdit()
            if combo_edit is not None:
                combo_edit.clear()
        self.itemsChanged.emit()

    def _on_combo_selection_changed(self, text: str) -> None:
        if not text:
            return
        if self._add_location(text):
            self._combo.setCurrentIndex(-1)
            combo_edit = self._combo.lineEdit()
            if combo_edit is not None:
                combo_edit.clear()
            self.itemsChanged.emit()

    def set_async_state(
        self,
        state: str,
        message: str,
        *,
        retry_callback: Callable[[], None] | None = None,
    ) -> None:
        if not self._async_status_controls_alive():
            return
        normalized = state.strip().lower()
        if normalized not in {"muted", "loading", "error", "success"}:
            normalized = "muted"
        self._status_label.setProperty("immoState", normalized)
        self._status_label.setText(message.strip())
        self._retry_callback = retry_callback
        show_status = bool(message.strip())
        self._status_label.setVisible(show_status)
        self._retry_btn.setVisible(
            show_status and normalized == "error" and retry_callback is not None
        )
        self._refresh_status_style()

    def clear_async_state(self) -> None:
        if not self._async_status_controls_alive():
            return
        self._status_label.setText("")
        self._status_label.setVisible(False)
        self._status_label.setProperty("immoState", "muted")
        self._retry_callback = None
        self._retry_btn.setVisible(False)
        self._refresh_status_style()

    def setItems(self, items: list[str]) -> None:
        self._combo.setItems(items)

    def set_automation_prefix(self, prefix: str) -> None:
        normalized = prefix.strip()
        if not normalized:
            return
        self._combo.setObjectName(f"{normalized}Combo")
        combo_edit = self._combo.lineEdit()
        if combo_edit is not None:
            combo_edit.setObjectName(f"{normalized}Input")
        self._add_btn.setObjectName(f"{normalized}AddButton")
        self._clear_btn.setObjectName(f"{normalized}ClearButton")
        self._chips_scroll.setObjectName(f"{normalized}Chips")
        self._retry_btn.setObjectName(f"{normalized}RetryButton")

    def setOnAddCallback(self, callback: Callable[[str], str | bool | None] | None) -> None:
        self._combo.setOnAddCallback(callback)

    def value(self) -> str:
        return "; ".join(self._locations)

    def setValue(self, value: str) -> None:
        tokens = self._parse_tokens(value)
        self._locations = []
        for loc in tokens:
            if loc not in self._locations:
                self._locations.append(loc)
        self._refresh_chips()

    def clear(self) -> None:
        if not self._locations:
            self._combo.setCurrentIndex(-1)
            combo_edit = self._combo.lineEdit()
            if combo_edit is not None:
                combo_edit.clear()
            return
        self._locations = []
        self._refresh_chips()
        self._combo.setCurrentIndex(-1)
        combo_edit = self._combo.lineEdit()
        if combo_edit is not None:
            combo_edit.clear()
        self.valueChanged.emit()

    def _on_retry_clicked(self) -> None:
        if self._retry_callback is None:
            return
        try:
            self._retry_callback()
        except Exception:
            logger.warning("Retry callback for locations failed", exc_info=True)

    def _add_current(self) -> None:
        combo_edit = self._combo.lineEdit()
        if combo_edit is None:
            return
        raw = combo_edit.text().strip()
        if not raw:
            return
        tokens = self._parse_tokens(raw)
        added = False
        for token in tokens:
            resolved = self._combo.resolve_text(token)
            if resolved:
                added = self._add_location(resolved) or added
        if added:
            self._combo.setCurrentIndex(-1)
            combo_edit = self._combo.lineEdit()
            if combo_edit is not None:
                combo_edit.clear()

    def _add_location(self, loc: str) -> bool:
        if not loc or loc in self._locations:
            return False
        self._locations.append(loc)
        self._refresh_chips()
        self.valueChanged.emit()
        return True

    def _remove_location(self, loc: str) -> None:
        if loc not in self._locations:
            return
        self._locations = [item for item in self._locations if item != loc]
        self._refresh_chips()
        self.valueChanged.emit()

    def _refresh_chips(self) -> None:
        while self._chips_layout.count():
            item = self._chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for loc in self._locations:
            chip = LocationChip(loc, self._chips_container)
            chip.removed.connect(self._remove_location)
            self._chips_layout.addWidget(chip)
        self._update_chip_area_height()

    def _update_chip_area_height(self) -> None:
        visible = bool(self._locations)
        self._chips_scroll.setVisible(visible)
        self._clear_btn.setVisible(visible)
        if not visible:
            self._chips_scroll.setMinimumHeight(0)
            self._chips_scroll.setMaximumHeight(0)
            return
        self._chips_layout.activate()
        self._chips_container.adjustSize()
        hint_height = self._chips_container.sizeHint().height()
        target_height = max(
            _CHIP_AREA_MIN_HEIGHT,
            min(_CHIP_AREA_MAX_HEIGHT, int(hint_height) + 6),
        )
        self._chips_scroll.setMinimumHeight(target_height)
        self._chips_scroll.setMaximumHeight(target_height)

    def _refresh_status_style(self) -> None:
        if not is_qt_object_alive(self._status_label):
            return
        style = self._status_label.style()
        style.unpolish(self._status_label)
        style.polish(self._status_label)
        self._status_label.update()

    def _async_status_controls_alive(self) -> bool:
        return (
            is_qt_object_alive(self)
            and is_qt_object_alive(self._status_label)
            and is_qt_object_alive(self._retry_btn)
        )

    @staticmethod
    def _parse_tokens(raw: str) -> list[str]:
        if any(sep in raw for sep in (";", "\n", "|")):
            return split_location_tokens(raw)
        raw = raw.strip()
        return [raw] if raw else []
