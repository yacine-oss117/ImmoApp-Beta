"""
Offer form widget shared by panels and dialogs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from app.services.locations import filter_locations_by_wilaya
from app.utils.common import coerce_number
from app.utils.geo import map_link_to_url, parse_lat_lon
from app.utils.i18n import tr_factory
from app.widgets.location_form_helpers import (
    add_location_with_wilaya_async,
    normalize_location_with_wilaya,
    prime_locations_non_blocking,
    refresh_locations_async,
)
from app.widgets.location_multi_select import LocationMultiSelect
from app.widgets.offer_form_data import OfferFormDataMixin
from app.widgets.offer_form_helpers import combo_value, populate_combo, set_combo_value
from app.widgets.offer_form_ui import setup_offer_form
from app.widgets.prefix_combo import PrefixComboBox

_TR = tr_factory("OfferForm")


class OfferForm(OfferFormDataMixin, QWidget):
    """Form fields for a property offer."""

    data_changed = Signal()

    type: QComboBox
    action: QComboBox
    wilaya: PrefixComboBox
    location: LocationMultiSelect
    beds: QSpinBox
    surface: QDoubleSpinBox
    budget: QDoubleSpinBox
    furnished: QComboBox
    floor: QSpinBox
    floor_label: QLabel
    elevator: QCheckBox
    accessibility_supported: QCheckBox
    price_negotiable: QCheckBox
    price_flex_pct: QLineEdit
    link: QLineEdit
    latitude: QLineEdit
    longitude: QLineEdit
    extract_coords_btn: QPushButton
    open_map_btn: QPushButton
    remarks: QLineEdit

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._all_locations: list[str] = []
        self._setup_ui()

    @staticmethod
    def _populate_combo(combo: QComboBox, values: Sequence[str], labels: Mapping[str, str]) -> None:
        populate_combo(combo, values, labels)

    @staticmethod
    def _combo_value(combo: QComboBox) -> str:
        return combo_value(combo)

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str | None) -> None:
        set_combo_value(combo, value)

    def _setup_ui(self) -> None:
        setup_offer_form(self)
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
        self.floor.setVisible(is_apt)
        self.elevator.setVisible(is_apt)

    def _emit_changed(self) -> None:
        self.data_changed.emit()

    def _on_link_changed(self) -> None:
        self._maybe_autofill_coords()
        self._emit_changed()

    def _on_coords_changed(self) -> None:
        self._emit_changed()

    def _extract_coords_from_link(self) -> None:
        coords = parse_lat_lon(self.link.text())
        if not coords:
            QMessageBox.information(
                self, _TR("Coordinates"), _TR("Couldn't find coordinates in this link.")
            )
            return
        self._set_coords(coords[0], coords[1])
        self._emit_changed()

    def _open_map_in_browser(self) -> None:
        lat = self._read_lat()
        lon = self._read_lon()
        url = map_link_to_url(self.link.text(), latitude=lat, longitude=lon)
        if not url:
            QMessageBox.information(
                self, _TR("Map"), _TR("No valid map link or coordinates found.")
            )
            return
        QDesktopServices.openUrl(QUrl(url))

    def _maybe_autofill_coords(self) -> None:
        if self.latitude.text().strip() or self.longitude.text().strip():
            return
        coords = parse_lat_lon(self.link.text())
        if coords:
            self._set_coords(coords[0], coords[1])

    def _set_coords(self, lat: float, lon: float) -> None:
        self.latitude.setText(self._format_coord(lat))
        self.longitude.setText(self._format_coord(lon))

    def _read_lat(self) -> float | None:
        value = coerce_number(self.latitude.text())
        if value is None or not -90 <= value <= 90:
            return None
        return float(value)

    def _read_lon(self) -> float | None:
        value = coerce_number(self.longitude.text())
        if value is None or not -180 <= value <= 180:
            return None
        return float(value)

    @staticmethod
    def _format_coord(value: float) -> str:
        return f"{value:.6f}".rstrip("0").rstrip(".")

    def validate(self) -> tuple[bool, str]:
        return True, ""
