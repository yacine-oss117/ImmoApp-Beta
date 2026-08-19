"""
Canonical batch rebuild pipeline for match_candidates and match_pairs.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

from core.matcher.match_queries import build_match_cte
from core.matcher.match_scoring_sql import SCORE_SQL
from core.matcher.ports.db import DbSession
from core.models_cast import as_int


@dataclass(frozen=True)
class MatchArtifactCounts:
    candidate_total: int
    ranked_total: int
    pair_total: int


@dataclass(frozen=True)
class MatchArtifactBatchResult:
    candidate_total: int
    ranked_total: int
    pair_total: int
    per_demande: dict[int, MatchArtifactCounts]


def _normalize_demande_ids(demande_ids: Sequence[int]) -> list[int]:
    return sorted({int(value) for value in (demande_ids or []) if int(value) > 0})


def _rebuild_statement_timeout_ms() -> int:
    raw = os.environ.get("IMMOAPP_MATCH_REBUILD_STATEMENT_TIMEOUT_MS", "120000").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 120000
    return max(1000, value)


def _rebuild_lock_timeout_ms() -> int:
    raw = os.environ.get("IMMOAPP_MATCH_REBUILD_LOCK_TIMEOUT_MS", "5000").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 5000
    return max(250, value)


def _set_rebuild_timeouts(session: DbSession) -> None:
    session.execute(f"SET LOCAL lock_timeout = '{_rebuild_lock_timeout_ms()}ms'")
    session.execute(f"SET LOCAL statement_timeout = '{_rebuild_statement_timeout_ms()}ms'")


def _artifact_insert_query(
    demande_ids: Sequence[int],
    *,
    limit: int | None,
) -> tuple[str, list[object]]:
    normalized_ids = _normalize_demande_ids(demande_ids)
    if not normalized_ids:
        return "", []

    cte = build_match_cte(
        demande_ids=normalized_ids,
        include_numeric=True,
        select_cols="""
            d.agency_id AS agency_id,
            d.id AS demande_id,
            o.id AS offer_id,
            d.visibility AS demande_visibility,
            o.visibility AS offer_visibility,
            d.owner_user_id AS demande_owner_user_id,
            o.owner_user_id AS offer_owner_user_id
        """,
    )
    cte_sql = cte.sql.strip()
    if cte_sql.upper().startswith("WITH "):
        cte_sql = cte_sql[5:]

    params: list[object] = [normalized_ids, *cte.params]
    limit_clause = ""
    if limit is not None:
        limit_clause = "WHERE rn <= %s"
        params.append(int(limit))

    sql = f"""
        WITH target_demandes AS MATERIALIZED (
            SELECT DISTINCT demande_id
            FROM UNNEST(%s::bigint[]) AS src(demande_id)
            WHERE demande_id > 0
        ),
        {cte_sql},
        candidate_insert AS (
            INSERT INTO match_candidates (
                agency_id,
                demande_id,
                offer_id,
                demande_visibility,
                offer_visibility,
                demande_owner_user_id,
                offer_owner_user_id
            )
            SELECT
                mp.agency_id,
                mp.demande_id,
                mp.offer_id,
                mp.demande_visibility,
                mp.offer_visibility,
                mp.demande_owner_user_id,
                mp.offer_owner_user_id
            FROM matched_pairs mp
            RETURNING demande_id
        ),
        candidate_counts AS (
            SELECT mp.demande_id, COUNT(*) AS candidate_total
            FROM matched_pairs mp
            GROUP BY mp.demande_id
        ),
        scored AS (
            SELECT
                mp.agency_id,
                mp.demande_id,
                mp.offer_id,
                mp.demande_visibility,
                mp.offer_visibility,
                mp.demande_owner_user_id,
                mp.offer_owner_user_id,
                {SCORE_SQL} AS score
            FROM matched_pairs mp
            JOIN demandes d ON d.id = mp.demande_id
            JOIN offers o ON o.id = mp.offer_id
            JOIN listings l ON l.id = o.listing_id
        ),
        ranked AS (
            SELECT
                agency_id,
                demande_id,
                offer_id,
                demande_visibility,
                offer_visibility,
                demande_owner_user_id,
                offer_owner_user_id,
                score,
                ROW_NUMBER() OVER (
                    PARTITION BY demande_id
                    ORDER BY score DESC, offer_id ASC
                ) AS rn
            FROM scored
        ),
        pair_insert AS (
            INSERT INTO match_pairs (
                agency_id,
                demande_id,
                offer_id,
                demande_visibility,
                offer_visibility,
                demande_owner_user_id,
                offer_owner_user_id,
                score,
                rank
            )
            SELECT
                agency_id,
                demande_id,
                offer_id,
                demande_visibility,
                offer_visibility,
                demande_owner_user_id,
                offer_owner_user_id,
                score,
                rn
            FROM ranked
            {limit_clause}
            RETURNING demande_id
        ),
        ranked_counts AS (
            SELECT demande_id, COUNT(*) AS ranked_total
            FROM ranked
            GROUP BY demande_id
        ),
        stored_counts AS (
            SELECT demande_id, COUNT(*) AS pair_total
            FROM pair_insert
            GROUP BY demande_id
        )
        SELECT
            td.demande_id,
            COALESCE(cc.candidate_total, 0) AS candidate_total,
            COALESCE(rc.ranked_total, 0) AS ranked_total,
            COALESCE(sc.pair_total, 0) AS pair_total
        FROM target_demandes td
        LEFT JOIN candidate_counts cc ON cc.demande_id = td.demande_id
        LEFT JOIN ranked_counts rc ON rc.demande_id = td.demande_id
        LEFT JOIN stored_counts sc ON sc.demande_id = td.demande_id
        ORDER BY td.demande_id
    """
    return sql, params


def _delete_existing_artifacts(session: DbSession, demande_ids: Sequence[int]) -> None:
    normalized_ids = _normalize_demande_ids(demande_ids)
    if not normalized_ids:
        return
    session.execute(
        "DELETE FROM match_candidates WHERE demande_id = ANY(%s)",
        (normalized_ids,),
    )
    session.execute(
        "DELETE FROM match_pairs WHERE demande_id = ANY(%s)",
        (normalized_ids,),
    )


def rebuild_match_artifacts_for_demandes(
    session: DbSession,
    demande_ids: Sequence[int],
    *,
    limit: int | None,
) -> MatchArtifactBatchResult:
    normalized_ids = _normalize_demande_ids(demande_ids)
    if not normalized_ids:
        return MatchArtifactBatchResult(
            candidate_total=0,
            ranked_total=0,
            pair_total=0,
            per_demande={},
        )

    _set_rebuild_timeouts(session)
    _delete_existing_artifacts(session, normalized_ids)
    sql, params = _artifact_insert_query(normalized_ids, limit=limit)
    rows = session.execute(sql, params).fetchall()

    per_demande: dict[int, MatchArtifactCounts] = {
        demande_id: MatchArtifactCounts(candidate_total=0, ranked_total=0, pair_total=0)
        for demande_id in normalized_ids
    }
    candidate_total = 0
    ranked_total = 0
    pair_total = 0
    for row in rows:
        demande_id = as_int((row or {}).get("demande_id"), default=0)
        if demande_id <= 0:
            continue
        counts = MatchArtifactCounts(
            candidate_total=as_int((row or {}).get("candidate_total"), default=0),
            ranked_total=as_int((row or {}).get("ranked_total"), default=0),
            pair_total=as_int((row or {}).get("pair_total"), default=0),
        )
        per_demande[demande_id] = counts
        candidate_total += counts.candidate_total
        ranked_total += counts.ranked_total
        pair_total += counts.pair_total

    return MatchArtifactBatchResult(
        candidate_total=candidate_total,
        ranked_total=ranked_total,
        pair_total=pair_total,
        per_demande=per_demande,
    )


def explain_match_artifacts_for_demandes(
    session: DbSession,
    demande_ids: Sequence[int],
    *,
    limit: int | None,
) -> dict[str, object]:
    normalized_ids = _normalize_demande_ids(demande_ids)
    if not normalized_ids:
        return {}

    _set_rebuild_timeouts(session)
    session.execute("SAVEPOINT match_artifact_explain")
    try:
        _delete_existing_artifacts(session, normalized_ids)
        sql, params = _artifact_insert_query(normalized_ids, limit=limit)
        row = session.execute(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}",
            params,
        ).fetchone()
    finally:
        session.execute("ROLLBACK TO SAVEPOINT match_artifact_explain")
        session.execute("RELEASE SAVEPOINT match_artifact_explain")
    raw_plan = (row or {}).get("QUERY PLAN")
    if isinstance(raw_plan, list) and raw_plan:
        first = raw_plan[0]
        if isinstance(first, dict):
            return first
    if isinstance(raw_plan, dict):
        return raw_plan
    return {}


__all__ = [
    "MatchArtifactBatchResult",
    "MatchArtifactCounts",
    "explain_match_artifacts_for_demandes",
    "rebuild_match_artifacts_for_demandes",
]
