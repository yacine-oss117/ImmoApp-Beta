"""
Data serialization helpers for OfferForm.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from app.models import Offer
from app.utils.common import coerce_number, display_wilaya
from app.widgets.form_value_parsers import get_float, get_int, get_str


class _OfferFormView(Protocol):
    type: Any
    action: Any
    wilaya: Any
    location: Any
    beds: Any
    surface: Any
    budget: Any
    price_negotiable: Any
    price_flex_pct: Any
    furnished: Any
    floor: Any
    elevator: Any
    accessibility_supported: Any
    link: Any
    latitude: Any
    longitude: Any
    remarks: Any

    def _combo_value(self, combo: Any) -> str: ...
    def _set_combo_value(self, combo: Any, value: str | None) -> None: ...
    def _format_coord(self, value: float) -> str: ...
    def _maybe_autofill_coords(self) -> None: ...


class OfferFormDataMixin:
    """Mixin that provides get/set/clear behavior for OfferForm."""

    @staticmethod
    def _spinbox_number(spinbox: Any) -> float:
        try:
            text_value = coerce_number(spinbox.lineEdit().text())
            if text_value is not None:
                return float(text_value)
        except Exception:
            pass
        return float(spinbox.value())

    @staticmethod
    def _wilaya_label(name: object, wilaya_id: object) -> str:
        raw_name = str(name or "").strip()
        raw_id = str(wilaya_id or "").strip()
        if raw_name and " - " in raw_name and any(ch.isdigit() for ch in raw_name):
            return raw_name
        if raw_name and raw_id:
            return f"{raw_name} - {raw_id}"
        if raw_id:
            return display_wilaya(raw_id)
        if raw_name:
            return display_wilaya(raw_name)
        return ""

    @staticmethod
    def _combo_items(combo: Any) -> list[str]:
        return [combo.itemText(index) for index in range(combo.count())]

    def _set_wilaya_value(self: _OfferFormView, candidates: Iterable[str]) -> None:
        valid_candidates = [candidate.strip() for candidate in candidates if candidate.strip()]
        for candidate in valid_candidates:
            self.wilaya.setValue(candidate)
            if self.wilaya.value():
                return

        # Persisted offer data is authoritative. If the lookup cache is unavailable or stale,
        # keep a selectable value rather than blanking the city and losing it on save.
        fallback = next(
            (
                candidate
                for candidate in valid_candidates
                if " - " in candidate and any(ch.isdigit() for ch in candidate)
            ),
            "",
        )
        if not fallback:
            return
        items = OfferFormDataMixin._combo_items(self.wilaya)
        if fallback not in items:
            self.wilaya.setItems([*items, fallback])
        self.wilaya.setValue(fallback)

    def get_data(self: _OfferFormView) -> dict[str, object]:
        lat_text = self.latitude.text().strip()
        lon_text = self.longitude.text().strip()
        return {
            "type": self._combo_value(self.type),
            "action": self._combo_value(self.action),
            "wilaya": self.wilaya.value(),
            "location": self.location.value(),
            "beds": self.beds.value(),
            "surface": OfferFormDataMixin._spinbox_number(self.surface),
            "budget": OfferFormDataMixin._spinbox_number(self.budget),
            "price_negotiable": self.price_negotiable.isChecked(),
            "price_flex_pct": coerce_number(self.price_flex_pct.text().strip()) or 0.0,
            "furnished": self._combo_value(self.furnished),
            "floor": self.floor.value(),
            "elevator": self.elevator.isChecked(),
            "accessibility_supported": self.accessibility_supported.isChecked(),
            "link": self.link.text().strip(),
            "latitude": lat_text or None,
            "longitude": lon_text or None,
            "remarks": self.remarks.text().strip(),
        }

    def set_data(self: _OfferFormView, data: Mapping[str, object] | Offer) -> None:
        if isinstance(data, Offer):
            if data.type:
                self._set_combo_value(self.type, str(data.type))
            if data.action:
                self._set_combo_value(self.action, str(data.action))
            if data.wilaya or data.wilaya_id:
                OfferFormDataMixin._set_wilaya_value(
                    self,
                    (
                        OfferFormDataMixin._wilaya_label(data.wilaya, data.wilaya_id),
                        display_wilaya(str(data.wilaya_id or "")),
                        display_wilaya(str(data.wilaya or "")),
                        str(data.wilaya or ""),
                    ),
                )
            if data.location:
                self.location.setValue(str(data.location))
            self.beds.setValue(int(data.beds or 0))
            self.surface.setValue(float(data.surface or 0))
            self.budget.setValue(float(data.budget or 0))
            self.price_negotiable.setChecked(bool(data.price_negotiable))
            self.price_flex_pct.setText(str(int(data.price_flex_pct or 0)))
            if data.furnished:
                self._set_combo_value(self.furnished, str(data.furnished))
            self.floor.setValue(int(data.floor or 0))
            self.elevator.setChecked(bool(data.elevator))
            self.accessibility_supported.setChecked(bool(data.accessibility_supported))
            self.link.setText(data.link or "")

            if data.latitude is not None:
                self.latitude.setText(self._format_coord(float(data.latitude)))
            else:
                self.latitude.clear()
            if data.longitude is not None:
                self.longitude.setText(self._format_coord(float(data.longitude)))
            else:
                self.longitude.clear()
            self.remarks.setText(data.remarks or "")
            self._maybe_autofill_coords()
            return

        type_val = get_str(data, "type")
        if type_val:
            self._set_combo_value(self.type, type_val)
        action_val = get_str(data, "action")
        if action_val:
            self._set_combo_value(self.action, action_val)

        wilaya_val = get_str(data, "wilaya")
        wilaya_id = get_int(data, "wilaya_id")
        if wilaya_val or wilaya_id:
            OfferFormDataMixin._set_wilaya_value(
                self,
                (
                    OfferFormDataMixin._wilaya_label(wilaya_val, wilaya_id),
                    display_wilaya(str(wilaya_id or "")),
                    display_wilaya(wilaya_val),
                    wilaya_val,
                ),
            )

        location_val = get_str(data, "location")
        if location_val:
            self.location.setValue(location_val)

        self.beds.setValue(get_int(data, "beds"))
        self.surface.setValue(get_float(data, "surface"))
        self.budget.setValue(get_float(data, "budget"))
        self.price_negotiable.setChecked(bool(data.get("price_negotiable")))
        self.price_flex_pct.setText(str(get_int(data, "price_flex_pct")))

        furnished_val = get_str(data, "furnished")
        if furnished_val:
            self._set_combo_value(self.furnished, furnished_val)

        self.floor.setValue(get_int(data, "floor"))
        self.elevator.setChecked(bool(data.get("elevator")))
        self.accessibility_supported.setChecked(bool(data.get("accessibility_supported")))
        self.link.setText(get_str(data, "link"))

        lat_raw = data.get("latitude")
        lon_raw = data.get("longitude")
        if lat_raw is not None and str(lat_raw).strip() != "":
            lat_val = coerce_number(lat_raw)
            if lat_val is not None:
                self.latitude.setText(self._format_coord(float(lat_val)))
        else:
            self.latitude.clear()
        if lon_raw is not None and str(lon_raw).strip() != "":
            lon_val = coerce_number(lon_raw)
            if lon_val is not None:
                self.longitude.setText(self._format_coord(float(lon_val)))
        else:
            self.longitude.clear()
        self.remarks.setText(get_str(data, "remarks"))
        self._maybe_autofill_coords()

    def clear(self: _OfferFormView) -> None:
        self.type.setCurrentIndex(0)
        self.action.setCurrentIndex(0)
        self.wilaya.setCurrentIndex(-1)
        wilaya_edit = self.wilaya.lineEdit()
        if wilaya_edit is not None:
            wilaya_edit.clear()
        self.location.clear()
        self.beds.setValue(0)
        self.surface.setValue(0)
        self.budget.setValue(0)
        self.price_negotiable.setChecked(False)
        self.price_flex_pct.clear()
        self.furnished.setCurrentIndex(0)
        self.floor.setValue(0)
        self.elevator.setChecked(False)
        self.accessibility_supported.setChecked(False)
        self.link.clear()

        self.latitude.clear()
        self.longitude.clear()
        self.remarks.clear()
