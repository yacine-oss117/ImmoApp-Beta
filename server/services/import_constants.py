"""
Importer domain constants and validation helpers.
"""

from __future__ import annotations

DUPLICATE_STRATEGY_ALLOW_ALL = "allow_all"
DUPLICATE_STRATEGY_SKIP = "skip"
DUPLICATE_STRATEGY_REVIEW = "review"

ALLOWED_DUPLICATE_STRATEGIES = (
    DUPLICATE_STRATEGY_ALLOW_ALL,
    DUPLICATE_STRATEGY_SKIP,
    DUPLICATE_STRATEGY_REVIEW,
)

ENTITY_TYPE_CLIENT = "client"
ENTITY_TYPE_LISTING = "listing"
ENTITY_TYPE_DEMANDE = "demande"
ENTITY_TYPE_OFFER = "offer"

ALLOWED_ENTITY_TYPES = (
    ENTITY_TYPE_CLIENT,
    ENTITY_TYPE_LISTING,
    ENTITY_TYPE_DEMANDE,
    ENTITY_TYPE_OFFER,
)


def normalize_duplicate_strategy(value: str | None) -> str:
    strategy = (value or DUPLICATE_STRATEGY_SKIP).strip().lower()
    if strategy not in ALLOWED_DUPLICATE_STRATEGIES:
        return DUPLICATE_STRATEGY_SKIP
    return strategy


def normalize_entity_type(value: str | None) -> str:
    entity = (value or ENTITY_TYPE_CLIENT).strip().lower()
    if entity not in ALLOWED_ENTITY_TYPES:
        return ENTITY_TYPE_CLIENT
    return entity


__all__ = [
    "ALLOWED_DUPLICATE_STRATEGIES",
    "ALLOWED_ENTITY_TYPES",
    "DUPLICATE_STRATEGY_ALLOW_ALL",
    "DUPLICATE_STRATEGY_REVIEW",
    "DUPLICATE_STRATEGY_SKIP",
    "ENTITY_TYPE_CLIENT",
    "ENTITY_TYPE_LISTING",
    "ENTITY_TYPE_DEMANDE",
    "ENTITY_TYPE_OFFER",
    "normalize_duplicate_strategy",
    "normalize_entity_type",
]
