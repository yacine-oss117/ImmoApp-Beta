"""
Shared helpers for match counting.
"""

from __future__ import annotations

from collections.abc import Iterable

from core.matcher.match_query_sql import (
    ACTIVE_CLIENT,
    ACTIVE_DEMANDE,
    ACTIVE_LISTING,
    ACTIVE_OFFER,
)
from core.matcher.ports.db import DbSession
from core.utils.row_casts import row_int

_MAX_SQL_PARAMS = 999
_MAX_DIRECT_IDS = _MAX_SQL_PARAMS


def iter_id_chunks(ids: list[int], chunk_size: int) -> Iterable[list[int]]:
    """Yield ID chunks to stay under database parameter limits."""
    for start in range(0, len(ids), chunk_size):
        yield ids[start : start + chunk_size]


def count_clients_for_ids(session: DbSession, client_ids: list[int]) -> dict[int, int]:
    counts = {id_: 0 for id_ in client_ids}
    for chunk in iter_id_chunks(client_ids, _MAX_DIRECT_IDS):
        sql = f"""
            SELECT d.client_id, COUNT(DISTINCT mc.offer_id) AS match_count
            FROM match_candidates mc
            JOIN offers o ON o.id = mc.offer_id AND {ACTIVE_OFFER.sql}
            JOIN listings l ON l.id = o.listing_id AND {ACTIVE_LISTING.sql}
            JOIN demandes d ON d.id = mc.demande_id
            JOIN clients c ON c.id = d.client_id AND {ACTIVE_CLIENT.sql}
            WHERE d.client_id = ANY(%s)
              AND {ACTIVE_DEMANDE.sql}
            GROUP BY d.client_id
        """
        params = [chunk]
        result = session.execute(sql, params).fetchall()
        for row in result:
            counts[row_int(row, "client_id")] = row_int(row, "match_count")
    return counts


def count_demandes_for_ids(session: DbSession, demande_ids: list[int]) -> dict[int, int]:
    counts = {id_: 0 for id_ in demande_ids}
    for chunk in iter_id_chunks(demande_ids, _MAX_DIRECT_IDS):
        sql = f"""
            SELECT mc.demande_id, COUNT(DISTINCT mc.offer_id) AS match_count
            FROM match_candidates mc
            JOIN offers o ON o.id = mc.offer_id AND {ACTIVE_OFFER.sql}
            JOIN listings l ON l.id = o.listing_id AND {ACTIVE_LISTING.sql}
            JOIN demandes d ON d.id = mc.demande_id
            WHERE mc.demande_id = ANY(%s)
              AND {ACTIVE_DEMANDE.sql}
            GROUP BY mc.demande_id
        """
        params = [chunk]
        result = session.execute(sql, params).fetchall()
        for row in result:
            counts[row_int(row, "demande_id")] = row_int(row, "match_count")
    return counts


def count_listings_for_ids(session: DbSession, listing_ids: list[int]) -> dict[int, int]:
    counts = {id_: 0 for id_ in listing_ids}
    for chunk in iter_id_chunks(listing_ids, _MAX_DIRECT_IDS):
        sql = f"""
            SELECT o.listing_id, COUNT(DISTINCT mc.demande_id) AS match_count
            FROM match_candidates mc
            JOIN offers o ON o.id = mc.offer_id
            JOIN listings l ON l.id = o.listing_id AND {ACTIVE_LISTING.sql}
            WHERE o.listing_id = ANY(%s)
              AND {ACTIVE_OFFER.sql}
            GROUP BY o.listing_id
        """
        params = [chunk]
        result = session.execute(sql, params).fetchall()
        for row in result:
            counts[row_int(row, "listing_id")] = row_int(row, "match_count")
    return counts


def count_offers_for_ids(session: DbSession, offer_ids: list[int]) -> dict[int, int]:
    counts = {id_: 0 for id_ in offer_ids}
    for chunk in iter_id_chunks(offer_ids, _MAX_DIRECT_IDS):
        sql = f"""
            SELECT mc.offer_id, COUNT(DISTINCT mc.demande_id) AS match_count
            FROM match_candidates mc
            JOIN offers o ON o.id = mc.offer_id AND {ACTIVE_OFFER.sql}
            JOIN listings l ON l.id = o.listing_id AND {ACTIVE_LISTING.sql}
            WHERE mc.offer_id = ANY(%s)
            GROUP BY mc.offer_id
        """
        params = [chunk]
        result = session.execute(sql, params).fetchall()
        for row in result:
            counts[row_int(row, "offer_id")] = row_int(row, "match_count")
    return counts


__all__ = [
    "_MAX_DIRECT_IDS",
    "count_clients_for_ids",
    "count_demandes_for_ids",
    "count_listings_for_ids",
    "count_offers_for_ids",
    "iter_id_chunks",
]
