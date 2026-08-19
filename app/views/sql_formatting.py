"""
Shared formatting helpers for SQL-backed views.
"""

from __future__ import annotations

from app.utils.common import fmt_money_short


def format_datetime(dt: object | None) -> str:
    if not dt:
        return ""
    if isinstance(dt, str):
        return dt[:16]
    return dt.strftime("%Y-%m-%d %H:%M") if hasattr(dt, "strftime") else str(dt)


def format_number(value: object) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        num = float(value)
    else:
        try:
            num = float(str(value))
        except (TypeError, ValueError):
            return str(value)
    return f"{num:,.0f}".replace(",", " ")


def format_budget(value: object) -> str:
    if value is None or value == "":
        return ""
    return fmt_money_short(value, "DZD")


__all__ = ["format_budget", "format_datetime", "format_number"]
