"""
Storage object persistence (raw SQL, UoW).
"""

from __future__ import annotations

from typing import Any

from core.utils.row_casts import row_int
from server.pg.uow import PgSession


def create_storage_object(
    session: PgSession,
    *,
    bucket: str,
    object_key: str,
    user_id: int,
    role: str,
    purpose: str,
    content_type: str | None,
    size_bytes: int | None,
    checksum: str | None,
    created_ip: str | None,
) -> str:
    row = session.execute(
        """
        INSERT INTO storage_objects (
            bucket,
            object_key,
            user_id,
            role,
            purpose,
            content_type,
            size_bytes,
            checksum,
            created_ip,
            status,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            bucket,
            object_key,
            user_id,
            role,
            purpose,
            content_type,
            size_bytes,
            checksum,
            created_ip,
        ),
    ).fetchone()
    return str(row["id"]) if row else ""


def mark_storage_ready(
    session: PgSession,
    *,
    storage_id: str,
    content_type: str | None,
    size_bytes: int,
    checksum: str | None,
) -> None:
    session.execute(
        """
        UPDATE storage_objects
        SET status = 'ready',
            content_type = COALESCE(%s, content_type),
            size_bytes = %s,
            checksum = COALESCE(%s, checksum),
            updated_at = CURRENT_TIMESTAMP,
            row_version = row_version + 1
        WHERE id = %s
        """,
        (content_type, size_bytes, checksum, storage_id),
    )


def mark_storage_failed(session: PgSession, *, storage_id: str, message: str | None) -> None:
    session.execute(
        """
        UPDATE storage_objects
        SET status = 'failed',
            updated_at = CURRENT_TIMESTAMP,
            row_version = row_version + 1
        WHERE id = %s
        """,
        (storage_id,),
    )
    if message:
        session.execute(
            "UPDATE storage_objects SET checksum = %s WHERE id = %s",
            (message[:512], storage_id),
        )


def mark_storage_deleted(session: PgSession, *, storage_id: str) -> int:
    row = session.execute(
        """
        UPDATE storage_objects
        SET status = 'deleted',
            deleted_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP,
            row_version = row_version + 1
        WHERE id = %s
        RETURNING size_bytes
        """,
        (storage_id,),
    ).fetchone()
    return row_int(row, "size_bytes") if row else 0


def restore_deleted_storage(session: PgSession, *, storage_id: str) -> int:
    row = session.execute(
        """
        UPDATE storage_objects
        SET status = 'ready',
            deleted_at = NULL,
            updated_at = CURRENT_TIMESTAMP,
            row_version = row_version + 1
        WHERE id = %s
          AND status = 'deleted'
          AND deleted_at IS NOT NULL
        RETURNING size_bytes
        """,
        (storage_id,),
    ).fetchone()
    return row_int(row, "size_bytes") if row else 0


def mark_storage_purged(session: PgSession, *, storage_id: str) -> None:
    session.execute(
        """
        UPDATE storage_objects
        SET status = 'purged',
            updated_at = CURRENT_TIMESTAMP,
            row_version = row_version + 1
        WHERE id = %s
        """,
        (storage_id,),
    )


def delete_storage_object(session: PgSession, *, storage_id: str) -> int:
    row = session.execute(
        """
        DELETE FROM storage_objects
        WHERE id = %s
        RETURNING size_bytes
        """,
        (storage_id,),
    ).fetchone()
    return row_int(row, "size_bytes") if row else 0


def get_storage_object(session: PgSession, storage_id: str) -> dict[str, Any] | None:
    row = session.execute(
        "SELECT * FROM storage_objects WHERE id = %s",
        (storage_id,),
    ).fetchone()
    return dict(row) if row else None


def lock_storage_object(session: PgSession, storage_id: str) -> dict[str, Any] | None:
    row = session.execute(
        "SELECT * FROM storage_objects WHERE id = %s FOR UPDATE",
        (storage_id,),
    ).fetchone()
    return dict(row) if row else None


def lock_storage_objects(session: PgSession, storage_ids: list[str]) -> dict[str, dict[str, Any]]:
    ids = sorted({str(storage_id) for storage_id in storage_ids if str(storage_id)})
    if not ids:
        return {}
    rows = session.execute(
        """
        SELECT *
        FROM storage_objects
        WHERE id = ANY(%s)
        ORDER BY id ASC
        FOR UPDATE
        """,
        (ids,),
    ).fetchall()
    return {str(row["id"]): dict(row) for row in rows}


def list_deleted_storage_objects(
    session: PgSession,
    *,
    older_than_days: int,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = session.execute(
        """
        SELECT id, bucket, object_key, size_bytes, agency_id, user_id, role, created_ip
        FROM storage_objects
        WHERE status = 'deleted'
          AND deleted_at < (CURRENT_TIMESTAMP - (%s || ' days')::interval)
        ORDER BY deleted_at ASC
        LIMIT %s
        """,
        (older_than_days, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def list_pending_storage_objects(
    session: PgSession,
    *,
    older_than_hours: int,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = session.execute(
        """
        SELECT id, bucket, object_key, size_bytes, agency_id, user_id, role, created_ip
        FROM storage_objects
        WHERE status = 'pending'
          AND created_at < (CURRENT_TIMESTAMP - (%s || ' hours')::interval)
        ORDER BY created_at ASC
        LIMIT %s
        """,
        (older_than_hours, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def get_total_usage_bytes(session: PgSession, *, agency_id: int | None = None) -> int:
    params: list[object] = []
    sql = "SELECT COALESCE(SUM(size_bytes), 0) AS total FROM storage_objects WHERE status = 'ready'"
    if agency_id is not None:
        sql += " AND agency_id = %s"
        params.append(agency_id)
    row = session.execute(sql, params).fetchone()
    return row_int(row, "total") if row else 0


def bump_storage_usage(session: PgSession, *, agency_id: int, delta_bytes: int) -> None:
    session.execute(
        """
        INSERT INTO storage_usage (agency_id, total_bytes, updated_at)
        VALUES (%s, GREATEST(%s, 0), CURRENT_TIMESTAMP)
        ON CONFLICT (agency_id)
        DO UPDATE SET
            total_bytes = GREATEST(storage_usage.total_bytes + %s, 0),
            updated_at = CURRENT_TIMESTAMP
        """,
        (agency_id, delta_bytes, delta_bytes),
    )
    session.execute(
        """
        DELETE FROM storage_usage
        WHERE agency_id = %s
          AND total_bytes <= 0
        """,
        (agency_id,),
    )


def get_usage_for_agency(session: PgSession, *, agency_id: int) -> int:
    row = session.execute(
        "SELECT total_bytes FROM storage_usage WHERE agency_id = %s",
        (agency_id,),
    ).fetchone()
    return row_int(row, "total_bytes") if row else 0


def get_reserved_usage_for_agency(session: PgSession, *, agency_id: int) -> int:
    """
    Return agency usage including pending reservations.

    This is used for quota enforcement to prevent parallel-upload bypasses.
    """
    row = session.execute(
        """
        SELECT COALESCE(SUM(size_bytes), 0) AS total_bytes
        FROM storage_objects
        WHERE agency_id = %s
          AND status IN ('ready', 'pending')
        """,
        (agency_id,),
    ).fetchone()
    return row_int(row, "total_bytes") if row else 0


def count_recent_uploads(session: PgSession, *, user_id: int, since_hours: int = 24) -> int:
    row = session.execute(
        """
        SELECT COUNT(*) AS count
        FROM storage_objects
        WHERE user_id = %s
          AND created_at >= (CURRENT_TIMESTAMP - (%s || ' hours')::interval)
        """,
        (user_id, since_hours),
    ).fetchone()
    return row_int(row, "count") if row else 0
