"""Structured SQL fragments for match queries."""

from __future__ import annotations

from core.utils.sql_fragments import SqlFragment, and_all

ACTION_ID_BUY = 1
ACTION_ID_RENT = 2
ACTION_ID_SELL = 3

# STRICT: Index-friendly equality
TYPE_MATCH_STRICT = SqlFragment("d.type_id = o.type_id")

# Strict-only matching (no wildcard type support in this phase)
TYPE_MATCH = TYPE_MATCH_STRICT


ACTION_MATCH = SqlFragment(
    # Rewrite OR into a single equality to stay index-friendly.
    # Demand BUY matches Offer SELL; Demand RENT matches Offer RENT.
    f"""o.action_id = CASE
            WHEN d.action_id = {ACTION_ID_BUY}  THEN {ACTION_ID_SELL}
            WHEN d.action_id = {ACTION_ID_RENT} THEN {ACTION_ID_RENT}
            ELSE NULL
        END"""
)

ACTIVE_CLIENT = SqlFragment("c.status = 'active' AND c.deleted_at IS NULL")
ACTIVE_LISTING = SqlFragment("l.status = 'available' AND l.deleted_at IS NULL")
ACTIVE_DEMANDE = SqlFragment("d.deleted_at IS NULL")
ACTIVE_OFFER = SqlFragment("o.status = 'available' AND o.deleted_at IS NULL")

# Numeric Matching using Range Overlaps
# 1. Price/Budget: Overlap (&&) since price is a range (negotiable) and budget is a range
# 2. Surface: Listing surface (point) must be within Demande surface range
# 3. Beds: Listing beds (point) must be within Demande beds range
NUMERIC_MATCH = SqlFragment("""
    (o.price_range && d.budget_range)
    AND (o.surface::numeric <@ d.surface_range)
    AND (o.beds <@ d.beds_range)
    AND (
        d.floor_min IS NULL
        AND d.floor_max IS NULL
        OR (COALESCE(o.floor, 0) BETWEEN COALESCE(d.floor_min, 0) AND COALESCE(d.floor_max, 100))
    )

    AND (d.elevator IS NULL OR o.elevator = 1)
    AND (d.accessibility_required IS NULL OR o.accessibility_supported = 1)
    """)


COMMON_MATCH = and_all([TYPE_MATCH, ACTION_MATCH, NUMERIC_MATCH])

LOCATION_MATCH = SqlFragment("""
    (
        EXISTS (
            SELECT 1
            FROM demande_locations dl
            JOIN offer_locations ol ON dl.location_id = ol.location_id
            WHERE dl.demande_id = d.id AND ol.offer_id = o.id
        )
        OR
        (
            NOT EXISTS (SELECT 1 FROM demande_locations WHERE demande_id = d.id)
            AND o.wilaya_id = d.wilaya_id
        )
    )
    """)


__all__ = [
    "ACTION_ID_BUY",
    "ACTION_ID_RENT",
    "ACTION_ID_SELL",
    "TYPE_MATCH",
    "TYPE_MATCH_STRICT",
    "ACTION_MATCH",
    "ACTIVE_CLIENT",
    "ACTIVE_LISTING",
    "ACTIVE_DEMANDE",
    "ACTIVE_OFFER",
    "NUMERIC_MATCH",
    "COMMON_MATCH",
    "LOCATION_MATCH",
]
