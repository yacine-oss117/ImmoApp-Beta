"""Durable match rebuild state tracking for coalescing and batched dispatch."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

from core.matcher.ports.db import DbSession
from core.models_cast import as_int

_PENDING_STALE_SEC = int(os.environ.get("MATCH_REBUILD_PENDING_STALE_SEC", "900"))
_DISPATCH_CLAIM_TTL_SEC = int(os.environ.get("MATCH_REBUILD_DISPATCH_CLAIM_TTL_SEC", "120"))


def _is_stale(updated_at: object) -> bool:
    if _PENDING_STALE_SEC <= 0:
        return False
    if not isinstance(updated_at, datetime):
        return False
    delta = timedelta(seconds=_PENDING_STALE_SEC)
    tzinfo = updated_at.tzinfo or UTC
    return datetime.now(tz=tzinfo) - updated_at > delta


def _claim_expired(claim_expires_at: object) -> bool:
    if not isinstance(claim_expires_at, datetime):
        return True
    tzinfo = claim_expires_at.tzinfo or UTC
    return datetime.now(tz=tzinfo) >= claim_expires_at


def _dispatch_after_expr(seconds: int) -> str:
    return f"(CURRENT_TIMESTAMP + ({max(0, int(seconds))} * INTERVAL '1 second'))"


def fetch_stale_pending(
    session: DbSession,
    *,
    limit: int = 200,
    stale_seconds: int | None = None,
) -> list[dict[str, object]]:
    """Return pending rebuild rows older than stale_seconds."""
    stale = _PENDING_STALE_SEC if stale_seconds is None else int(stale_seconds)
    if stale <= 0:
        return []
    rows = session.execute(
        """
        SELECT scope, scope_id, updated_at
        FROM match_rebuild_state
        WHERE pending = TRUE
          AND updated_at < (CURRENT_TIMESTAMP - (%s * INTERVAL '1 second'))
        ORDER BY updated_at ASC
        LIMIT %s
        """,
        (stale, int(limit)),
    ).fetchall()
    return [dict(row) for row in rows]


def request_rebuild(
    session: DbSession,
    *,
    scope: str,
    scope_id: int,
    debounce_seconds: int = 0,
) -> bool:
    """Record a rebuild request and return True if enqueue/flush should be attempted."""
    session.execute(
        """
        INSERT INTO match_rebuild_state (
            scope,
            scope_id,
            pending,
            generation,
            updated_at,
            dispatch_after,
            dispatch_claim_token,
            dispatch_claim_expires_at,
            last_requested_at
        )
        VALUES (%s, %s, FALSE, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, NULL, CURRENT_TIMESTAMP)
        ON CONFLICT (scope, scope_id, agency_id) DO NOTHING
        """,
        (scope, int(scope_id)),
    )

    row = session.execute(
        """
        SELECT generation, pending, updated_at, dispatch_claim_expires_at
        FROM match_rebuild_state
        WHERE scope = %s AND scope_id = %s
        FOR UPDATE
        """,
        (scope, int(scope_id)),
    ).fetchone()

    if not row:
        return True

    pending = bool(row.get("pending"))
    claim_expired = _claim_expired(row.get("dispatch_claim_expires_at"))
    if pending and _is_stale(row.get("updated_at")):
        pending = False

    if str(scope) == "demande" and int(debounce_seconds) > 0:
        session.execute(
            f"""
            UPDATE match_rebuild_state
            SET generation = generation + 1,
                pending = TRUE,
                updated_at = CURRENT_TIMESTAMP,
                last_requested_at = CURRENT_TIMESTAMP,
                dispatch_after = {_dispatch_after_expr(int(debounce_seconds))},
                dispatch_claim_token = CASE
                    WHEN dispatch_claim_expires_at IS NULL OR dispatch_claim_expires_at <= CURRENT_TIMESTAMP
                    THEN NULL ELSE dispatch_claim_token
                END,
                dispatch_claim_expires_at = CASE
                    WHEN dispatch_claim_expires_at IS NULL OR dispatch_claim_expires_at <= CURRENT_TIMESTAMP
                    THEN NULL ELSE dispatch_claim_expires_at
                END
            WHERE scope = %s AND scope_id = %s
            """,
            (scope, int(scope_id)),
        )
        return True

    if pending and not claim_expired:
        session.execute(
            """
            UPDATE match_rebuild_state
            SET generation = generation + 1,
                updated_at = CURRENT_TIMESTAMP,
                last_requested_at = CURRENT_TIMESTAMP
            WHERE scope = %s AND scope_id = %s
            """,
            (scope, int(scope_id)),
        )
        return False

    session.execute(
        """
        UPDATE match_rebuild_state
        SET generation = generation + 1,
            pending = TRUE,
            updated_at = CURRENT_TIMESTAMP,
            dispatch_after = CURRENT_TIMESTAMP,
            dispatch_claim_token = NULL,
            dispatch_claim_expires_at = NULL,
            last_requested_at = CURRENT_TIMESTAMP
        WHERE scope = %s AND scope_id = %s
        """,
        (scope, int(scope_id)),
    )
    return True


def request_rebuild_batch(
    session: DbSession,
    *,
    scope: str,
    scope_ids: list[int],
    debounce_seconds: int = 0,
) -> list[int]:
    """Record multiple rebuild requests and return scope_ids that should enqueue work."""
    normalized_ids = sorted({int(value) for value in (scope_ids or []) if int(value) > 0})
    if not normalized_ids:
        return []

    session.execute(
        """
        INSERT INTO match_rebuild_state (
            scope,
            scope_id,
            pending,
            generation,
            updated_at,
            dispatch_after,
            dispatch_claim_token,
            dispatch_claim_expires_at,
            last_requested_at
        )
        SELECT
            %s,
            ids.scope_id,
            FALSE,
            0,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            NULL,
            NULL,
            CURRENT_TIMESTAMP
        FROM UNNEST(%s::bigint[]) AS ids(scope_id)
        ON CONFLICT (scope, scope_id, agency_id) DO NOTHING
        """,
        (scope, normalized_ids),
    )

    if str(scope) == "demande" and int(debounce_seconds) > 0:
        session.execute(
            f"""
            UPDATE match_rebuild_state
            SET generation = generation + 1,
                pending = TRUE,
                updated_at = CURRENT_TIMESTAMP,
                last_requested_at = CURRENT_TIMESTAMP,
                dispatch_after = {_dispatch_after_expr(int(debounce_seconds))},
                dispatch_claim_token = CASE
                    WHEN dispatch_claim_expires_at IS NULL OR dispatch_claim_expires_at <= CURRENT_TIMESTAMP
                    THEN NULL ELSE dispatch_claim_token
                END,
                dispatch_claim_expires_at = CASE
                    WHEN dispatch_claim_expires_at IS NULL OR dispatch_claim_expires_at <= CURRENT_TIMESTAMP
                    THEN NULL ELSE dispatch_claim_expires_at
                END
            WHERE scope = %s
              AND scope_id = ANY(%s)
            """,
            (scope, normalized_ids),
        )
        return normalized_ids

    rows = session.execute(
        """
        SELECT scope_id, pending, updated_at, dispatch_claim_expires_at
        FROM match_rebuild_state
        WHERE scope = %s
          AND scope_id = ANY(%s)
        FOR UPDATE
        """,
        (scope, normalized_ids),
    ).fetchall()

    enqueue_ids: list[int] = []
    suppress_ids: list[int] = []
    for row in rows:
        scope_id = as_int(row.get("scope_id"), default=0)
        if scope_id <= 0:
            continue
        pending = bool(row.get("pending"))
        claim_expired = _claim_expired(row.get("dispatch_claim_expires_at"))
        if pending and _is_stale(row.get("updated_at")):
            pending = False
        if pending and not claim_expired:
            suppress_ids.append(scope_id)
        else:
            enqueue_ids.append(scope_id)

    if suppress_ids:
        session.execute(
            """
            UPDATE match_rebuild_state
            SET generation = generation + 1,
                updated_at = CURRENT_TIMESTAMP,
                last_requested_at = CURRENT_TIMESTAMP
            WHERE scope = %s
              AND scope_id = ANY(%s)
            """,
            (scope, suppress_ids),
        )

    if enqueue_ids:
        session.execute(
            """
            UPDATE match_rebuild_state
            SET generation = generation + 1,
                pending = TRUE,
                updated_at = CURRENT_TIMESTAMP,
                dispatch_after = CURRENT_TIMESTAMP,
                dispatch_claim_token = NULL,
                dispatch_claim_expires_at = NULL,
                last_requested_at = CURRENT_TIMESTAMP
            WHERE scope = %s
              AND scope_id = ANY(%s)
            """,
            (scope, enqueue_ids),
        )

    return sorted(set(enqueue_ids))


def get_generation(session: DbSession, *, scope: str, scope_id: int) -> int:
    """Read the current generation for a rebuild scope."""
    row = session.execute(
        "SELECT generation FROM match_rebuild_state WHERE scope = %s AND scope_id = %s",
        (scope, int(scope_id)),
    ).fetchone()
    if not row:
        return 0
    return as_int(row.get("generation"), default=0)


def count_dispatchable(
    session: DbSession,
    *,
    scope: str,
) -> int:
    row = session.execute(
        """
        SELECT COUNT(*) AS count
        FROM match_rebuild_state
        WHERE scope = %s
          AND pending = TRUE
          AND dispatch_after <= CURRENT_TIMESTAMP
          AND (
              dispatch_claim_expires_at IS NULL
              OR dispatch_claim_expires_at <= CURRENT_TIMESTAMP
          )
        """,
        (scope,),
    ).fetchone()
    return as_int(row.get("count") if row else 0, default=0)


def count_pending(
    session: DbSession,
    *,
    scope: str,
) -> int:
    row = session.execute(
        """
        SELECT COUNT(*) AS count
        FROM match_rebuild_state
        WHERE scope = %s
          AND pending = TRUE
        """,
        (scope,),
    ).fetchone()
    return as_int(row.get("count") if row else 0, default=0)


def count_claimed_dispatches(
    session: DbSession,
    *,
    scope: str,
) -> int:
    row = session.execute(
        """
        SELECT COUNT(*) AS count
        FROM match_rebuild_state
        WHERE scope = %s
          AND pending = TRUE
          AND dispatch_claim_expires_at IS NOT NULL
          AND dispatch_claim_expires_at > CURRENT_TIMESTAMP
        """,
        (scope,),
    ).fetchone()
    return as_int(row.get("count") if row else 0, default=0)


def count_expired_dispatch_claims(
    session: DbSession,
    *,
    scope: str,
) -> int:
    row = session.execute(
        """
        SELECT COUNT(*) AS count
        FROM match_rebuild_state
        WHERE scope = %s
          AND pending = TRUE
          AND dispatch_claim_expires_at IS NOT NULL
          AND dispatch_claim_expires_at <= CURRENT_TIMESTAMP
        """,
        (scope,),
    ).fetchone()
    return as_int(row.get("count") if row else 0, default=0)


def claim_dispatchable_scope_ids(
    session: DbSession,
    *,
    scope: str,
    limit: int,
    claim_token: str | None = None,
    claim_ttl_seconds: int | None = None,
) -> list[int]:
    token = str(claim_token or uuid.uuid4().hex)
    ttl = max(10, int(claim_ttl_seconds or _DISPATCH_CLAIM_TTL_SEC))
    rows = session.execute(
        """
        WITH candidates AS (
            SELECT ctid, scope_id
            FROM match_rebuild_state
            WHERE scope = %s
              AND pending = TRUE
              AND dispatch_after <= CURRENT_TIMESTAMP
              AND (
                  dispatch_claim_expires_at IS NULL
                  OR dispatch_claim_expires_at <= CURRENT_TIMESTAMP
              )
            ORDER BY dispatch_after ASC, last_requested_at ASC, scope_id ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        )
        UPDATE match_rebuild_state AS target
        SET dispatch_claim_token = %s,
            dispatch_claim_expires_at = CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),
            updated_at = CURRENT_TIMESTAMP
        FROM candidates
        WHERE target.ctid = candidates.ctid
        RETURNING target.scope_id
        """,
        (scope, int(limit), token, ttl),
    ).fetchall()
    return sorted(
        {
            as_int(row.get("scope_id"), default=0)
            for row in rows
            if as_int(row.get("scope_id"), default=0) > 0
        }
    )


def reclaim_expired_dispatch_claims(
    session: DbSession,
    *,
    scope: str,
    limit: int = 200,
) -> int:
    return int(
        session.execute(
            """
            WITH expired AS (
                SELECT ctid
                FROM match_rebuild_state
                WHERE scope = %s
                  AND pending = TRUE
                  AND dispatch_claim_expires_at IS NOT NULL
                  AND dispatch_claim_expires_at <= CURRENT_TIMESTAMP
                ORDER BY dispatch_claim_expires_at ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            UPDATE match_rebuild_state AS target
            SET dispatch_claim_token = NULL,
                dispatch_claim_expires_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            FROM expired
            WHERE target.ctid = expired.ctid
            """,
            (scope, int(limit)),
        ).rowcount
        or 0
    )


def complete_rebuild(
    session: DbSession,
    *,
    scope: str,
    scope_id: int,
    start_generation: int,
) -> bool:
    """Finalize a rebuild, returning True if another run is required."""
    row = session.execute(
        """
        SELECT generation
        FROM match_rebuild_state
        WHERE scope = %s AND scope_id = %s
        FOR UPDATE
        """,
        (scope, int(scope_id)),
    ).fetchone()
    if not row:
        return False
    current_gen = as_int(row.get("generation"), default=0)
    if current_gen > start_generation:
        session.execute(
            """
            UPDATE match_rebuild_state
            SET pending = TRUE,
                dispatch_after = CURRENT_TIMESTAMP,
                dispatch_claim_token = NULL,
                dispatch_claim_expires_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE scope = %s AND scope_id = %s
            """,
            (scope, int(scope_id)),
        )
        return True

    session.execute(
        """
        UPDATE match_rebuild_state
        SET pending = FALSE,
            dispatch_after = CURRENT_TIMESTAMP,
            dispatch_claim_token = NULL,
            dispatch_claim_expires_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE scope = %s AND scope_id = %s
        """,
        (scope, int(scope_id)),
    )
    return False


def complete_rebuild_batch(
    session: DbSession,
    *,
    scope: str,
    start_generations: dict[int, int],
) -> list[int]:
    """Finalize multiple rebuild scopes with one lock/read pass."""
    scope_ids = sorted({int(k) for k in (start_generations or {}).keys() if int(k) > 0})
    if not scope_ids:
        return []

    rows = session.execute(
        """
        SELECT scope_id, generation
        FROM match_rebuild_state
        WHERE scope = %s
          AND scope_id = ANY(%s)
        FOR UPDATE
        """,
        (scope, scope_ids),
    ).fetchall()
    if not rows:
        return []

    rerun_ids: list[int] = []
    done_ids: list[int] = []
    for row in rows:
        scope_id = as_int(row.get("scope_id"), default=0)
        if scope_id <= 0:
            continue
        current_gen = as_int(row.get("generation"), default=0)
        start_gen = as_int(start_generations.get(scope_id), default=0)
        if current_gen > start_gen:
            rerun_ids.append(scope_id)
        else:
            done_ids.append(scope_id)

    if rerun_ids:
        session.execute(
            """
            UPDATE match_rebuild_state
            SET pending = TRUE,
                dispatch_after = CURRENT_TIMESTAMP,
                dispatch_claim_token = NULL,
                dispatch_claim_expires_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE scope = %s
              AND scope_id = ANY(%s)
            """,
            (scope, rerun_ids),
        )
    if done_ids:
        session.execute(
            """
            UPDATE match_rebuild_state
            SET pending = FALSE,
                dispatch_after = CURRENT_TIMESTAMP,
                dispatch_claim_token = NULL,
                dispatch_claim_expires_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE scope = %s
              AND scope_id = ANY(%s)
            """,
            (scope, done_ids),
        )
    return sorted(set(rerun_ids))


__all__ = [
    "claim_dispatchable_scope_ids",
    "complete_rebuild",
    "complete_rebuild_batch",
    "count_claimed_dispatches",
    "count_dispatchable",
    "count_expired_dispatch_claims",
    "count_pending",
    "fetch_stale_pending",
    "get_generation",
    "reclaim_expired_dispatch_claims",
    "request_rebuild",
    "request_rebuild_batch",
]
