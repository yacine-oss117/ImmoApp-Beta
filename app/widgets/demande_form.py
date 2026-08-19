"""
Demande form widget shared by panels and dialogs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from app.models import Demande
from app.services.locations import filter_locations_by_wilaya
from app.utils.common import coerce_number
from app.utils.i18n import tr_factory
from app.widgets.demande_form_ui import setup_demande_form
from app.widgets.form_value_parsers import get_float, get_int, get_str
from app.widgets.location_form_helpers import (
    add_location_with_wilaya_async,
    normalize_location_with_wilaya,
    prime_locations_non_blocking,
    refresh_locations_async,
)
from app.widgets.location_multi_select import LocationMultiSelect
from app.widgets.prefix_combo import PrefixComboBox

_TR = tr_factory("DemandeForm")


class DemandeForm(QWidget):
    """Form fields for a client property request."""

    data_changed = Signal()

    type: QComboBox
    action: QComboBox
    wilaya: PrefixComboBox
    location: LocationMultiSelect
    beds_min: QSpinBox
    surface_min: QDoubleSpinBox
    surface_max: QDoubleSpinBox
    budget_min: QDoubleSpinBox
    budget_max: QDoubleSpinBox
    furnished: QComboBox
    floor_min: QSpinBox
    floor_max: QSpinBox
    floor_label: QLabel
    floor_row_widget: QWidget
    elevator: QCheckBox
    accessibility_required: QCheckBox
    tags: QLineEdit
    remarks: QLineEdit

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._all_locations: list[str] = []
        self._setup_ui()

    @staticmethod
    def _populate_combo(combo: QComboBox, values: Sequence[str], labels: Mapping[str, str]) -> None:
        """Populate a combo box with display labels while storing stable values."""
        combo.clear()
        for value in values:
            combo.addItem(labels.get(value, value), value)

    @staticmethod
    def _combo_value(combo: QComboBox) -> str:
        """Return the stored value for a combo box selection."""
        value = combo.currentData()
        if value is None:
            return str(combo.currentText())
        return str(value)

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        """Set a combo box selection by stored value."""
        if value is None:
            return
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            combo.setCurrentText(str(value))

    def _setup_ui(self) -> None:
        setup_demande_form(self)
        cached = prime_locations_non_blocking(
            self,
            self._set_locations_source,
            on_error=self._on_locations_error,
        )
        if cached:
            self.location.clear_async_state()
        else:
            self.location.set_async_state(
                "loading",
                _TR("Loading locations..."),
                retry_callback=self._retry_locations_refresh,
            )

    def _on_wilaya_changed(self, _wilaya: str) -> None:
        self._refresh_locations(clear_selection=True)

    def _refresh_locations(self, clear_selection: bool = False) -> None:
        filtered = filter_locations_by_wilaya(self._all_locations, self.wilaya.value())
        self.location.setItems(filtered)
        if clear_selection:
            self.location.clear()

    def _set_locations_source(self, locations: list[str]) -> None:
        self._all_locations = list(locations)
        self._refresh_locations(clear_selection=False)
        self.location.clear_async_state()

    def _retry_locations_refresh(self) -> None:
        self.location.set_async_state("loading", _TR("Refreshing locations..."))
        refresh_locations_async(
            self,
            self._set_locations_source,
            on_error=self._on_locations_error,
        )

    def _on_locations_error(self, message: str) -> None:
        self.location.set_async_state(
            "error",
            message,
            retry_callback=self._retry_locations_refresh,
        )

    def _on_add_location(self, name: str) -> bool | str:
        full_name = normalize_location_with_wilaya(name, self.wilaya.value())
        if not full_name:
            self.location.set_async_state(
                "error",
                _TR("Location name is required."),
                retry_callback=self._retry_locations_refresh,
            )
            return False
        if full_name in self._all_locations:
            self.location.clear_async_state()
            return full_name

        self._all_locations.append(full_name)
        self._all_locations.sort()
        self._refresh_locations()
        self._persist_location_async(full_name)
        return full_name

    def _persist_location_async(self, full_name: str) -> None:
        def _retry() -> None:
            self._persist_location_async(full_name)

        def _on_error(message: str) -> None:
            self._on_location_save_failed(full_name, message)

        self.location.set_async_state(
            "loading",
            _TR("Saving location..."),
            retry_callback=_retry,
        )
        add_location_with_wilaya_async(
            self,
            full_name,
            "",
            on_success=self._on_location_saved,
            on_error=_on_error,
        )

    def _on_location_saved(self, _full_name: str) -> None:
        self.location.set_async_state("success", _TR("Location saved."))
        QTimer.singleShot(1200, self.location.clear_async_state)

    def _on_location_save_failed(self, full_name: str, message: str) -> None:
        def _retry() -> None:
            self._persist_location_async(full_name)

        self.location.set_async_state(
            "error",
            message,
            retry_callback=_retry,
        )

    def _on_type_changed(self, _text: str) -> None:
        is_apt = self._combo_value(self.type) == "apartment"
        self.floor_label.setVisible(is_apt)
        floor_parent = getattr(self, "floor_row_widget", None) or self.floor_min.parentWidget()
        if floor_parent is not None:
            floor_parent.setVisible(is_apt)
        self.elevator.setVisible(is_apt)

    def _emit_changed(self) -> None:
        self.data_changed.emit()

    def validate(self) -> tuple[bool, str]:
        return True, ""

    @staticmethod
    def _spinbox_number(spinbox: QDoubleSpinBox) -> float:
        try:
            text_value = coerce_number(spinbox.lineEdit().text())
            if text_value is not None:
                return float(text_value)
        except Exception:
            pass
        return float(spinbox.value())

    def get_data(self) -> dict[str, object]:
        return {
            "type": self._combo_value(self.type),
            "action": self._combo_value(self.action),
            "wilaya": self.wilaya.value(),
            "locations": self.location.value(),
            "beds_min": self.beds_min.value(),
            "surface_min": self._spinbox_number(self.surface_min),
            "surface_max": self._spinbox_number(self.surface_max),
            "budget_min": self._spinbox_number(self.budget_min),
            "budget_max": self._spinbox_number(self.budget_max),
            "furnished": self._combo_value(self.furnished),
            "floor_min": self.floor_min.value(),
            "floor_max": self.floor_max.value(),
            "elevator": self.elevator.isChecked(),
            "accessibility_required": self.accessibility_required.isChecked(),
            "tags": self.tags.text().strip(),
            "remarks": self.remarks.text().strip(),
        }

    def set_data(self, data: Mapping[str, object] | Demande) -> None:
        if isinstance(data, Demande):
            if data.type:
                self._set_combo_value(self.type, str(data.type))
            if data.action:
                self._set_combo_value(self.action, str(data.action))
            if data.wilaya:
                self.wilaya.setValue(str(data.wilaya))
            if data.locations:
                self.location.setValue(str(data.locations))
            self.beds_min.setValue(int(data.beds_min or 0))
            self.surface_min.setValue(float(data.surface_min or 0))
            self.surface_max.setValue(float(data.surface_max or 0))
            self.budget_min.setValue(float(data.budget_min or 0))
            self.budget_max.setValue(float(data.budget_max or 0))
            if data.furnished:
                self._set_combo_value(self.furnished, str(data.furnished))
            self.floor_min.setValue(int(data.floor_min or 0))
            self.floor_max.setValue(int(data.floor_max or 100))
            self.elevator.setChecked(bool(data.elevator))
            self.accessibility_required.setChecked(bool(data.accessibility_required))
            self.tags.setText(data.tags or "")
            self.remarks.setText(data.remarks or "")
            return

        type_val = get_str(data, "type")
        if type_val:
            self._set_combo_value(self.type, type_val)
        action_val = get_str(data, "action")
        if action_val:
            self._set_combo_value(self.action, action_val)

        wilaya_val = get_str(data, "wilaya")
        if wilaya_val:
            self.wilaya.setValue(wilaya_val)

        locations_val = get_str(data, "locations")
        if locations_val:
            self.location.setValue(locations_val)

        self.beds_min.setValue(get_int(data, "beds_min"))
        self.surface_min.setValue(get_float(data, "surface_min"))
        self.surface_max.setValue(get_float(data, "surface_max"))
        self.budget_min.setValue(get_float(data, "budget_min"))
        self.budget_max.setValue(get_float(data, "budget_max"))

        furnished_val = get_str(data, "furnished")
        if furnished_val:
            self._set_combo_value(self.furnished, furnished_val)

        self.floor_min.setValue(get_int(data, "floor_min"))
        self.floor_max.setValue(get_int(data, "floor_max", 100))
        self.elevator.setChecked(bool(data.get("elevator")))
        self.accessibility_required.setChecked(bool(data.get("accessibility_required")))
        self.tags.setText(get_str(data, "tags"))
        self.remarks.setText(get_str(data, "remarks"))

    def clear(self) -> None:
        self.type.setCurrentIndex(0)
        self.action.setCurrentIndex(0)
        self.wilaya.setCurrentIndex(-1)
        wilaya_edit = self.wilaya.lineEdit()
        if wilaya_edit is not None:
            wilaya_edit.clear()
        self.location.clear()
        self.beds_min.setValue(0)
        self.surface_min.setValue(0)
        self.surface_max.setValue(0)
        self.budget_min.setValue(0)
        self.budget_max.setValue(0)
        self.furnished.setCurrentIndex(0)
        self.floor_min.setValue(0)
        self.floor_max.setValue(100)
        self.elevator.setChecked(False)
        self.accessibility_required.setChecked(False)
        self.tags.clear()
        self.remarks.clear()
