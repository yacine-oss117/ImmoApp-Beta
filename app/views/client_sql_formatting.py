"""
Formatting helpers and label maps for ClientSQLModel.
"""

from __future__ import annotations

from app.utils.i18n import tr_factory
from app.views.sql_formatting import format_budget, format_datetime, format_number

_TR = tr_factory("ClientSQLModel")

TYPE_LABELS = {
    "": _TR("Any"),
    "apartment": _TR("Apartment"),
    "house": _TR("House"),
    "business": _TR("Business"),
    "land": _TR("Land"),
    "other": _TR("Other"),
}
ACTION_LABELS = {
    "buy": _TR("Buy"),
    "rent": _TR("Rent"),
}
FURNISHED_LABELS = {
    "any": _TR("Any"),
    "yes": _TR("Yes"),
    "no": _TR("No"),
}

CLIENT_LIST_FIELDS = [
    "id",
    "family_name",
    "phone",
    "is_vip",
    "remarks",
    "created_at",
    "updated_at",
]


def format_client_name(family_name: str, match_count: int, is_vip: bool) -> str:
    vip = _TR("VIP ") if is_vip else ""
    return f"[{match_count}] {vip}{family_name}"


def format_demande_type(type_value: str | None, match_count: int, accessibility: bool) -> str:
    type_label = TYPE_LABELS.get(type_value or "", type_value or _TR("Any"))
    accessibility_tag = " ♿" if accessibility else ""
    return _TR("[{count}] {type}{acc}").format(
        count=match_count,
        type=type_label,
        acc=accessibility_tag,
    )


__all__ = [
    "ACTION_LABELS",
    "CLIENT_LIST_FIELDS",
    "FURNISHED_LABELS",
    "TYPE_LABELS",
    "format_budget",
    "format_client_name",
    "format_datetime",
    "format_demande_type",
    "format_number",
]
