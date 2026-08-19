"""Checkpoint + lease helpers for resumable keyset task scans."""

from __future__ import annotations

from dataclasses import dataclass

from core.matcher.ports.db import DbSession
from core.utils.row_casts import row_int


@dataclass(frozen=True)
class ScanCheckpoint:
    last_id: int
    rows_processed: int
    attempt: int


def acquire_lease(
    session: DbSession,
    *,
    task_name: str,
    agency_id: int,
    stream_key: str,
    lease_owner: str,
    lease_seconds: int,
) -> ScanCheckpoint | None:
    """Acquire or renew a checkpoint lease and return current scan progress."""
    session.execute(
        """
        INSERT INTO task_scan_checkpoints (
            task_name, agency_id, stream_key, last_id, rows_processed, attempt, created_at, updated_at
        )
        VALUES (%s, %s, %s, 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (task_name, agency_id, stream_key) DO NOTHING
        """,
        (task_name, agency_id, stream_key),
    )
    row = session.execute(
        """
        UPDATE task_scan_checkpoints
        SET lease_owner = %s,
            lease_until = CURRENT_TIMESTAMP + (%s || ' seconds')::interval,
            attempt = attempt + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_name = %s
          AND agency_id = %s
          AND stream_key = %s
          AND (
            lease_owner IS NULL
            OR lease_until IS NULL
            OR lease_until < CURRENT_TIMESTAMP
            OR lease_owner = %s
          )
        RETURNING last_id, rows_processed, attempt
        """,
        (
            lease_owner,
            max(1, int(lease_seconds)),
            task_name,
            agency_id,
            stream_key,
            lease_owner,
        ),
    ).fetchone()
    if not row:
        return None
    return ScanCheckpoint(
        last_id=row_int(row, "last_id"),
        rows_processed=row_int(row, "rows_processed"),
        attempt=row_int(row, "attempt"),
    )


def heartbeat_lease(
    session: DbSession,
    *,
    task_name: str,
    agency_id: int,
    stream_key: str,
    lease_owner: str,
    lease_seconds: int,
) -> None:
    session.execute(
        """
        UPDATE task_scan_checkpoints
        SET lease_until = CURRENT_TIMESTAMP + (%s || ' seconds')::interval,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_name = %s
          AND agency_id = %s
          AND stream_key = %s
          AND lease_owner = %s
        """,
        (max(1, int(lease_seconds)), task_name, agency_id, stream_key, lease_owner),
    )


def save_progress(
    session: DbSession,
    *,
    task_name: str,
    agency_id: int,
    stream_key: str,
    lease_owner: str,
    last_id: int,
    rows_processed: int,
) -> None:
    session.execute(
        """
        UPDATE task_scan_checkpoints
        SET last_id = %s,
            rows_processed = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_name = %s
          AND agency_id = %s
          AND stream_key = %s
          AND lease_owner = %s
        """,
        (
            max(0, int(last_id)),
            max(0, int(rows_processed)),
            task_name,
            agency_id,
            stream_key,
            lease_owner,
        ),
    )


def release_lease(
    session: DbSession,
    *,
    task_name: str,
    agency_id: int,
    stream_key: str,
    lease_owner: str,
) -> None:
    session.execute(
        """
        UPDATE task_scan_checkpoints
        SET lease_owner = NULL,
            lease_until = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_name = %s
          AND agency_id = %s
          AND stream_key = %s
          AND lease_owner = %s
        """,
        (task_name, agency_id, stream_key, lease_owner),
    )


def reset_progress(
    session: DbSession,
    *,
    task_name: str,
    agency_id: int,
    stream_key: str,
    lease_owner: str,
) -> None:
    session.execute(
        """
        UPDATE task_scan_checkpoints
        SET last_id = 0,
            rows_processed = 0,
            attempt = 0,
            lease_owner = NULL,
            lease_until = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_name = %s
          AND agency_id = %s
          AND stream_key = %s
          AND lease_owner = %s
        """,
        (task_name, agency_id, stream_key, lease_owner),
    )


__all__ = [
    "ScanCheckpoint",
    "acquire_lease",
    "heartbeat_lease",
    "release_lease",
    "reset_progress",
    "save_progress",
]
