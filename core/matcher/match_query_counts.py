"""
Count query builders for match metrics.
"""

from __future__ import annotations

from collections.abc import Sequence

from core.matcher.match_query_cte import MatchQuery, build_match_cte
from core.matcher.match_query_sql import ACTIVE_CLIENT, ACTIVE_DEMANDE, ACTIVE_LISTING, ACTIVE_OFFER


def build_client_counts_query(
    *,
    client_ids: Sequence[int] | None = None,
    agency_id: int | None = None,
) -> MatchQuery:
    """
    Count distinct offers per client using precomputed match_candidates.

    This is the production-grade path for count queries: avoid full matcher CTE expansion
    and aggregate from the canonical candidate table.
    """
    params: list[object] = []
    filters: list[str] = []

    if client_ids is not None:
        filters.append("d.client_id = ANY(%s)")
        params.append(list(client_ids))
    if agency_id is not None:
        filters.append("d.agency_id = %s")
        params.append(agency_id)

    where_sql = ""
    if filters:
        where_sql = "AND " + " AND ".join(filters)

    sql = f"""
        SELECT d.client_id, COUNT(DISTINCT mc.offer_id) AS match_count
        FROM match_candidates mc
        JOIN demandes d ON d.id = mc.demande_id
        JOIN clients c ON c.id = d.client_id AND {ACTIVE_CLIENT.sql}
        JOIN offers o ON o.id = mc.offer_id AND {ACTIVE_OFFER.sql}
        JOIN listings l ON l.id = o.listing_id AND {ACTIVE_LISTING.sql}
        WHERE {ACTIVE_DEMANDE.sql}
          {where_sql}
        GROUP BY d.client_id
    """
    return MatchQuery(sql=sql, params=params)


def build_single_client_count_query(client_id: int, agency_id: int | None = None) -> MatchQuery:
    """Count distinct offers for a single client via the canonical CTE."""
    cte = build_match_cte(
        client_ids=[client_id], agency_id=agency_id, select_cols="o.id as offer_id"
    )
    sql = f"""
    {cte.sql}
    SELECT COUNT(DISTINCT offer_id) as match_count FROM matched_pairs
    """
    return MatchQuery(sql=sql, params=cte.params)


def build_demande_counts_query(
    demande_ids: Sequence[int] | None = None, agency_id: int | None = None
) -> MatchQuery:
    """Count distinct offers per demande (optionally filtered to specific demandes)."""
    cte = build_match_cte(
        demande_ids=demande_ids,
        agency_id=agency_id,
        select_cols="d.id as demande_id, o.id as offer_id",
    )
    sql = f"""
    {cte.sql}
    SELECT demande_id, COUNT(DISTINCT offer_id) as match_count
    FROM matched_pairs
    GROUP BY demande_id
    """
    return MatchQuery(sql=sql, params=cte.params)


def build_listing_counts_query(
    listing_ids: Sequence[int], agency_id: int | None = None
) -> MatchQuery:
    """Count unique matching demandes per listing via the canonical CTE."""
    cte = build_match_cte(
        listing_ids=listing_ids,
        select_cols="o.listing_id, d.id as demande_id",
    )
    sql = f"""
    {cte.sql}
    SELECT listing_id, COUNT(DISTINCT demande_id) as match_count
    FROM matched_pairs
    GROUP BY listing_id
    """
    return MatchQuery(sql=sql, params=cte.params)


def build_offer_counts_query(offer_ids: Sequence[int], agency_id: int | None = None) -> MatchQuery:
    """Count unique matching demandes per offer via the canonical CTE."""
    cte = build_match_cte(
        offer_ids=offer_ids,
        select_cols="o.id as offer_id, d.id as demande_id",
    )
    sql = f"""
    {cte.sql}
    SELECT offer_id, COUNT(DISTINCT demande_id) as match_count
    FROM matched_pairs
    GROUP BY offer_id
    """
    return MatchQuery(sql=sql, params=cte.params)


def build_wilaya_client_counts_query(wilaya_id: int, agency_id: int | None = None) -> MatchQuery:
    """
    Count distinct matching offers per client for demandes in a specific wilaya.

    IMPORTANT: must NOT use OR-heavy matcher joins here; use match_candidates for speed and consistency
    with cached/precomputed matching. Strict model requires wilaya_id on demandes.
    """
    params: list[object] = [wilaya_id]
    extra_agency = ""
    if agency_id is not None:
        extra_agency = "AND d.agency_id = %s"
        params.append(agency_id)

    sql = f"""
        WITH target_demandes AS (
            SELECT d.id, d.client_id
            FROM demandes d
            JOIN clients c ON c.id = d.client_id AND {ACTIVE_CLIENT.sql}
            WHERE {ACTIVE_DEMANDE.sql}
              AND d.wilaya_id = %s
              {extra_agency}
        )
        SELECT td.client_id, COUNT(DISTINCT mc.offer_id) AS match_count
        FROM target_demandes td
        JOIN match_candidates mc ON mc.demande_id = td.id
        JOIN offers o ON o.id = mc.offer_id AND {ACTIVE_OFFER.sql}
        JOIN listings l ON l.id = o.listing_id AND {ACTIVE_LISTING.sql}
        GROUP BY td.client_id
    """
    return MatchQuery(sql=sql, params=params)


def build_demande_match_count_query(demande_id: int, agency_id: int | None = None) -> MatchQuery:
    """Count matching offers for a single demande via the canonical CTE."""
    cte = build_match_cte(
        demande_ids=[demande_id],
        select_cols="o.id as offer_id",
    )
    sql = f"""
    {cte.sql}
    SELECT COUNT(DISTINCT offer_id) as match_count
    FROM matched_pairs
    """
    return MatchQuery(sql=sql, params=cte.params)


__all__ = [
    "build_client_counts_query",
    "build_demande_counts_query",
    "build_demande_match_count_query",
    "build_listing_counts_query",
    "build_offer_counts_query",
    "build_single_client_count_query",
    "build_wilaya_client_counts_query",
]
