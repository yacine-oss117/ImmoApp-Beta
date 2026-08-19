"""Localized labels for ListingSQLModel display."""

from __future__ import annotations

from app.utils.i18n import tr_factory

_TR = tr_factory("ListingSQLModel")

TYPE_LABELS = {
    "": _TR("Any"),
    "apartment": _TR("Apartment"),
    "house": _TR("House"),
    "business": _TR("Business"),
    "land": _TR("Land"),
    "other": _TR("Other"),
}
ACTION_LABELS = {
    "sell": _TR("Sell"),
    "rent": _TR("Rent"),
}
FURNISHED_LABELS = {
    "any": _TR("Any"),
    "yes": _TR("Yes"),
    "no": _TR("No"),
}


def format_listing_name(family_name: str, match_count: int, is_vip: bool) -> str:
    vip = _TR("VIP ") if is_vip else ""
    return f"[{match_count}] {vip}{family_name}"


__all__ = [
    "ACTION_LABELS",
    "FURNISHED_LABELS",
    "TYPE_LABELS",
    "format_listing_name",
]
