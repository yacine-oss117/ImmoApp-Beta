"""
Render helpers for ListingSQLModel cells.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

from app.models import Listing, Offer
from app.ui.theme_manager import current_theme
from app.ui.theme_tokens import get_theme_tokens
from app.utils.common import display_wilaya, norm_text
from app.views.listing_sql_labels import ACTION_LABELS, FURNISHED_LABELS, TYPE_LABELS
from app.views.sql_formatting import format_budget, format_datetime, format_number


@lru_cache(maxsize=2)
def _colors_for_theme(theme_name: str) -> dict[str, QColor]:
    tokens = get_theme_tokens(theme_name)
    return {
        "listing_name": QColor(tokens["INFO"]),
        "offer_arrow": QColor(tokens["PRIMARY_HOVER"]),
    }


def _theme_colors() -> dict[str, QColor]:
    return _colors_for_theme(current_theme())


def listing_cell_value(
    listing: Listing,
    col: int,
    role: int,
    *,
    match_counts: dict[int, int],
    tr: Callable[[str], str],
) -> object | None:
    if role == int(Qt.ItemDataRole.DisplayRole):
        if col == 0:
            # Match counts are computed per loaded page for scalability.
            vip = tr("VIP ") if listing.is_vip else ""
            match_count = match_counts.get(listing.id, 0)
            return f"[{match_count}] {vip}{listing.family_name}"
        if col == 1:
            return listing.phone or ""
        if col == 10:
            return format_datetime(listing.created_at)
        if col == 11:
            return format_datetime(listing.updated_at)

    if role == int(Qt.ItemDataRole.ForegroundRole) and col == 0:
        return cast(object, _theme_colors()["listing_name"])

    if role == int(Qt.ItemDataRole.FontRole) and col == 0:
        font = QFont()
        font.setBold(True)
        return cast(object, font)

    return None


def offer_cell_value(
    offer: Offer,
    col: int,
    role: int,
    *,
    match_counts: dict[int, int],
    tr: Callable[[str], str],
) -> object | None:
    if role == int(Qt.ItemDataRole.DisplayRole):
        if col == 0:
            return "    ->"
        if col == 2:
            match_count = match_counts.get(offer.id, 0)
            type_label = TYPE_LABELS.get(offer.type or "", offer.type or "")
            accessibility = " ♿" if getattr(offer, "accessibility_supported", False) else ""
            return tr("[{count}] {type}{acc}").format(
                count=match_count, type=type_label, acc=accessibility
            )
        if col == 3:
            return ACTION_LABELS.get(offer.action or "", offer.action or "")
        if col == 4:
            wilaya_display = display_wilaya(offer.wilaya)
            location = offer.location or ""
            if location and wilaya_display:
                if norm_text(wilaya_display) not in norm_text(location):
                    return f"{wilaya_display} - {location}"
                return location
            return location or wilaya_display
        if col == 5:
            return str(offer.beds) if offer.beds else ""
        if col == 6:
            return format_number(offer.surface)
        if col == 7:
            return format_budget(offer.budget)
        if col == 8:
            return FURNISHED_LABELS.get(offer.furnished or "", offer.furnished or "")
        if col == 9:
            suffix = tr(" (Elevator)") if offer.elevator else ""
            return f"{offer.floor}{suffix}"
        if col == 10:
            return format_datetime(offer.created_at)
        if col == 11:
            return format_datetime(offer.updated_at)

    if role == int(Qt.ItemDataRole.ForegroundRole) and col == 0:
        return cast(object, _theme_colors()["offer_arrow"])

    return None


__all__ = ["listing_cell_value", "offer_cell_value"]
