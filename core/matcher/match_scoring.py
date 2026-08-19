"""
Match scoring and demande summary formatting.

Kept separate to keep match_counter.py focused on query execution.
"""

from __future__ import annotations

import re

from core.models_demande import Demande
from core.models_offer import Offer
from core.utils.common import display_wilaya, fmt_money_range, fmt_money_short, norm_text


def calculate_score(
    demande: Demande,
    offer: Offer,
    has_location_match: bool,
    demande_has_locations: bool,
) -> float:
    """Calculate match quality score (0-10 scale)."""
    score = 0.0

    d_type = norm_text(demande.type)
    o_type = norm_text(offer.type)
    if not d_type or not o_type or d_type == o_type:
        score += 2.0

    if demande_has_locations:
        if has_location_match:
            score += 2.0
    else:
        score += 1.0

    if demande.budget_max and offer.budget:
        if offer.budget <= demande.budget_max:
            gap_ratio = 1 - (offer.budget / demande.budget_max)
            score += min(2.0, gap_ratio * 4)

    if demande.surface_min and offer.surface:
        if offer.surface >= demande.surface_min:
            extra = (offer.surface - demande.surface_min) / max(1, demande.surface_min)
            score += min(2.0, extra * 2)

    if demande.beds_min and offer.beds:
        if offer.beds >= demande.beds_min:
            score += min(1.0, (offer.beds - demande.beds_min) * 0.3)

    if demande.furnished and offer.furnished:
        if norm_text(demande.furnished) not in ("", "any"):
            if norm_text(demande.furnished) == norm_text(offer.furnished):
                score += 1.0

    return round(min(score, 10.0), 2)


def calculate_value_score_raw(demande: Demande, offer: Offer) -> float:
    """Return a raw value score (higher is better) for ranking matched offers."""
    surface = float(offer.surface or 0.0)
    beds = float(offer.beds or 0.0)
    budget = float(offer.budget or 0.0)

    value = 0.0
    if surface > 0.0 and budget > 0.0:
        value += (surface / budget) * 1_000_000.0
    value += surface
    value += beds * 10.0
    return value


def _coerce_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(" ", "")
    match = re.search(r"-?\d+(?:[.,]\d+)?", s)
    if not match:
        return None
    raw = match.group(0)
    if "," in raw and "." in raw:
        raw = raw.replace(",", "")
    elif "," in raw and "." not in raw:
        parts = raw.split(",")
        if len(parts[-1]) == 3:
            raw = "".join(parts)
        else:
            raw = raw.replace(",", ".")
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


def _fmt_num(value: object) -> str:
    num = _coerce_number(value)
    if num is None:
        return ""
    return f"{num:,.0f}".replace(",", " ")


def format_demande_summary(demande: Demande) -> str:
    """Create human-readable demande summary."""
    parts: list[str] = []

    if demande.type:
        parts.append(demande.type.capitalize())

    if demande.locations:
        parts.append(f"in {demande.locations}")
    elif demande.wilaya:
        parts.append(f"in {display_wilaya(demande.wilaya)}")

    if demande.action:
        parts.append(demande.action.capitalize())

    budget_min = demande.budget_min or 0
    budget_max = demande.budget_max or 0
    if budget_min or budget_max:
        if budget_min and budget_max:
            parts.append(f"budget {fmt_money_range(budget_min, budget_max)} DZD")
        elif budget_min:
            parts.append(f"budget >= {fmt_money_short(budget_min)} DZD")
        else:
            parts.append(f"budget <= {fmt_money_short(budget_max)} DZD")

    surface_min = demande.surface_min or 0
    surface_max = demande.surface_max or 0
    if surface_min or surface_max:
        if surface_min and surface_max:
            parts.append(f"surface {_fmt_num(surface_min)}-{_fmt_num(surface_max)}m2")
        elif surface_min:
            parts.append(f"surface >= {_fmt_num(surface_min)}m2")
        else:
            parts.append(f"surface <= {_fmt_num(surface_max)}m2")

    if demande.beds_min and demande.beds_min > 0:
        parts.append(f"{demande.beds_min}+ beds")

    floor_min = demande.floor_min or 0
    floor_max = demande.floor_max if demande.floor_max is not None else 100
    if floor_min > 0 or (floor_max and floor_max < 100):
        if floor_min > 0 and floor_max < 100:
            parts.append(f"floor {floor_min}-{floor_max}")
        elif floor_min > 0:
            parts.append(f"floor >= {floor_min}")
        else:
            parts.append(f"floor <= {floor_max}")

    if demande.elevator:
        parts.append("elevator")

    furnished = norm_text(demande.furnished)
    if furnished and furnished not in ("any", ""):
        parts.append(f"furnished {demande.furnished}")

    return " | ".join(parts) if parts else "Any property"
