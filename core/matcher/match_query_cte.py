"""
Common CTE builder for matching queries.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from core.matcher.match_query_sql import (
    ACTION_MATCH,
    ACTIVE_CLIENT,
    ACTIVE_DEMANDE,
    ACTIVE_LISTING,
    ACTIVE_OFFER,
    NUMERIC_MATCH,
    TYPE_MATCH_STRICT,
)


@dataclass(frozen=True)
class MatchQuery:
    """SQL query text and parameters for DB execution."""

    sql: str
    params: Sequence[object]


@dataclass(frozen=True)
class _BranchSpec:
    name: str
    type_predicate: str
    offers_join_sql: str
    where_clauses: tuple[str, ...] = field(default_factory=tuple)


def _junction_branch(type_predicate: str) -> _BranchSpec:
    return _BranchSpec(
        name="junction",
        type_predicate=type_predicate,
        offers_join_sql=(
            "JOIN offers o ON ol.offer_id = o.id "
            "AND o.agency_id = d.agency_id "
            "AND " + ACTIVE_OFFER.sql
        ),
        where_clauses=(),
    )


def _wilaya_branch(type_predicate: str) -> _BranchSpec:
    return _BranchSpec(
        name="wilaya",
        type_predicate=type_predicate,
        offers_join_sql=(
            "JOIN offers o ON d.wilaya_id = o.wilaya_id "
            "AND o.agency_id = d.agency_id "
            "AND " + ACTIVE_OFFER.sql
        ),
        where_clauses=(
            "NOT EXISTS (SELECT 1 FROM demande_locations WHERE demande_id = d.id)",
            "d.wilaya_id IS NOT NULL",
            "d.wilaya_id <> 0",
        ),
    )


def _build_id_filter(
    *,
    client_ids: Sequence[int] | None = None,
    demande_ids: Sequence[int] | None = None,
) -> tuple[str, list[object]]:
    """Build a SQL WHERE filter and params for optional client/demande IDs."""
    if client_ids:
        return "d.client_id = ANY(%s)", [list(client_ids)]
    if demande_ids:
        return "d.id = ANY(%s)", [list(demande_ids)]
    return "1=1", []


def build_match_cte(
    *,
    client_ids: Sequence[int] | None = None,
    demande_ids: Sequence[int] | None = None,
    offer_ids: Sequence[int] | None = None,
    listing_ids: Sequence[int] | None = None,
    include_numeric: bool = True,
    agency_id: int | None = None,
    select_cols: str = "d.client_id, o.id as offer_id",
) -> MatchQuery:
    """
    Build the common CTE SQL for matching demandes to offers.

    Uses a strict 2-branch UNION strategy:
    1. Junction table match (explicit locations)
    2. Wilaya fallback (no locations, wilaya required)
    """
    id_filter, id_params = _build_id_filter(client_ids=client_ids, demande_ids=demande_ids)

    offer_filter = "1=1"
    offer_params: list[object] = []

    if offer_ids:
        offer_filter = "o.id = ANY(%s)"
        offer_params.append(list(offer_ids))
    elif listing_ids:
        offer_filter = "o.listing_id = ANY(%s)"
        offer_params.append(list(listing_ids))

    numeric_predicate = NUMERIC_MATCH.sql if include_numeric else "1=1"
    branch_specs = (
        _junction_branch(TYPE_MATCH_STRICT.sql),
        _wilaya_branch(TYPE_MATCH_STRICT.sql),
    )

    branch_sql_parts: list[str] = []
    params: list[object] = []
    for spec in branch_specs:
        if spec.name == "junction":
            location_joins = """
                JOIN demande_locations dl ON d.id = dl.demande_id
                JOIN offer_locations ol ON dl.location_id = ol.location_id
            """
        else:
            location_joins = ""

        offers_join_sql = spec.offers_join_sql.format(
            numeric_predicate=numeric_predicate,
            offer_filter=offer_filter,
        )
        where_parts = [
            id_filter,
            ACTIVE_DEMANDE.sql,
            *spec.where_clauses,
        ]
        where_parts.extend(
            [
                ACTION_MATCH.sql,
                numeric_predicate,
                offer_filter,
                spec.type_predicate,
            ]
        )

        branch_sql_parts.append(f"""
            SELECT {select_cols}
            FROM demandes d
            JOIN clients c ON c.id = d.client_id AND c.agency_id = d.agency_id AND {ACTIVE_CLIENT.sql}
            {location_joins}
            {offers_join_sql}
            JOIN listings l ON l.id = o.listing_id AND l.agency_id = o.agency_id AND {ACTIVE_LISTING.sql}
            WHERE {" AND ".join(where_parts)}
            """)
        params.extend(id_params)
        params.extend(offer_params)

    branches_sql = "\nUNION ALL\n".join(branch_sql_parts)
    sql = f"""
    WITH raw_pairs AS (
        {branches_sql}
    ),
    matched_pairs AS (
        SELECT DISTINCT * FROM raw_pairs
    )
    """
    return MatchQuery(sql=sql, params=params)


__all__ = ["MatchQuery", "build_match_cte"]
