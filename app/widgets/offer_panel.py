"""
Offer Panel Widget - Form panel for a single property offer.

Features:
- Wilaya dropdown with prefix search (FIXED list)
- Location/Commune dropdown - CASCADING
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.models import Offer
from app.utils.i18n import tr_factory
from app.widgets.collapsible_section import CollapsibleSection
from app.widgets.offer_form import OfferForm
from app.widgets.offer_photos_widget import OfferPhotosWidget

_TR = tr_factory("OfferPanel")
logger = logging.getLogger(__name__)


class OfferPanel(QWidget):
    """
    A panel containing form fields for a single offer (property listing).

    UI-only wrapper for offer input fields.
    """

    data_changed = Signal()
    delete_requested = Signal()
    expanded = Signal(object)

    def __init__(
        self, offer_id: int = 0, offer_number: int = 1, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._offer_id = offer_id
        self._offer_number = offer_number
        self._row_version = 1
        self._dirty = offer_id <= 0
        self._saved_signature: tuple[tuple[str, str], ...] | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName(f"offerPanel_{self._offer_number}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = _TR("Offer {num}").format(num=self._offer_number)
        self._section = CollapsibleSection(title, self, show_delete=True, collapsible=False)
        self._section.setObjectName(f"offerPanelSection_{self._offer_number}")
        self._section.set_delete_button_object_name(f"offerPanelDeleteButton_{self._offer_number}")
        self._section.delete_requested.connect(self._on_delete)
        self._section.collapsed_changed.connect(self._on_collapse_changed)

        self._form = OfferForm(self)
        self._form.data_changed.connect(self._on_form_data_changed)
        self._content = QWidget(self)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(10)
        self._photos = OfferPhotosWidget(
            offer_id=self._offer_id,
            offer_number=self._offer_number,
            parent=self._content,
        )
        self._content_layout.addWidget(self._form)
        self._content_layout.addWidget(self._photos)
        self._section.set_content(self._content)
        layout.addWidget(self._section)

    def _on_form_data_changed(self) -> None:
        self._dirty = True
        self.data_changed.emit()

    def _on_collapse_changed(self, collapsed: bool) -> None:
        if not collapsed:
            self.expanded.emit(self)

    def _on_delete(self) -> None:
        self.delete_requested.emit()

    def is_collapsed(self) -> bool:
        return self._section.is_collapsed()

    def validate(self) -> tuple[bool, str]:
        """Validate the offer data."""
        return self._form.validate()

    @property
    def offer_id(self) -> int:
        return self._offer_id

    def set_offer_id(self, id: int) -> None:
        self._offer_id = id
        self._refresh_photo_context()

    def is_dirty(self) -> bool:
        if not self._dirty:
            return False
        if self._saved_signature is not None and self._data_signature() == self._saved_signature:
            self._dirty = False
            return False
        return self._dirty

    def mark_saved(self, *, row_version: int | None = None) -> None:
        if row_version is not None:
            self._row_version = row_version
        self._saved_signature = self._data_signature()
        self._dirty = False

    def _data_signature(self) -> tuple[tuple[str, str], ...]:
        data = self._form.get_data()
        data.pop("id", None)
        data.pop("row_version", None)
        return tuple(sorted((str(key), repr(value)) for key, value in data.items()))

    def set_number(self, num: int) -> None:
        self._offer_number = num
        self.setObjectName(f"offerPanel_{num}")
        self._section.setObjectName(f"offerPanelSection_{num}")
        self._section.set_delete_button_object_name(f"offerPanelDeleteButton_{num}")
        self._section.set_title(_TR("Offer {num}").format(num=num))
        self._refresh_photo_context()

    def collapse(self) -> None:
        self._section.collapse()

    def expand(self) -> None:
        self._section.expand()

    def get_data(self) -> dict[str, object]:
        data = self._form.get_data()
        data["id"] = self._offer_id
        if self._offer_id > 0:
            data["row_version"] = self._row_version
        return data

    def set_data(self, data: Mapping[str, object] | Offer) -> None:
        if isinstance(data, Offer):
            self._offer_id = data.id
            self._row_version = data.row_version
            self._form.set_data(data)
            self._refresh_photo_context()
            self._saved_signature = self._data_signature()
            self._dirty = False
            return

        def _get_int(key: str, default: int = 0) -> int:
            value = data.get(key, default)
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value)
            if isinstance(value, str):
                try:
                    return int(float(value.strip()))
                except ValueError:
                    return default
            return default

        self._offer_id = _get_int("id", 0)
        self._row_version = _get_int("row_version", 1)
        self._form.set_data(data)
        self._refresh_photo_context()
        self._saved_signature = self._data_signature()
        self._dirty = False

    def clear(self) -> None:
        self._offer_id = 0
        self._row_version = 1
        self._saved_signature = None
        self._form.clear()
        self._refresh_photo_context()
        self._dirty = True

    def _refresh_photo_context(self) -> None:
        try:
            self._photos.set_offer_context(
                offer_id=self._offer_id,
                offer_number=self._offer_number,
            )
        except (RuntimeError, ValueError):
            logger.warning("Offer photo context refresh failed", exc_info=True)
