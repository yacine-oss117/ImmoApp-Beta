"""
Shared SQL helper utilities for read repositories.
"""

from __future__ import annotations

from collections.abc import Sequence

from core.ale_utils import MASK_BIDX_PREFIX
from core.blind_index import blind_index
from core.utils.common import phone_digits


def build_people_search_conditions(
    *,
    search: str,
    person_alias: str,
    join_fields: Sequence[str],
) -> tuple[str, list[object]]:
    """
    Build trigram + LIKE search conditions for people tables (clients/listings).

    Returns a condition string and parameters list. If search is empty,
    returns ("", []).
    """
    if not search:
        return "", []

    # Phone Search Hardening: normalize query digits to match index
    norm_phone = phone_digits(search)
    phone_bidx = MASK_BIDX_PREFIX + blind_index(norm_phone) if norm_phone else ""

    search_lower = f"%{search.lower()}%"
    conditions = [
        f"{person_alias}.family_name_search_idx && immoapp_hash_trigrams(%s)",
        f"{person_alias}.phone_search_idx && immoapp_hash_trigrams(%s)",
        f"{person_alias}.phone = %s",
        f"LOWER({person_alias}.remarks) LIKE %s",
    ]
    conditions.extend(f"LOWER({field}) LIKE %s" for field in join_fields)

    params: list[object] = [search, search, phone_bidx, search_lower]
    params.extend([search_lower] * len(join_fields))

    return "(" + " OR ".join(conditions) + ")", params


def build_like_search_conditions(
    *,
    search: str,
    columns: Sequence[str],
) -> tuple[str, list[str]]:
    """
    Build a simple case-insensitive LIKE search condition over columns.

    Returns a condition string and params. If search is empty, returns ("", []).
    """
    if not search:
        return "", []

    search_lower = f"%{search.lower()}%"
    conditions = [f"LOWER({column}) LIKE %s" for column in columns]
    return "(" + " OR ".join(conditions) + ")", [search_lower] * len(columns)
