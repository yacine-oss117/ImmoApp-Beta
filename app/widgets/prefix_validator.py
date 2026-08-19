"""
Prefix validator for searchable combo boxes.
"""

from __future__ import annotations

from bisect import bisect_left

from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QWidget

from app.services.locations import normalize_for_lookup


class PrefixValidator(QValidator):
    """Validator that allows items from list OR new items (if enabled)."""

    def __init__(
        self, items: list[str], allow_new: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._allow_new = allow_new
        self._items: list[str] = []
        self._normalized_map: dict[str, str] = {}
        self._normalized_keys: list[str] = []
        self.set_items(items)

    def set_items(self, items: list[str]) -> None:
        self._items = list(items)
        self._normalized_map = {normalize_for_lookup(item): item for item in self._items if item}
        self._normalized_keys = sorted(self._normalized_map.keys())

    def _has_prefix_match(self, normalized_query: str) -> bool:
        if not normalized_query:
            return bool(self._normalized_keys)
        start = bisect_left(self._normalized_keys, normalized_query)
        if start < len(self._normalized_keys):
            return self._normalized_keys[start].startswith(normalized_query)
        return False

    def validate(self, text: str, pos: int) -> tuple[QValidator.State, str, int]:
        if not text:
            return QValidator.State.Intermediate, text, pos

        if text in self._items:
            return QValidator.State.Acceptable, text, pos

        normalized = normalize_for_lookup(text)
        mapped = self._normalized_map.get(normalized)
        if mapped:
            return QValidator.State.Acceptable, mapped, pos

        if self._allow_new:
            return QValidator.State.Acceptable, text, pos

        if self._has_prefix_match(normalized):
            return QValidator.State.Intermediate, text, pos

        return QValidator.State.Invalid, text, pos
