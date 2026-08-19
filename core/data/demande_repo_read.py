"""
Read operations for demandes.
"""

from __future__ import annotations

from collections.abc import Iterator

from core.matcher.match_queries import build_match_cte
from core.matcher.ports.db import DbSession
from core.models import Demande
from core.models_cast import as_int, row_at
from core.utils.memory_guard import adaptive_chunk_size
from core.utils.row_casts import row_int


def _id_page_size() -> int:
    return adaptive_chunk_size(floor=100, ceiling=1000)


def get_demande_by_id(
    session: DbSession,
    demande_id: int,
    include_deleted: bool = False,
) -> Demande | None:
    """
    Fetch a single demande by ID.
    """
    query = """
        SELECT d.* FROM demandes d
        WHERE d.id = %s
    """
    params: list[object] = [demande_id]

    if not include_deleted:
        query += " AND d.deleted_at IS NULL"

    row = session.execute(query, params).fetchone()
    return Demande.from_row(row) if row else None


def get_demandes_for_client(
    session: DbSession,
    client_id: int,
    limit: int | None = None,
    offset: int = 0,
    include_deleted: bool = False,
) -> list[Demande]:
    """
    Fetch all demandes for a specific client (with optional pagination).
    """
    query = """
        SELECT d.* FROM demandes d
        WHERE d.client_id = %s
    """
    params: list[object] = [client_id]

    if not include_deleted:
        query += " AND d.deleted_at IS NULL"
    query += " ORDER BY d.id"

    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])

    rows = session.execute(query, params).fetchall()
    return [Demande.from_row(row) for row in rows]


def count_demandes_for_client(session: DbSession, client_id: int) -> int:
    """
    Count the number of demandes for a client.
    """
    query = """
        SELECT COUNT(*) FROM demandes d
        WHERE d.client_id = %s AND d.deleted_at IS NULL
    """
    params: list[object] = [client_id]

    row = session.execute(query, params).fetchone()
    return as_int(row_at(row, 0)) if row else 0


def get_all_demande_counts(session: DbSession) -> dict[int, int]:
    """
    Get demande counts for all clients in one query.
    """
    query = """
        SELECT d.client_id, COUNT(*) as cnt
        FROM demandes d
        WHERE d.deleted_at IS NULL
    """
    params: list[object] = []

    query += " GROUP BY d.client_id"
    rows = session.execute(query, params).fetchall()
    return {row_int(row, "client_id"): row_int(row, "cnt") for row in rows}


def get_total_demande_count(session: DbSession) -> int:
    """Get the total number of demandes in the system."""
    query = """
        SELECT COUNT(*) FROM demandes d
        WHERE d.deleted_at IS NULL
    """
    params: list[object] = []

    row = session.execute(query, params).fetchone()
    return as_int(row_at(row, 0)) if row else 0


def get_all_demandes_grouped(
    session: DbSession,
    limit: int | None = None,
    offset: int = 0,
) -> dict[int, list[Demande]]:
    """
    Get all demandes (with optional pagination), grouped by client_id.
    """
    query = """
        SELECT d.* FROM demandes d
        WHERE d.deleted_at IS NULL
    """
    params: list[object] = []

    query += " ORDER BY d.client_id, d.id"

    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])

    rows = session.execute(query, params).fetchall()

    result: dict[int, list[Demande]] = {}
    for row in rows:
        demande = Demande.from_row(row)
        result.setdefault(demande.client_id, []).append(demande)

    return result


def fetch_deleted_demandes(
    session: DbSession,
    limit: int | None = None,
    offset: int = 0,
) -> list[Demande]:
    """Fetch soft-deleted demandes for trash management."""
    query = """
        SELECT d.* FROM demandes d
        WHERE d.deleted_at IS NOT NULL
    """
    params: list[object] = []

    query += " ORDER BY d.deleted_at DESC"
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])
    rows = session.execute(query, params).fetchall()
    return [Demande.from_row(row) for row in rows]


def get_total_deleted_demande_count(session: DbSession) -> int:
    """Get total number of deleted demandes for pagination."""
    query = """
        SELECT COUNT(*) FROM demandes d
        WHERE d.deleted_at IS NOT NULL
    """
    params: list[object] = []

    row = session.execute(query, params).fetchone()
    return as_int(row_at(row, 0)) if row else 0


def get_demande_ids_for_wilaya(session: DbSession, wilaya_id: int) -> list[int]:
    """Fetch demande IDs filtered by wilaya id."""
    ids: list[int] = []
    for page in iter_demande_ids_for_wilaya(session, wilaya_id, page_size=_id_page_size()):
        ids.extend(page)
    return ids


def iter_demande_ids_for_wilaya(
    session: DbSession,
    wilaya_id: int,
    *,
    page_size: int = 500,
) -> Iterator[list[int]]:
    """Yield demande IDs for a wilaya in bounded pages."""
    if page_size <= 0:
        raise ValueError("page_size must be > 0")
    last_id = 0
    while True:
        rows = session.execute(
            """
                SELECT d.id
                FROM demandes d
                WHERE d.deleted_at IS NULL
                  AND d.wilaya_id = %s
                  AND d.id > %s
                ORDER BY d.id
                LIMIT %s
                """,
            (wilaya_id, int(last_id), int(page_size)),
        ).fetchall()
        if not rows:
            break
        page = [row_int(row, "id") for row in rows]
        if not page:
            break
        last_id = page[-1]
        yield page


def get_demande_ids_for_client(
    session: DbSession,
    client_id: int,
    include_deleted: bool = False,
) -> list[int]:
    """Fetch demande IDs for a client."""
    ids: list[int] = []
    for page in iter_demande_ids_for_client(
        session,
        client_id,
        include_deleted=include_deleted,
        page_size=_id_page_size(),
    ):
        ids.extend(page)
    return ids


def iter_demande_ids_for_client(
    session: DbSession,
    client_id: int,
    *,
    include_deleted: bool = False,
    page_size: int = 500,
) -> Iterator[list[int]]:
    """Yield demande IDs for a client in bounded pages."""
    if page_size <= 0:
        raise ValueError("page_size must be > 0")
    last_id = 0
    while True:
        query = """
            SELECT d.id
            FROM demandes d
            WHERE d.client_id = %s
              AND d.id > %s
        """
        params: list[object] = [client_id, int(last_id)]
        if not include_deleted:
            query += " AND d.deleted_at IS NULL"
        query += " ORDER BY d.id LIMIT %s"
        params.append(int(page_size))
        rows = session.execute(query, params).fetchall()
        if not rows:
            break
        page = [row_int(row, "id") for row in rows]
        if not page:
            break
        last_id = page[-1]
        yield page


def get_demande_ids_for_offer(session: DbSession, offer_id: int) -> list[int]:
    """Fetch demande IDs that could match a specific offer (without numeric filters)."""
    cte = build_match_cte(
        offer_ids=[offer_id],
        include_numeric=False,
        select_cols="d.id as demande_id",
    )
    sql = f"""
    {cte.sql}
    SELECT DISTINCT demande_id AS id
    FROM matched_pairs
    """
    rows = session.execute(sql, cte.params).fetchall()
    return [row_int(row, "id") for row in rows]


def get_demande_ids_for_offers(
    session: DbSession,
    offer_ids: list[int],
) -> dict[int, list[int]]:
    """Fetch demande IDs for multiple offers using adaptive batch sizing.

    Uses precomputed match tables to avoid expensive per-offer CTE rebuilds.
    """
    if not offer_ids:
        return {}

    normalized_offer_ids = sorted({int(offer_id) for offer_id in offer_ids if int(offer_id) > 0})
    if not normalized_offer_ids:
        return {}

    chunk_size = adaptive_chunk_size(floor=50, ceiling=500)
    row_page_size = _id_page_size()
    grouped: dict[int, set[int]] = {}

    for index in range(0, len(normalized_offer_ids), chunk_size):
        batch = normalized_offer_ids[index : index + chunk_size]
        placeholders = ",".join(["%s"] * len(batch))
        sql = f"""
            SELECT offer_id, demande_id
            FROM match_pairs
            WHERE offer_id IN ({placeholders})
            UNION ALL
            SELECT offer_id, demande_id
            FROM match_candidates
            WHERE offer_id IN ({placeholders})
        """
        cursor = session.execute(sql, [*batch, *batch])
        while True:
            rows = cursor.fetchmany(int(row_page_size))
            if not rows:
                break
            for row in rows:
                offer_id = row_int(row, "offer_id")
                demande_id = row_int(row, "demande_id")
                grouped.setdefault(offer_id, set()).add(demande_id)

    return {offer_id: sorted(demande_ids) for offer_id, demande_ids in grouped.items()}


def get_demande_ids_from_precomputed_for_offer(session: DbSession, offer_id: int) -> list[int]:
    """Fetch demande IDs linked to an offer via precomputed tables.

    This helper is used for stale-edge cleanup when an offer/listing is deleted
    and live matching queries may no longer return that offer.
    """
    sql = """
        SELECT DISTINCT demande_id AS id
        FROM (
            SELECT demande_id FROM match_pairs WHERE offer_id = %s
            UNION ALL
            SELECT demande_id FROM match_candidates WHERE offer_id = %s
        ) q
        ORDER BY id
    """
    rows = session.execute(sql, (offer_id, offer_id)).fetchall()
    return [row_int(row, "id") for row in rows]


def get_demande_ids_for_listing(session: DbSession, listing_id: int) -> list[int]:
    """Fetch demande IDs that could match offers for a listing (without numeric filters)."""
    cte = build_match_cte(
        listing_ids=[listing_id],
        include_numeric=False,
        select_cols="d.id as demande_id",
    )
    sql = f"""
    {cte.sql}
    SELECT DISTINCT demande_id AS id
    FROM matched_pairs
    """
    rows = session.execute(sql, cte.params).fetchall()
    return [row_int(row, "id") for row in rows]
