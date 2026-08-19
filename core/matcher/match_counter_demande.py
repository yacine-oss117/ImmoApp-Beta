"""
Per-demande match count helpers.
"""

from __future__ import annotations

from core.matcher.match_query_sql import ACTIVE_DEMANDE, ACTIVE_LISTING, ACTIVE_OFFER
from core.matcher.ports.db import DbSession
from core.utils.row_casts import row_int


def _count_for_demande_fast(session: DbSession, demande_id: int) -> int:
    """Count matching offers for a single demande using junction tables (O(log n))."""
    sql = f"""
        SELECT COUNT(DISTINCT mc.offer_id) AS match_count
        FROM match_candidates mc
        JOIN offers o ON o.id = mc.offer_id AND {ACTIVE_OFFER.sql}
        JOIN listings l ON l.id = o.listing_id AND {ACTIVE_LISTING.sql}
        JOIN demandes d ON d.id = mc.demande_id
        WHERE mc.demande_id = %s
          AND {ACTIVE_DEMANDE.sql}
    """
    result = session.execute(sql, [demande_id]).fetchone()
    return row_int(result, "match_count") if result else 0


def count_matches_per_demande(session: DbSession, client_id: int) -> dict[int, int]:
    """
    Get match count for each demande of a client.
    """
    demande_ids = [
        row_int(row, "id")
        for row in session.execute(
            "SELECT d.id FROM demandes d WHERE d.client_id = %s AND d.deleted_at IS NULL",
            (client_id,),
        ).fetchall()
    ]
    return {did: _count_for_demande_fast(session, did) for did in demande_ids}


def get_all_demande_match_counts(session: DbSession) -> dict[int, int]:
    """Get match counts for ALL demandes in one batch operation."""
    from core.matcher.match_counter_batch import batch_count_all_demandes_cte

    return batch_count_all_demandes_cte(session)


__all__ = ["count_matches_per_demande", "get_all_demande_match_counts"]
