from __future__ import annotations

CLIENT_FIELD_KEYS: tuple[str, ...] = (
    "family_name",
    "phone",
    "remarks",
    "is_vip",
    "status",
    "tags",
)

LISTING_FIELD_KEYS: tuple[str, ...] = (
    "family_name",
    "phone",
    "remarks",
    "is_vip",
    "status",
)

DEMANDE_FIELD_KEYS: tuple[str, ...] = (
    "client_id",
    "action",
    "type",
    "wilaya",
    "locations",
    "budget_min",
    "budget_max",
    "surface_min",
    "surface_max",
    "beds_min",
    "floor_min",
    "floor_max",
    "furnished",
    "elevator",
    "accessibility_required",
    "remarks",
    "tags",
)

OFFER_FIELD_KEYS: tuple[str, ...] = (
    "listing_id",
    "action",
    "type",
    "status",
    "wilaya",
    "location",
    "budget",
    "surface",
    "beds",
    "floor",
    "furnished",
    "elevator",
    "accessibility_supported",
    "price_negotiable",
    "price_flex_pct",
    "remarks",
    "link",
    "latitude",
    "longitude",
)


__all__ = [
    "CLIENT_FIELD_KEYS",
    "DEMANDE_FIELD_KEYS",
    "LISTING_FIELD_KEYS",
    "OFFER_FIELD_KEYS",
]
