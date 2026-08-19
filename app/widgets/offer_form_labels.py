"""Localized labels for OfferForm combos."""

from __future__ import annotations

from app.utils.i18n import tr_factory

_TR = tr_factory("OfferForm")

TYPE_LABELS = {
    "": _TR("Any"),
    "apartment": _TR("Apartment"),
    "house": _TR("House"),
    "business": _TR("Business"),
    "land": _TR("Land"),
    "other": _TR("Other"),
}
ACTION_LABELS = {
    "sell": _TR("For Sale"),
    "rent": _TR("For Rent"),
}
FURNISHED_LABELS = {
    "any": _TR("Any"),
    "yes": _TR("Yes"),
    "no": _TR("No"),
}
