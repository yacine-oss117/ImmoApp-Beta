"""Compact summary card for a client's property search request.

The detailed request form lives in a modal dialog. Keeping only a concise
summary in the Clients editor prevents one or more requests from expanding the
page into several screen-heights while preserving the existing DemandePanel
persistence interface used by ClientsTabV2.
"""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.models import Demande
from app.utils.common import fmt_money_short
from app.utils.i18n import tr_factory
from app.widgets.demande_form_labels import ACTION_LABELS, TYPE_LABELS
from app.widgets.demande_request_dialog import DemandeRequestDialog

_TR = tr_factory("DemandePanel")

_REQUEST_FIELDS = (
    "type",
    "action",
    "wilaya",
    "locations",
    "beds_min",
    "surface_min",
    "surface_max",
    "budget_min",
    "budget_max",
    "furnished",
    "floor_min",
    "floor_max",
    "elevator",
    "accessibility_required",
    "tags",
    "remarks",
)


class DemandePanel(QWidget):
    """Compact, editable summary for one client property request."""

    data_changed = Signal()
    delete_requested = Signal()
    expanded = Signal(object)

    def __init__(
        self, demande_id: int = 0, demande_number: int = 1, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._demande_id = int(demande_id)
        self._demande_number = int(demande_number)
        self._row_version = 1
        self._data: dict[str, object] = {}
        self._dirty = demande_id <= 0
        self._saved_signature: tuple[tuple[str, str], ...] | None = None
        self._setup_ui()
        self._refresh_summary()

    def _setup_ui(self) -> None:
        self.setObjectName(f"demandePanel_{self._demande_number}")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("demandeSummaryCard")
        card.setProperty("immoRole", "requestSummary")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(14, 10, 10, 10)
        card_layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        self._title_label = QLabel(card)
        self._title_label.setObjectName("demandeSummaryTitle")
        self._primary_label = QLabel(card)
        self._primary_label.setObjectName("demandeSummaryPrimary")
        self._secondary_label = QLabel(card)
        self._secondary_label.setObjectName("demandeSummarySecondary")
        self._secondary_label.setWordWrap(True)
        self._notes_label = QLabel(card)
        self._notes_label.setObjectName("demandeSummaryNotes")
        self._notes_label.setWordWrap(True)

        text_col.addWidget(self._title_label)
        text_col.addWidget(self._primary_label)
        text_col.addWidget(self._secondary_label)
        text_col.addWidget(self._notes_label)
        card_layout.addLayout(text_col, 1)

        action_col = QVBoxLayout()
        action_col.setSpacing(6)
        action_col.addStretch()

        self._edit_btn = QPushButton(_TR("Edit"), card)
        self._edit_btn.setObjectName(f"demandePanelEditButton_{self._demande_number}")
        self._edit_btn.setProperty("immoVariant", "secondary")
        self._edit_btn.setProperty("immoSize", "sm")
        self._edit_btn.setAccessibleName(_TR("Edit request"))
        self._edit_btn.clicked.connect(self._on_edit)

        self._delete_btn = QPushButton(_TR("Remove"), card)
        self._delete_btn.setObjectName(f"demandePanelDeleteButton_{self._demande_number}")
        self._delete_btn.setProperty("immoVariant", "danger")
        self._delete_btn.setProperty("immoSize", "sm")
        self._delete_btn.setAccessibleName(_TR("Remove request"))
        self._delete_btn.clicked.connect(self._on_delete)

        action_col.addWidget(self._edit_btn)
        action_col.addWidget(self._delete_btn)
        action_col.addStretch()
        card_layout.addLayout(action_col)

        root.addWidget(card)

    def _on_edit(self) -> None:
        self.edit_request()

    def _on_delete(self) -> None:
        self.delete_requested.emit()

    def edit_request(self, *, new_request: bool = False) -> bool:
        """Open the modal editor and stage changes in this summary card."""
        title = _TR("New Property Request") if new_request else _TR("Edit Property Request")
        save_text = _TR("Add Request") if new_request else _TR("Save Request")
        dialog = DemandeRequestDialog(
            self._data or None,
            title=title,
            save_text=save_text,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False

        preserved_id = self._demande_id
        preserved_row_version = self._row_version
        self._data = dict(dialog.get_data())
        self._demande_id = preserved_id
        self._row_version = preserved_row_version
        self._dirty = True
        self._refresh_summary()
        self.data_changed.emit()
        return True

    def is_collapsed(self) -> bool:
        """Summary cards are intentionally always compact and visible."""
        return False

    def validate(self) -> tuple[bool, str]:
        if not self._data:
            return False, _TR("Complete the property request before saving the client.")
        return True, ""

    @property
    def demande_id(self) -> int:
        return self._demande_id

    def set_demande_id(self, id: int) -> None:
        self._demande_id = int(id)

    def is_dirty(self) -> bool:
        if not self._dirty:
            return False
        if self._saved_signature is not None and self._data_signature() == self._saved_signature:
            self._dirty = False
            return False
        return self._dirty

    def mark_saved(self, *, row_version: int | None = None) -> None:
        if row_version is not None:
            self._row_version = int(row_version)
        self._saved_signature = self._data_signature()
        self._dirty = False

    def _data_signature(self) -> tuple[tuple[str, str], ...]:
        data = self.get_data()
        data.pop("id", None)
        data.pop("row_version", None)
        return tuple(sorted((str(key), repr(value)) for key, value in data.items()))

    def set_number(self, num: int) -> None:
        self._demande_number = int(num)
        self.setObjectName(f"demandePanel_{num}")
        self._edit_btn.setObjectName(f"demandePanelEditButton_{num}")
        self._delete_btn.setObjectName(f"demandePanelDeleteButton_{num}")
        self._refresh_summary()

    def collapse(self) -> None:
        """Compatibility no-op: summary cards do not collapse."""

    def expand(self) -> None:
        """Compatibility no-op: summary cards are already expanded."""
        self.expanded.emit(self)

    def get_data(self) -> dict[str, object]:
        data = dict(self._data)
        data["id"] = self._demande_id
        if self._demande_id > 0:
            data["row_version"] = self._row_version
        return data

    def set_data(self, data: Mapping[str, object] | Demande) -> None:
        if isinstance(data, Demande):
            self._demande_id = int(data.id)
            self._row_version = int(data.row_version)
            self._data = {field: getattr(data, field) for field in _REQUEST_FIELDS}
            self._saved_signature = self._data_signature()
            self._dirty = False
            self._refresh_summary()
            return

        self._demande_id = self._coerce_int(data.get("id"), 0)
        self._row_version = self._coerce_int(data.get("row_version"), 1)
        self._data = {field: data.get(field) for field in _REQUEST_FIELDS if field in data}
        self._saved_signature = self._data_signature()
        self._dirty = False
        self._refresh_summary()

    def clear(self) -> None:
        self._demande_id = 0
        self._row_version = 1
        self._data = {}
        self._saved_signature = None
        self._dirty = True
        self._refresh_summary()

    @staticmethod
    def _coerce_int(value: object, default: int) -> int:
        try:
            return int(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_float(value: object) -> float:
        try:
            return float(value) if value not in (None, "") else 0.0
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _compact_range(min_value: object, max_value: object, suffix: str) -> str:
        minimum = DemandePanel._coerce_float(min_value)
        maximum = DemandePanel._coerce_float(max_value)
        if minimum > 0 and maximum > 0:
            if abs(minimum - maximum) < 1e-9:
                return f"{minimum:g} {suffix}".strip()
            return f"{minimum:g}–{maximum:g} {suffix}".strip()
        if minimum > 0:
            return f"≥ {minimum:g} {suffix}".strip()
        if maximum > 0:
            return f"≤ {maximum:g} {suffix}".strip()
        return ""

    @staticmethod
    def _compact_budget(min_value: object, max_value: object) -> str:
        minimum = DemandePanel._coerce_float(min_value)
        maximum = DemandePanel._coerce_float(max_value)
        if minimum > 0 and maximum > 0:
            if abs(minimum - maximum) < 1e-9:
                return fmt_money_short(minimum, "DZD")
            return f"{fmt_money_short(minimum)}–{fmt_money_short(maximum)} DZD"
        if minimum > 0:
            return f"≥ {fmt_money_short(minimum, 'DZD')}"
        if maximum > 0:
            return f"≤ {fmt_money_short(maximum, 'DZD')}"
        return ""

    def _refresh_summary(self) -> None:
        self._title_label.setText(_TR("Request {num}").format(num=self._demande_number))

        if not self._data:
            self._primary_label.setText(_TR("New property request"))
            self._secondary_label.setText(_TR("Open the request editor to add criteria."))
            self._notes_label.clear()
            self._notes_label.hide()
            return

        type_key = str(self._data.get("type") or "")
        action_key = str(self._data.get("action") or "")
        type_label = TYPE_LABELS.get(type_key, type_key or _TR("Any property"))
        action_label = ACTION_LABELS.get(action_key, action_key)
        wilaya = str(self._data.get("wilaya") or "").strip()

        primary_parts = [part for part in (type_label, action_label, wilaya) if part]
        self._primary_label.setText("  ·  ".join(primary_parts) or _TR("Property request"))

        details: list[str] = []
        beds = self._coerce_int(self._data.get("beds_min"), 0)
        if beds > 0:
            details.append(_TR("{count} bedrooms").format(count=beds))
        surface = self._compact_range(
            self._data.get("surface_min"), self._data.get("surface_max"), "m²"
        )
        if surface:
            details.append(surface)
        budget = self._compact_budget(
            self._data.get("budget_min"), self._data.get("budget_max")
        )
        if budget:
            details.append(budget)
        locations = str(self._data.get("locations") or "").strip()
        if locations:
            details.append(locations)

        self._secondary_label.setText("  ·  ".join(details) or _TR("Flexible criteria"))

        remarks = str(self._data.get("remarks") or "").strip()
        tags = str(self._data.get("tags") or "").strip()
        note_parts = [part for part in (tags, remarks) if part]
        if note_parts:
            self._notes_label.setText("  ·  ".join(note_parts))
            self._notes_label.show()
        else:
            self._notes_label.clear()
            self._notes_label.hide()
