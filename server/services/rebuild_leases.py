"""Durable rebuild lease orchestration for API coalescing/backpressure."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg

from core.matcher.ports.db import DbSession
from core.utils.row_casts import row_int

_ACTIVE_STATUSES = ("queued", "running")
_FINAL_STATUSES = ("done", "failed")


@dataclass(frozen=True)
class LeaseReserveResult:
    outcome: str  # accepted | coalesced | backpressured
    task_id: str | None
    retry_after_seconds: int


def _env_int(name: str, default: int, *, min_v: int, max_v: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_v, min(max_v, value))


def _max_active_leases() -> int:
    return _env_int("IMMOAPP_REBUILD_MAX_ACTIVE_LEASES", 2, min_v=1, max_v=32)


def _queued_ttl_seconds() -> int:
    return _env_int("IMMOAPP_REBUILD_LEASE_TTL_SECONDS", 3600, min_v=60, max_v=86400)


def _history_ttl_seconds() -> int:
    return _env_int("IMMOAPP_REBUILD_LEASE_HISTORY_TTL_SECONDS", 21600, min_v=300, max_v=604800)


def _retry_after_seconds() -> int:
    return _env_int("IMMOAPP_REBUILD_RETRY_AFTER_SECONDS", 30, min_v=5, max_v=600)


def _min_interval_seconds() -> int:
    return _env_int("IMMOAPP_REBUILD_MIN_INTERVAL_SECONDS", 30, min_v=0, max_v=3600)


def _advisory_lock_key(*, agency_id: int) -> int:
    digest = hashlib.sha256(f"rebuild-lease:{int(agency_id)}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


def _safe_exec(session: DbSession, sql: str, params: tuple[object, ...] = ()) -> None:
    session.execute(sql, params)


def reserve_rebuild_lease(
    session: DbSession,
    *,
    agency_id: int,
    job_type: str,
    scope_key: str,
    task_id: str,
) -> LeaseReserveResult:
    """
    Reserve a rebuild lease.

    Returns:
    - accepted: caller can enqueue now with returned task_id.
    - coalesced: existing active lease should be reused.
    - backpressured: active agency budget exceeded.
    """
    try:
        _safe_exec(
            session, "SELECT pg_advisory_xact_lock(%s)", (_advisory_lock_key(agency_id=agency_id),)
        )
        _safe_exec(
            session,
            """
            DELETE FROM api_rebuild_job_leases
            WHERE expires_at < NOW()
              AND status IN ('done', 'failed')
            """,
        )
        existing = session.execute(
            """
            SELECT task_id
            FROM api_rebuild_job_leases
            WHERE agency_id = %s
              AND job_type = %s
              AND scope_key = %s
              AND status IN ('queued', 'running')
              AND expires_at > NOW()
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (int(agency_id), str(job_type), str(scope_key)),
        ).fetchone()
        if existing is not None:
            task = str(existing.get("task_id") or "").strip()
            return LeaseReserveResult(
                outcome="coalesced",
                task_id=task or None,
                retry_after_seconds=_retry_after_seconds(),
            )

        min_interval_seconds = _min_interval_seconds()
        if min_interval_seconds > 0:
            recent = session.execute(
                """
                SELECT
                    task_id,
                    GREATEST(
                        1,
                        CEIL(
                            EXTRACT(
                                EPOCH FROM (
                                    updated_at + (%s || ' seconds')::interval - NOW()
                                )
                            )
                        )::int
                    ) AS retry_after
                FROM api_rebuild_job_leases
                WHERE agency_id = %s
                  AND job_type = %s
                  AND scope_key = %s
                  AND updated_at + (%s || ' seconds')::interval > NOW()
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (
                    min_interval_seconds,
                    int(agency_id),
                    str(job_type),
                    str(scope_key),
                    min_interval_seconds,
                ),
            ).fetchone()
            if recent is not None:
                task = str(recent.get("task_id") or "").strip()
                retry_after = row_int(recent, "retry_after")
                return LeaseReserveResult(
                    outcome="coalesced",
                    task_id=task or None,
                    retry_after_seconds=max(1, retry_after),
                )

        count_row = session.execute(
            """
            SELECT COUNT(*) AS n
            FROM api_rebuild_job_leases
            WHERE agency_id = %s
              AND status IN ('queued', 'running')
              AND expires_at > NOW()
            """,
            (int(agency_id),),
        ).fetchone()
        active_count = row_int(count_row, "n") if count_row else 0
        if active_count >= _max_active_leases():
            return LeaseReserveResult(
                outcome="backpressured",
                task_id=None,
                retry_after_seconds=_retry_after_seconds(),
            )

        session.execute(
            """
            INSERT INTO api_rebuild_job_leases (
                agency_id,
                job_type,
                scope_key,
                task_id,
                status,
                created_at,
                updated_at,
                expires_at
            ) VALUES (
                %s, %s, %s, %s, 'queued', NOW(), NOW(),
                NOW() + (%s || ' seconds')::interval
            )
            """,
            (
                int(agency_id),
                str(job_type),
                str(scope_key),
                str(task_id),
                _queued_ttl_seconds(),
            ),
        )
    except psycopg.Error as exc:
        if getattr(exc, "sqlstate", None) == "42P01":
            # Migration not applied yet; keep API available without coalescing.
            return LeaseReserveResult(
                outcome="accepted",
                task_id=task_id,
                retry_after_seconds=_retry_after_seconds(),
            )
        raise

    return LeaseReserveResult(
        outcome="accepted",
        task_id=task_id,
        retry_after_seconds=_retry_after_seconds(),
    )


def reserve_rebuild_lease_tx(
    *,
    agency_id: int,
    job_type: str,
    scope_key: str,
    task_id: str,
) -> LeaseReserveResult:
    from server.pg.uow import get_uow, use_security_context

    with use_security_context(agency_id=int(agency_id), is_superuser=True):
        with get_uow().transaction() as session:
            return reserve_rebuild_lease(
                session,
                agency_id=agency_id,
                job_type=job_type,
                scope_key=scope_key,
                task_id=task_id,
            )


def _mark_status(
    session: DbSession,
    *,
    task_id: str,
    status: str,
    error_message: str = "",
) -> None:
    assert status in {"running", "done", "failed"}
    ttl_seconds = _queued_ttl_seconds() if status == "running" else _history_ttl_seconds()
    session.execute(
        """
        UPDATE api_rebuild_job_leases
        SET status = %s,
            last_error = %s,
            updated_at = NOW(),
            expires_at = NOW() + (%s || ' seconds')::interval
        WHERE task_id = %s
        """,
        (status, error_message[:1000], ttl_seconds, str(task_id)),
    )


def mark_rebuild_running(session: DbSession, *, task_id: str) -> None:
    try:
        _mark_status(session, task_id=task_id, status="running")
    except psycopg.Error as exc:
        if getattr(exc, "sqlstate", None) != "42P01":
            raise


def mark_rebuild_done(session: DbSession, *, task_id: str) -> None:
    try:
        _mark_status(session, task_id=task_id, status="done")
    except psycopg.Error as exc:
        if getattr(exc, "sqlstate", None) != "42P01":
            raise


def mark_rebuild_failed(session: DbSession, *, task_id: str, error_message: str) -> None:
    try:
        _mark_status(session, task_id=task_id, status="failed", error_message=error_message)
    except psycopg.Error as exc:
        if getattr(exc, "sqlstate", None) != "42P01":
            raise


def mark_rebuild_failed_tx(*, agency_id: int, task_id: str, error_message: str) -> None:
    from server.pg.uow import get_uow, use_security_context

    with use_security_context(agency_id=int(agency_id), is_superuser=True):
        with get_uow().transaction() as session:
            mark_rebuild_failed(session, task_id=task_id, error_message=error_message)


def parse_scope_key(
    *, job_type: str, client_id: int | None = None, wilaya_id: int | None = None
) -> str:
    normalized = str(job_type).strip().lower()
    if normalized == "client":
        return f"client:{int(client_id or 0)}"
    if normalized == "wilaya":
        return f"wilaya:{int(wilaya_id or 0)}"
    return "_"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "LeaseReserveResult",
    "mark_rebuild_done",
    "mark_rebuild_failed",
    "mark_rebuild_failed_tx",
    "mark_rebuild_running",
    "parse_scope_key",
    "reserve_rebuild_lease_tx",
    "reserve_rebuild_lease",
    "utc_now",
]
