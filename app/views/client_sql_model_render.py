"""
Render helpers for ClientSQLModel cells.
"""

from __future__ import annotations

from functools import lru_cache
from typing import cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

from app.models import Client, Demande
from app.ui.theme_manager import current_theme
from app.ui.theme_tokens import get_theme_tokens
from app.utils.common import display_wilaya
from app.views.client_sql_formatting import (
    ACTION_LABELS,
    FURNISHED_LABELS,
    format_budget,
    format_client_name,
    format_datetime,
    format_demande_type,
    format_number,
)


@lru_cache(maxsize=2)
def _colors_for_theme(theme_name: str) -> dict[str, QColor]:
    t = get_theme_tokens(theme_name)
    return {
        "client_name": QColor(t["INFO"]),
        "demande_arrow": QColor(t["PRIMARY_HOVER"]),
        "match_high": QColor(t["SUCCESS"]),
        "match_mid": QColor(t["WARNING"]),
        "match_low": QColor(t["STATUS_SCHEDULED"]),
        "match_none": QColor(t["TEXT_DIM"]),
    }


def _theme_colors() -> dict[str, QColor]:
    return _colors_for_theme(current_theme())


def client_cell_value(
    client: Client,
    col: int,
    role: int,
    *,
    match_counts: dict[int, int],
) -> object | None:
    if role == int(Qt.ItemDataRole.DisplayRole):
        if col == 0:
            match_count = match_counts.get(client.id, 0)
            return format_client_name(client.family_name, match_count, client.is_vip)
        if col == 1:
            return client.phone or ""
        if col == 9:
            return format_datetime(client.created_at)
        if col == 10:
            return format_datetime(client.updated_at)
        if col == 11:
            return client.remarks or ""

    if role == int(Qt.ItemDataRole.ForegroundRole) and col == 0:
        return cast(object, _theme_colors()["client_name"])

    if role == int(Qt.ItemDataRole.FontRole) and col == 0:
        font = QFont()
        font.setBold(True)
        return cast(object, font)

    return None


def demande_cell_value(
    demande: Demande,
    col: int,
    role: int,
    *,
    match_counts: dict[int, int],
) -> object | None:
    match_count = match_counts.get(demande.id, 0)

    if role == int(Qt.ItemDataRole.DisplayRole):
        if col == 0:
            return "    ->"
        if col == 2:
            return format_demande_type(
                demande.type,
                match_count,
                getattr(demande, "accessibility_required", False),
            )
        if col == 3:
            return ACTION_LABELS.get(demande.action or "", demande.action or "")
        if col == 4:
            return demande.locations or display_wilaya(demande.wilaya)
        if col == 5:
            return str(demande.beds_min) if demande.beds_min else ""
        if col == 6:
            return format_number(demande.surface_min)
        if col == 7:
            return format_budget(demande.budget_max)
        if col == 8:
            return FURNISHED_LABELS.get(demande.furnished or "", demande.furnished or "")
        if col == 9:
            return format_datetime(demande.created_at)
        if col == 10:
            return format_datetime(demande.updated_at)

    if role == int(Qt.ItemDataRole.ForegroundRole):
        colors = _theme_colors()
        if col == 0:
            return cast(object, colors["demande_arrow"])
        if col == 2:
            if match_count >= 10:
                return cast(object, colors["match_high"])
            if match_count >= 3:
                return cast(object, colors["match_mid"])
            return cast(object, colors["match_low"] if match_count > 0 else colors["match_none"])

    return None


__all__ = ["client_cell_value", "demande_cell_value"]
