"""
Read operations for offers.
"""

from __future__ import annotations

from core.matcher.ports.db import DbSession
from core.models import Offer
from core.models_cast import as_int, row_at
from core.utils.row_casts import row_int


def get_offer_by_id(
    session: DbSession,
    offer_id: int,
    include_deleted: bool = False,
) -> Offer | None:
    """Fetch a single offer by ID."""
    query = """
        SELECT o.* FROM offers o
        JOIN listings l ON o.listing_id = l.id
        WHERE o.id = %s
    """
    params: list[object] = [offer_id]

    if not include_deleted:
        query += " AND o.deleted_at IS NULL"

    row = session.execute(query, params).fetchone()
    return Offer.from_row(row) if row else None


def get_offers_for_listing(
    session: DbSession,
    listing_id: int,
    limit: int | None = None,
    offset: int = 0,
    include_deleted: bool = False,
) -> list[Offer]:
    """
    Fetch all offers for a listing (with optional pagination).
    """
    query = """
        SELECT o.* FROM offers o
        JOIN listings l ON o.listing_id = l.id
        WHERE o.listing_id = %s
    """
    params: list[object] = [listing_id]

    if not include_deleted:
        query += " AND o.deleted_at IS NULL"
    query += " ORDER BY o.id"

    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])

    rows = session.execute(query, params).fetchall()
    return [Offer.from_row(row) for row in rows]


def count_offers_for_listing(session: DbSession, listing_id: int) -> int:
    """Count the number of offers for a listing."""
    query = """
        SELECT COUNT(*) FROM offers o
        JOIN listings l ON o.listing_id = l.id
        WHERE o.listing_id = %s AND o.deleted_at IS NULL
    """
    params: list[object] = [listing_id]
    row = session.execute(query, params).fetchone()
    return as_int(row_at(row, 0)) if row else 0


def fetch_deleted_offers(
    session: DbSession,
    limit: int | None = None,
    offset: int = 0,
) -> list[Offer]:
    """Fetch soft-deleted offers for trash management."""
    query = """
        SELECT o.* FROM offers o
        JOIN listings l ON o.listing_id = l.id
        WHERE o.deleted_at IS NOT NULL
    """
    params: list[object] = []

    query += " ORDER BY o.deleted_at DESC"
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])
    rows = session.execute(query, params).fetchall()
    return [Offer.from_row(row) for row in rows]


def get_total_deleted_offer_count(session: DbSession) -> int:
    """Get total number of deleted offers for pagination."""
    query = """
        SELECT COUNT(*) FROM offers o
        JOIN listings l ON o.listing_id = l.id
        WHERE o.deleted_at IS NOT NULL
    """
    params: list[object] = []

    row = session.execute(query, params).fetchone()
    return as_int(row_at(row, 0)) if row else 0


def get_total_offer_count(session: DbSession) -> int:
    """Get the total number of offers in the system."""
    query = """
        SELECT COUNT(*) FROM offers o
        JOIN listings l ON o.listing_id = l.id
        WHERE o.deleted_at IS NULL
    """
    params: list[object] = []

    row = session.execute(query, params).fetchone()
    return as_int(row_at(row, 0)) if row else 0


def get_offer_ids_for_listing(
    session: DbSession,
    listing_id: int,
    *,
    include_deleted: bool,
) -> list[int]:
    """Return offer IDs for a listing in stable ID order."""
    sql = "SELECT o.id FROM offers o WHERE o.listing_id = %s"
    params: list[object] = [listing_id]
    if not include_deleted:
        sql += " AND o.deleted_at IS NULL"
    sql += " ORDER BY o.id"
    rows = session.execute(sql, params).fetchall()
    return [row_int(row, "id") for row in rows]


def get_offer_wilaya_ids_for_listing(
    session: DbSession,
    listing_id: int,
    *,
    include_deleted: bool,
) -> set[int]:
    """Return distinct non-zero wilaya IDs referenced by a listing's offers."""
    sql = """
        SELECT DISTINCT o.wilaya_id
        FROM offers o
        WHERE o.listing_id = %s
          AND o.wilaya_id IS NOT NULL AND o.wilaya_id <> 0
    """
    params: list[object] = [listing_id]
    if not include_deleted:
        sql += " AND o.deleted_at IS NULL"
    rows = session.execute(sql, params).fetchall()
    result: set[int] = set()
    for row in rows:
        wilaya_id = row_int(row, "wilaya_id")
        if wilaya_id > 0:
            result.add(wilaya_id)
    return result
