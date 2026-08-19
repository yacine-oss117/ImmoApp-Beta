"""
Prefix search index helper for PrefixComboBox.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right

from app.services.locations import normalize_for_lookup


class PrefixSearchIndex:
    """Maintain a normalized prefix-search index for combo box items."""

    def __init__(self) -> None:
        self._normalized_keys: list[str] = []
        self._sorted_items: list[str] = []
        self._normalized_map: dict[str, str] = {}

    def rebuild(self, items: list[str]) -> None:
        pairs = sorted((normalize_for_lookup(item), item) for item in items if item)
        self._normalized_keys = [key for key, _item in pairs]
        self._sorted_items = [item for _key, item in pairs]
        self._normalized_map = {key: item for key, item in pairs}

    def prefix_matches(self, normalized_query: str, limit: int) -> list[str]:
        if not normalized_query:
            return list(self._sorted_items)
        if not self._normalized_keys:
            return []
        start = bisect_left(self._normalized_keys, normalized_query)
        end = bisect_right(self._normalized_keys, f"{normalized_query}\uffff")
        matches = self._sorted_items[start:end]
        return matches[:limit] if limit and len(matches) > limit else matches

    def resolve(self, value: str) -> str | None:
        return self._normalized_map.get(normalize_for_lookup(value))
