"""
Detail query builders for match results.
"""

from __future__ import annotations

from core.matcher.match_query_cte import MatchQuery, build_match_cte
from core.matcher.match_query_sql import ACTIVE_LISTING


def build_demande_detail_matches_query(demande_id: int, agency_id: int | None = None) -> MatchQuery:
    """Fetch detailed matches for a demande with location flags via the canonical CTE."""
    cte = build_match_cte(
        demande_ids=[demande_id],
        select_cols="d.id as demande_id, o.id as offer_id",
    )

    sql = f"""
    {cte.sql}
    SELECT o.*,
           EXISTS (
               SELECT 1 FROM demande_locations dl
               JOIN offer_locations ol ON dl.location_id = ol.location_id
               WHERE dl.demande_id = mp.demande_id AND ol.offer_id = mp.offer_id
           ) AS has_location_match,
           EXISTS (
               SELECT 1 FROM demande_locations WHERE demande_id = mp.demande_id
           ) AS demande_has_locations
    FROM matched_pairs mp
    JOIN offers o ON o.id = mp.offer_id
    JOIN listings l ON l.id = o.listing_id AND {ACTIVE_LISTING.sql}
    """
    return MatchQuery(sql=sql, params=cte.params)


__all__ = ["build_demande_detail_matches_query"]
