"""
Batch count operations for match caches.
"""

from __future__ import annotations

import logging

from core.matcher.match_counter_helpers import (
    count_clients_for_ids,
    count_demandes_for_ids,
    count_listings_for_ids,
    count_offers_for_ids,
)
from core.matcher.match_query_sql import (
    ACTIVE_CLIENT,
    ACTIVE_DEMANDE,
    ACTIVE_LISTING,
    ACTIVE_OFFER,
)
from core.matcher.ports.db import DbSession
from core.utils.row_casts import row_int

logger = logging.getLogger(__name__)


def batch_count_clients_paginated(
    session: DbSession,
    client_ids: list[int],
) -> dict[int, int]:
    """
    Count matches for a SPECIFIC list of clients (e.g., the current page).
    Uses junction tables with wilaya fallback for consistency with canonical CTEs.
    """
    if not client_ids:
        return {}
    return count_clients_for_ids(session, client_ids)


def batch_count_all_clients_cte(session: DbSession) -> dict[int, int]:
    """
    Count matches for ALL clients (used for background cache population).
    Warning: Slow if density is high without pagination.
    """
    sql = f"""
        SELECT d.client_id, COUNT(DISTINCT mc.offer_id) AS match_count
        FROM match_candidates mc
        JOIN offers o ON o.id = mc.offer_id AND {ACTIVE_OFFER.sql}
        JOIN listings l ON l.id = o.listing_id AND {ACTIVE_LISTING.sql}
        JOIN demandes d ON d.id = mc.demande_id
        JOIN clients c ON c.id = d.client_id AND {ACTIVE_CLIENT.sql}
        WHERE {ACTIVE_DEMANDE.sql}
        GROUP BY d.client_id
    """
    result = session.execute(sql).fetchall()
    return {row_int(row, "client_id"): row_int(row, "match_count") for row in result}


def batch_count_listings_paginated(
    session: DbSession,
    listing_ids: list[int],
) -> dict[int, int]:
    """
    Count unique matching demandes for a list of listings (owners).
    Returns dict of {listing_id: match_count}.
    """
    if not listing_ids:
        return {}
    return count_listings_for_ids(session, listing_ids)


def batch_count_all_listings_cte(session: DbSession) -> dict[int, int]:
    """
    Count matches for ALL active listings in a single grouped query.
    Includes active listings with zero matches.
    """
    sql = f"""
        SELECT l.id AS listing_id, COUNT(DISTINCT mc.demande_id) AS match_count
        FROM listings l
        LEFT JOIN offers o
            ON o.listing_id = l.id
           AND {ACTIVE_OFFER.sql}
        LEFT JOIN match_candidates mc
            ON mc.offer_id = o.id
        WHERE {ACTIVE_LISTING.sql}
        GROUP BY l.id
        ORDER BY l.id
    """
    result = session.execute(sql).fetchall()
    return {row_int(row, "listing_id"): row_int(row, "match_count") for row in result}


def count_offers_by_ids(
    session: DbSession,
    offer_ids: list[int],
) -> dict[int, int]:
    """
    Count unique matching demandes for a list of offers.
    Returns dict of {offer_id: match_count}.
    """
    if not offer_ids:
        return {}
    return count_offers_for_ids(session, offer_ids)


def batch_count_all_offers_cte(session: DbSession) -> dict[int, int]:
    """
    Count matches for ALL active offers in a single grouped query.
    Includes active offers with zero matches.
    """
    sql = f"""
        SELECT o.id AS offer_id,
               COUNT(DISTINCT CASE WHEN l.id IS NOT NULL THEN mc.demande_id END) AS match_count
        FROM offers o
        LEFT JOIN listings l
            ON l.id = o.listing_id
           AND {ACTIVE_LISTING.sql}
        LEFT JOIN match_candidates mc
            ON mc.offer_id = o.id
        WHERE {ACTIVE_OFFER.sql}
        GROUP BY o.id
        ORDER BY o.id
    """
    result = session.execute(sql).fetchall()
    return {row_int(row, "offer_id"): row_int(row, "match_count") for row in result}


def count_single_client_cte(session: DbSession, client_id: int) -> int:
    """
    Count matches for a SINGLE client using CTE (canonical engine).

    Uses indexed junction table lookups for O(log n) performance.
    """
    try:
        counts = count_clients_for_ids(session, [client_id])
        return counts.get(client_id, 0)
    except Exception as exc:
        logger.error("Single client count failed for %s", client_id, exc_info=True)
        raise RuntimeError(f"Single client count failed for {client_id}") from exc


def count_clients_in_wilaya_cte(session: DbSession, wilaya_id: int | None) -> dict[int, int]:
    """
    Count matches for ALL clients with demandes in a specific wilaya.

    Strict model: wilaya is mandatory on demandes, so no NULL-wilaya fallback.
    """
    if not wilaya_id:
        return {}

    sql = f"""
        WITH target_demandes AS (
            SELECT d.id, d.client_id
            FROM demandes d
            JOIN clients c ON c.id = d.client_id AND {ACTIVE_CLIENT.sql}
            WHERE {ACTIVE_DEMANDE.sql}
              AND d.wilaya_id = %s

        )
        SELECT td.client_id, COUNT(DISTINCT mc.offer_id) AS match_count
        FROM target_demandes td
        JOIN match_candidates mc ON mc.demande_id = td.id
        JOIN offers o ON o.id = mc.offer_id AND {ACTIVE_OFFER.sql}
        JOIN listings l ON l.id = o.listing_id AND {ACTIVE_LISTING.sql}
        GROUP BY td.client_id
    """
    params = [wilaya_id]
    try:
        result = session.execute(sql, params).fetchall()
        return {row_int(row, "client_id"): row_int(row, "match_count") for row in result}
    except Exception as exc:
        logger.error("Wilaya count failed for %s", wilaya_id, exc_info=True)
        raise RuntimeError(f"Wilaya count failed for {wilaya_id}") from exc


def batch_count_all_demandes_cte(session: DbSession) -> dict[int, int]:
    """
    Count matches for ALL demandes in a SINGLE CTE query.
    """
    sql = f"""
        SELECT mc.demande_id, COUNT(DISTINCT mc.offer_id) AS match_count
        FROM match_candidates mc
        JOIN offers o ON o.id = mc.offer_id AND {ACTIVE_OFFER.sql}
        JOIN listings l ON l.id = o.listing_id AND {ACTIVE_LISTING.sql}
        JOIN demandes d ON d.id = mc.demande_id
        WHERE {ACTIVE_DEMANDE.sql}
        GROUP BY mc.demande_id
    """
    try:
        result = session.execute(sql).fetchall()
        return {row_int(row, "demande_id"): row_int(row, "match_count") for row in result}
    except Exception as exc:
        logger.error("Demande batch count failed", exc_info=True)
        raise RuntimeError("Demande batch count failed") from exc


def count_demandes_by_ids(
    session: DbSession,
    demande_ids: list[int],
) -> dict[int, int]:
    """
    Count matches for a list of demandes using the canonical CTE logic.
    Returns dict of {demande_id: match_count} (distinct offers).
    """
    if not demande_ids:
        return {}
    return count_demandes_for_ids(session, demande_ids)


__all__ = [
    "batch_count_all_clients_cte",
    "batch_count_all_demandes_cte",
    "batch_count_all_listings_cte",
    "batch_count_all_offers_cte",
    "batch_count_clients_paginated",
    "batch_count_listings_paginated",
    "count_clients_in_wilaya_cte",
    "count_demandes_by_ids",
    "count_offers_by_ids",
    "count_single_client_cte",
]
