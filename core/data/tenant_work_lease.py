"""Tenant-scoped lease helpers for fair async work scheduling."""

from __future__ import annotations

from core.matcher.ports.db import DbSession
from core.utils.row_casts import row_int


def _ensure_row(
    session: DbSession,
    *,
    task_name: str,
    agency_id: int,
    stream_key: str,
) -> None:
    session.execute(
        """
        INSERT INTO tenant_work_lease (
            task_name, agency_id, stream_key, in_flight, created_at, updated_at
        )
        VALUES (%s, %s, %s, 0, NOW(), NOW())
        ON CONFLICT (task_name, agency_id, stream_key) DO NOTHING
        """,
        (task_name, agency_id, stream_key),
    )


def reserve_stream_slot(
    session: DbSession,
    *,
    task_name: str,
    agency_id: int,
    stream_key: str,
    provisional_owner: str,
    lease_seconds: int,
    max_in_flight: int,
) -> tuple[str | None, bool]:
    """Reserve a tenant stream slot.

    Returns ``(active_owner, reserved)``:
    - ``active_owner`` is set when a live task should be coalesced.
    - ``reserved`` is true when a new slot was reserved for scheduling.
    """

    _ensure_row(
        session,
        task_name=task_name,
        agency_id=agency_id,
        stream_key=stream_key,
    )
    active_rows = session.execute(
        """
        SELECT in_flight
        FROM tenant_work_lease
        WHERE task_name = %s
          AND agency_id = %s
          AND in_flight > 0
          AND lease_until IS NOT NULL
          AND lease_until > NOW()
        FOR UPDATE
        """,
        (task_name, agency_id),
    ).fetchall()
    active_in_flight = sum(row_int(row, "in_flight") for row in active_rows)

    row = session.execute(
        """
        SELECT in_flight, lease_owner, lease_until
        FROM tenant_work_lease
        WHERE task_name = %s
          AND agency_id = %s
          AND stream_key = %s
        FOR UPDATE
        """,
        (task_name, agency_id, stream_key),
    ).fetchone()
    if row is None:
        return None, False

    in_flight = row_int(row, "in_flight")
    lease_owner = str(row.get("lease_owner") or "").strip() or None
    lease_until = row.get("lease_until")

    if lease_owner and lease_until is not None and in_flight > 0:
        session.execute(
            """
            UPDATE tenant_work_lease
            SET updated_at = NOW()
            WHERE task_name = %s
              AND agency_id = %s
              AND stream_key = %s
            """,
            (task_name, agency_id, stream_key),
        )
        return lease_owner, False

    if active_in_flight >= max(1, int(max_in_flight)):
        return None, False

    session.execute(
        """
        UPDATE tenant_work_lease
        SET in_flight = in_flight + 1,
            lease_owner = %s,
            lease_until = NOW() + (%s || ' seconds')::interval,
            attempt = attempt + 1,
            updated_at = NOW()
        WHERE task_name = %s
          AND agency_id = %s
          AND stream_key = %s
        """,
        (
            provisional_owner,
            max(1, int(lease_seconds)),
            task_name,
            agency_id,
            stream_key,
        ),
    )
    return None, True


def assign_stream_owner(
    session: DbSession,
    *,
    task_name: str,
    agency_id: int,
    stream_key: str,
    from_owner: str,
    to_owner: str,
    lease_seconds: int,
) -> None:
    session.execute(
        """
        UPDATE tenant_work_lease
        SET lease_owner = %s,
            lease_until = NOW() + (%s || ' seconds')::interval,
            updated_at = NOW()
        WHERE task_name = %s
          AND agency_id = %s
          AND stream_key = %s
          AND lease_owner = %s
        """,
        (
            to_owner,
            max(1, int(lease_seconds)),
            task_name,
            agency_id,
            stream_key,
            from_owner,
        ),
    )


def release_stream_slot(
    session: DbSession,
    *,
    task_name: str,
    agency_id: int,
    stream_key: str,
    lease_owner: str,
) -> None:
    session.execute(
        """
        UPDATE tenant_work_lease
        SET in_flight = 0,
            lease_owner = NULL,
            lease_until = NULL,
            updated_at = NOW()
        WHERE task_name = %s
          AND agency_id = %s
          AND stream_key = %s
          AND lease_owner = %s
        """,
        (task_name, agency_id, stream_key, lease_owner),
    )


def clear_stream_slot(
    session: DbSession,
    *,
    task_name: str,
    agency_id: int,
    stream_key: str,
) -> None:
    session.execute(
        """
        UPDATE tenant_work_lease
        SET in_flight = 0,
            lease_owner = NULL,
            lease_until = NULL,
            updated_at = NOW()
        WHERE task_name = %s
          AND agency_id = %s
          AND stream_key = %s
        """,
        (task_name, agency_id, stream_key),
    )


__all__ = [
    "assign_stream_owner",
    "clear_stream_slot",
    "release_stream_slot",
    "reserve_stream_slot",
]
