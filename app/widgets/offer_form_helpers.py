"""
Small helper functions for OfferForm widgets.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtWidgets import QComboBox


def populate_combo(combo: QComboBox, values: Sequence[str], labels: Mapping[str, str]) -> None:
    """Populate a combo box with display labels while storing stable values."""
    combo.clear()
    for value in values:
        combo.addItem(labels.get(value, value), value)


def combo_value(combo: QComboBox) -> str:
    """Return the stored value for a combo box selection."""
    value = combo.currentData()
    if value is None:
        return str(combo.currentText())
    return str(value)


def set_combo_value(combo: QComboBox, value: str | None) -> None:
    """Set a combo box selection by stored value."""
    if value is None:
        return
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)
    else:
        combo.setCurrentText(str(value))
