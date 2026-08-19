"""
Candidate prefilter storage for matching.
"""

from __future__ import annotations

from collections.abc import Sequence

from core.data.match_cache_utils import chunk_ids
from core.matcher.match_queries import build_match_cte
from core.matcher.ports.db import DbSession
from core.utils.row_casts import row_int


def fetch_candidate_offer_ids(session: DbSession, demande_id: int) -> list[int]:
    """Return offer IDs that satisfy boolean + numeric match constraints.

    Tenant isolation is enforced by PostgreSQL RLS; do not pass/force agency_id here.
    """
    cte = build_match_cte(
        demande_ids=[demande_id],
        select_cols="o.id as offer_id",
    )
    sql = f"""
    {cte.sql}
    SELECT DISTINCT offer_id AS id
    FROM matched_pairs
    """
    rows = session.execute(sql, cte.params).fetchall()
    return [row_int(row, "id") for row in rows]


def replace_candidates(session: DbSession, demande_id: int, offer_ids: Sequence[int]) -> int:
    """Replace stored candidates for a demande and return count."""
    clear_candidates(session, demande_id=demande_id)
    stored = store_candidates(session, demande_id, offer_ids)
    if stored:
        update_visibility_cache(session, demande_id=demande_id)
    return stored


def replace_candidates_from_match_query(session: DbSession, demande_id: int) -> int:
    """Replace candidates for a demande directly from the canonical matcher SQL (DB-side)."""
    counts = replace_candidates_for_demandes_from_match_query(session, [demande_id])
    return int(counts.get(int(demande_id), 0))


def replace_candidates_for_demandes_from_match_query(
    session: DbSession,
    demande_ids: Sequence[int],
) -> dict[int, int]:
    """Replace candidates for multiple demandes using one DB-side match query."""
    normalized_ids = [int(v) for v in demande_ids if int(v) > 0]
    if not normalized_ids:
        return {}

    clear_candidates(session, demande_ids=normalized_ids)
    cte = build_match_cte(
        demande_ids=normalized_ids,
        select_cols="d.agency_id as agency_id, d.id as demande_id, o.id as offer_id",
    )
    sql = f"""
    {cte.sql},
    upsert AS (
        INSERT INTO match_candidates (agency_id, demande_id, offer_id)
        SELECT mp.agency_id, mp.demande_id, mp.offer_id
        FROM matched_pairs mp
        ON CONFLICT (demande_id, offer_id) DO UPDATE
        SET agency_id = EXCLUDED.agency_id,
            created_at = CURRENT_TIMESTAMP
        RETURNING demande_id
    )
    SELECT demande_id, COUNT(*) AS total
    FROM matched_pairs
    GROUP BY demande_id
    """
    rows = session.execute(sql, cte.params).fetchall()
    counts: dict[int, int] = {int(demande_id): 0 for demande_id in normalized_ids}
    for row in rows:
        demande_id = row_int(row, "demande_id")
        if demande_id > 0:
            counts[demande_id] = row_int(row, "total")

    visible_ids = [demande_id for demande_id, total in counts.items() if total > 0]
    if visible_ids:
        update_visibility_cache(session, demande_ids=visible_ids)
    return counts


def replace_candidates_stream(
    session: DbSession,
    demande_id: int,
    offer_ids: Sequence[int],
) -> int:
    """Replace stored candidates for a demande from a pre-chunked list."""
    clear_candidates(session, demande_id=demande_id)
    stored = store_candidates(session, demande_id, offer_ids)
    if stored:
        update_visibility_cache(session, demande_id=demande_id)
    return stored


def store_candidates(session: DbSession, demande_id: int, offer_ids: Sequence[int]) -> int:
    """Store candidate offers for a demande.

    agency_id is derived from the demande parent row.
    """
    if not offer_ids:
        return 0

    for chunk in chunk_ids(list(offer_ids)):
        session.execute(
            """
            INSERT INTO match_candidates (agency_id, demande_id, offer_id)
            SELECT
                d.agency_id,
                d.id,
                src.offer_id
            FROM demandes d
            JOIN UNNEST(%s::bigint[]) AS src(offer_id) ON true
            WHERE d.id = %s
            ON CONFLICT (demande_id, offer_id) DO UPDATE
            SET agency_id = EXCLUDED.agency_id,
                created_at = CURRENT_TIMESTAMP
            """,
            (chunk, demande_id),
        )
    return len(offer_ids)


def update_visibility_cache(
    session: DbSession,
    *,
    demande_id: int | None = None,
    demande_ids: Sequence[int] | None = None,
) -> None:
    """Backfill visibility metadata for match_candidates to avoid RLS subqueries."""
    sql = """
        UPDATE match_candidates mc
        SET demande_visibility = d.visibility,
            offer_visibility = o.visibility,
            demande_owner_user_id = d.owner_user_id,
            offer_owner_user_id = o.owner_user_id
        FROM demandes d, offers o
        WHERE mc.demande_id = d.id
          AND o.id = mc.offer_id
    """
    params: list[object] = []
    normalized_ids = [int(v) for v in (demande_ids or []) if int(v) > 0]
    if normalized_ids:
        sql += " AND mc.demande_id = ANY(%s)"
        params.append(normalized_ids)
    elif demande_id is not None:
        sql += " AND mc.demande_id = %s"
        params.append(demande_id)
    session.execute(sql, params)


def clear_candidates(
    session: DbSession,
    *,
    demande_id: int | None = None,
    demande_ids: Sequence[int] | None = None,
) -> None:
    """Clear candidate entries by demande_id (tenant is enforced by RLS)."""
    sql = "DELETE FROM match_candidates"
    params: list[object] = []
    normalized_ids = [int(v) for v in (demande_ids or []) if int(v) > 0]
    if normalized_ids:
        sql += " WHERE demande_id = ANY(%s)"
        params.append(normalized_ids)
    elif demande_id is not None:
        sql += " WHERE demande_id = %s"
        params.append(demande_id)

    session.execute(sql, params)


def clear_candidates_for_offer(session: DbSession, offer_id: int) -> None:
    """Clear candidate entries for one offer (tenant is enforced by RLS)."""
    normalized_id = int(offer_id)
    if normalized_id <= 0:
        return
    session.execute("DELETE FROM match_candidates WHERE offer_id = %s", (normalized_id,))


__all__ = [
    "fetch_candidate_offer_ids",
    "replace_candidates",
    "replace_candidates_from_match_query",
    "replace_candidates_for_demandes_from_match_query",
    "replace_candidates_stream",
    "store_candidates",
    "update_visibility_cache",
    "clear_candidates",
    "clear_candidates_for_offer",
]
