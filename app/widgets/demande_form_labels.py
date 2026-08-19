"""Localized labels for DemandeForm combos."""

from __future__ import annotations

from app.utils.i18n import tr_factory

_TR = tr_factory("DemandeForm")

TYPE_LABELS = {
    "": _TR("Any"),
    "apartment": _TR("Apartment"),
    "house": _TR("House"),
    "business": _TR("Business"),
    "land": _TR("Land"),
    "other": _TR("Other"),
}
ACTION_LABELS = {
    "buy": _TR("To Buy"),
    "rent": _TR("To Rent"),
}
FURNISHED_LABELS = {
    "any": _TR("Any"),
    "yes": _TR("Yes"),
    "no": _TR("No"),
}
