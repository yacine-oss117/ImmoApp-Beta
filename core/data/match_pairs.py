"""
Precomputed match pair storage.
"""

from __future__ import annotations

from collections.abc import Sequence

from core.matcher.match_query_sql import ACTIVE_LISTING, ACTIVE_OFFER
from core.matcher.match_scoring_sql import SCORE_SQL
from core.matcher.ports.db import DbSession
from core.models_cast import as_int


def replace_pairs(session: DbSession, demande_id: int, pairs: Sequence[tuple[int, float]]) -> int:
    """Replace precomputed matches for a demande with ranked pairs."""
    clear_pairs(session, demande_id=demande_id)
    stored = store_pairs(session, demande_id, pairs)
    if stored:
        update_visibility_cache(session, demande_id=demande_id)
    return stored


def store_pairs(session: DbSession, demande_id: int, pairs: Sequence[tuple[int, float]]) -> int:
    """Store match pairs for a demande, assigning ranks by order.

    agency_id is derived from the demande parent row.
    """
    if not pairs:
        return 0

    ranked = [
        (demande_id, offer_id, score, rank) for rank, (offer_id, score) in enumerate(pairs, start=1)
    ]

    chunk_size = 900
    for i in range(0, len(ranked), chunk_size):
        batch = ranked[i : i + chunk_size]
        session.executemany(
            """
            INSERT INTO match_pairs (agency_id, demande_id, offer_id, score, rank)
            SELECT d.agency_id, %s, %s, %s, %s
            FROM demandes d
            WHERE d.id = %s
            ON CONFLICT (demande_id, offer_id) DO UPDATE
            SET agency_id = EXCLUDED.agency_id,
                score = EXCLUDED.score,
                rank = EXCLUDED.rank,
                computed_at = CURRENT_TIMESTAMP
            """,
            [
                (demande_id, offer_id, score, rank, demande_id)
                for demande_id, offer_id, score, rank in batch
            ],
        )

    return len(ranked)


def update_visibility_cache(
    session: DbSession,
    *,
    demande_id: int | None = None,
    demande_ids: Sequence[int] | None = None,
) -> None:
    """Backfill visibility metadata for match_pairs to avoid RLS subqueries."""
    sql = """
        UPDATE match_pairs mp
        SET demande_visibility = d.visibility,
            offer_visibility = o.visibility,
            demande_owner_user_id = d.owner_user_id,
            offer_owner_user_id = o.owner_user_id
        FROM demandes d, offers o
        WHERE mp.demande_id = d.id
          AND o.id = mp.offer_id
    """
    params: list[object] = []
    normalized_ids = [int(v) for v in (demande_ids or []) if int(v) > 0]
    if normalized_ids:
        sql += " AND mp.demande_id = ANY(%s)"
        params.append(normalized_ids)
    elif demande_id is not None:
        sql += " AND mp.demande_id = %s"
        params.append(demande_id)
    session.execute(sql, params)


def clear_pairs(
    session: DbSession,
    *,
    demande_id: int | None = None,
    demande_ids: Sequence[int] | None = None,
) -> None:
    """Clear precomputed match pairs by demande_id (tenant is enforced by RLS)."""
    sql = "DELETE FROM match_pairs"
    params: list[object] = []
    normalized_ids = [int(v) for v in (demande_ids or []) if int(v) > 0]
    if normalized_ids:
        sql += " WHERE demande_id = ANY(%s)"
        params.append(normalized_ids)
    elif demande_id is not None:
        sql += " WHERE demande_id = %s"
        params.append(demande_id)
    session.execute(sql, params)


def clear_pairs_for_offer(session: DbSession, offer_id: int) -> None:
    """Clear precomputed match pairs for one offer (tenant is enforced by RLS)."""
    normalized_id = int(offer_id)
    if normalized_id <= 0:
        return
    session.execute("DELETE FROM match_pairs WHERE offer_id = %s", (normalized_id,))


def rebuild_pairs_for_demande_from_candidates_sql(
    session: DbSession,
    demande_id: int,
    *,
    limit: int | None,
) -> tuple[int, int]:
    """
    Rebuild pair cache for one demande using SQL-only scoring/ranking.

    Returns (stored_count, ranked_count).
    """
    stored_total, _ranked_total, per_demande = rebuild_pairs_for_demandes_from_candidates_sql(
        session,
        [demande_id],
        limit=limit,
    )
    stored, ranked = per_demande.get(int(demande_id), (0, 0))
    return as_int(stored, default=as_int(stored_total, default=0)), as_int(ranked, default=0)


def rebuild_pairs_for_demandes_from_candidates_sql(
    session: DbSession,
    demande_ids: Sequence[int],
    *,
    limit: int | None,
) -> tuple[int, int, dict[int, tuple[int, int]]]:
    """Rebuild pair cache for multiple demandes using SQL-only scoring/ranking."""
    normalized_ids = [int(v) for v in demande_ids if int(v) > 0]
    if not normalized_ids:
        return 0, 0, {}

    clear_pairs(session, demande_ids=normalized_ids)
    params: list[object] = [normalized_ids]
    limit_clause = ""
    if limit is not None:
        limit_clause = "WHERE rn <= %s"
        params.append(int(limit))

    sql = f"""
        WITH scored AS (
            SELECT
                mc.demande_id,
                mc.offer_id,
                {SCORE_SQL} AS score
            FROM match_candidates mc
            JOIN demandes d ON d.id = mc.demande_id
            JOIN offers o ON o.id = mc.offer_id AND {ACTIVE_OFFER.sql}
            JOIN listings l ON l.id = o.listing_id AND {ACTIVE_LISTING.sql}
            WHERE mc.demande_id = ANY(%s)
        ),
        ranked AS (
            SELECT
                demande_id,
                offer_id,
                score,
                ROW_NUMBER() OVER (
                    PARTITION BY demande_id
                    ORDER BY score DESC, offer_id ASC
                ) AS rn
            FROM scored
        ),
        upsert AS (
            INSERT INTO match_pairs (agency_id, demande_id, offer_id, score, rank)
            SELECT d.agency_id, ranked.demande_id, ranked.offer_id, ranked.score, ranked.rn
            FROM ranked
            JOIN demandes d ON d.id = ranked.demande_id
            {limit_clause}
            ON CONFLICT (demande_id, offer_id) DO UPDATE
            SET agency_id = EXCLUDED.agency_id,
                score = EXCLUDED.score,
                rank = EXCLUDED.rank,
                computed_at = CURRENT_TIMESTAMP
            RETURNING demande_id
        ),
        ranked_counts AS (
            SELECT demande_id, COUNT(*) AS ranked_total
            FROM ranked
            GROUP BY demande_id
        ),
        stored_counts AS (
            SELECT demande_id, COUNT(*) AS stored_total
            FROM upsert
            GROUP BY demande_id
        )
        SELECT
            ranked_counts.demande_id,
            ranked_counts.ranked_total,
            COALESCE(stored_counts.stored_total, 0) AS stored_total
        FROM ranked_counts
        LEFT JOIN stored_counts ON stored_counts.demande_id = ranked_counts.demande_id
    """
    rows = session.execute(sql, params).fetchall()

    per_demande: dict[int, tuple[int, int]] = {
        int(demande_id): (0, 0) for demande_id in normalized_ids
    }
    stored_total = 0
    ranked_total = 0
    visible_ids: list[int] = []
    for row in rows:
        demande_id = as_int(row.get("demande_id"), default=0)
        ranked_count = as_int(row.get("ranked_total"), default=0)
        stored_count = as_int(row.get("stored_total"), default=0)
        if demande_id <= 0:
            continue
        per_demande[demande_id] = (stored_count, ranked_count)
        ranked_total += ranked_count
        stored_total += stored_count
        if stored_count > 0:
            visible_ids.append(demande_id)

    if visible_ids:
        update_visibility_cache(session, demande_ids=visible_ids)
    return stored_total, ranked_total, per_demande


def find_demande_ids_missing_pairs(session: DbSession, *, limit: int = 200) -> list[int]:
    """Find demandes that have candidates but no stored pairs."""
    rows = session.execute(
        """
        SELECT mc.demande_id
        FROM match_candidates mc
        WHERE NOT EXISTS (
            SELECT 1 FROM match_pairs mp WHERE mp.demande_id = mc.demande_id
        )
        GROUP BY mc.demande_id
        LIMIT %s
        """,
        (int(limit),),
    ).fetchall()
    return [as_int(row.get("demande_id"), default=0) for row in rows if row]


def fetch_pairs(
    session: DbSession,
    demande_id: int,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, object]]:
    """Fetch stored match pairs for a demande (tenant enforced by RLS)."""
    sql = """
        SELECT offer_id, score, rank
        FROM match_pairs
        WHERE demande_id = %s
        ORDER BY score DESC, offer_id ASC
        LIMIT %s OFFSET %s
    """
    rows = session.execute(sql, (demande_id, limit, offset)).fetchall()
    return [dict(row) for row in rows]


def fetch_pairs_with_offers(
    session: DbSession,
    demande_id: int,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, object]]:
    """Fetch stored match pairs joined with offers (tenant enforced by RLS)."""
    sql = f"""
        SELECT o.*, mp.score, mp.rank
        FROM match_pairs mp
        JOIN offers o ON o.id = mp.offer_id AND {ACTIVE_OFFER.sql}
        JOIN listings l ON l.id = o.listing_id AND {ACTIVE_LISTING.sql}
        WHERE mp.demande_id = %s
        ORDER BY mp.score DESC, mp.offer_id ASC
        LIMIT %s OFFSET %s
    """
    rows = session.execute(sql, (demande_id, limit, offset)).fetchall()
    return [dict(row) for row in rows]


def count_pairs_for_demande(session: DbSession, demande_id: int) -> int:
    """Count stored match pairs for a demande (tenant enforced by RLS)."""
    sql = f"""
        SELECT COUNT(*) AS count
        FROM match_pairs mp
        JOIN offers o ON o.id = mp.offer_id AND {ACTIVE_OFFER.sql}
        JOIN listings l ON l.id = o.listing_id AND {ACTIVE_LISTING.sql}
        WHERE mp.demande_id = %s
    """
    row = session.execute(sql, (demande_id,)).fetchone()
    if not row:
        return 0
    return as_int(row.get("count"), default=0)


__all__ = [
    "replace_pairs",
    "store_pairs",
    "update_visibility_cache",
    "clear_pairs",
    "clear_pairs_for_offer",
    "rebuild_pairs_for_demande_from_candidates_sql",
    "rebuild_pairs_for_demandes_from_candidates_sql",
    "find_demande_ids_missing_pairs",
    "fetch_pairs",
    "fetch_pairs_with_offers",
    "count_pairs_for_demande",
]
