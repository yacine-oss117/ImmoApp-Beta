"""Location helpers backed by API lookups (thin client)."""

from __future__ import annotations

import unicodedata

from app.services.lookup_service import get_all_wilayas

__all__ = [
    "get_wilaya_labels",
    "filter_locations_by_wilaya",
    "normalize_for_lookup",
]


def get_wilaya_labels() -> list[str]:
    """Return wilaya labels as 'Name - Code' from the API lookup cache."""
    try:
        items = get_all_wilayas()
    except Exception:
        return []
    labels: list[str] = []
    for _, name, code in items:
        if not name:
            continue
        if code:
            labels.append(f"{name} - {code}")
        else:
            labels.append(name)
    return labels


def normalize_for_lookup(text: str) -> str:
    """Normalize text for lookup: lowercase, remove accents, remove dashes."""
    raw = (text or "").lower()
    raw = unicodedata.normalize("NFD", raw)
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    raw = raw.replace("-", " ").replace("'", " ")
    return raw


def _extract_wilaya_from_location(location: str) -> str:
    """Extract wilaya from location format 'Commune, Wilaya - Code'."""
    if ", " in location:
        return location.split(", ", 1)[1]
    return ""


def filter_locations_by_wilaya(locations: list[str], wilaya: str) -> list[str]:
    """Filter locations to only those matching the wilaya."""
    if not wilaya:
        return locations
    wilaya_norm = normalize_for_lookup(wilaya)
    return [
        loc
        for loc in locations
        if normalize_for_lookup(_extract_wilaya_from_location(loc)) == wilaya_norm
    ]
