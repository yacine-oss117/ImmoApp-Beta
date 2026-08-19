"""
Offer photo persistence helpers.
"""

from __future__ import annotations

from core.contracts.offer_photo_lifecycle import PHOTO_DELETE_ORIGIN_MANUAL
from core.data.errors import NotFoundError
from core.matcher.ports.db import DbSession
from core.utils.row_casts import row_int
from core.utils.time import utc_now_iso


def list_offer_photos(
    session: DbSession, *, offer_id: int, include_deleted: bool = False
) -> list[dict[str, object]]:
    sql = "SELECT * FROM offer_photos WHERE offer_id = %s"
    params: list[object] = [offer_id]
    if not include_deleted:
        sql += " AND deleted_at IS NULL"
    sql += " ORDER BY position ASC, id ASC"
    rows = session.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def get_offer_photo_by_id(session: DbSession, *, photo_id: int) -> dict[str, object] | None:
    row = session.execute(
        "SELECT * FROM offer_photos WHERE id = %s",
        (photo_id,),
    ).fetchone()
    return dict(row) if row else None


def lock_active_offer(session: DbSession, *, offer_id: int) -> dict[str, object] | None:
    row = session.execute(
        """
        SELECT id, agency_id
        FROM offers
        WHERE id = %s
          AND deleted_at IS NULL
        FOR UPDATE
        """,
        (offer_id,),
    ).fetchone()
    return dict(row) if row else None


def get_active_offer_photo_for_storage(
    session: DbSession, *, offer_id: int, storage_id: str
) -> dict[str, object] | None:
    row = session.execute(
        """
        SELECT *
        FROM offer_photos
        WHERE offer_id = %s
          AND storage_id = %s
          AND deleted_at IS NULL
        ORDER BY id ASC
        LIMIT 1
        """,
        (offer_id, storage_id),
    ).fetchone()
    return dict(row) if row else None


def lock_active_offer_photo_for_storage(
    session: DbSession, *, offer_id: int, storage_id: str
) -> dict[str, object] | None:
    row = session.execute(
        """
        SELECT *
        FROM offer_photos
        WHERE offer_id = %s
          AND storage_id = %s
          AND deleted_at IS NULL
        ORDER BY id ASC
        LIMIT 1
        FOR UPDATE
        """,
        (offer_id, storage_id),
    ).fetchone()
    return dict(row) if row else None


def lock_deleted_offer_photo_for_storage(
    session: DbSession, *, offer_id: int, storage_id: str
) -> dict[str, object] | None:
    row = session.execute(
        """
        SELECT op.*
        FROM offer_photos op
        JOIN storage_objects so ON so.id = op.storage_id
        WHERE op.offer_id = %s
          AND op.storage_id = %s
          AND op.deleted_at IS NOT NULL
          AND so.status = 'deleted'
          AND so.purpose = 'offer_photo'
          AND so.agency_id = op.agency_id
        ORDER BY op.id DESC
        LIMIT 1
        FOR UPDATE OF op
        """,
        (offer_id, storage_id),
    ).fetchone()
    return dict(row) if row else None


def lock_offer_photo_by_id(session: DbSession, *, photo_id: int) -> dict[str, object] | None:
    row = session.execute(
        """
        SELECT *
        FROM offer_photos
        WHERE id = %s
        FOR UPDATE
        """,
        (photo_id,),
    ).fetchone()
    return dict(row) if row else None


def restore_deleted_offer_photo_for_storage(
    session: DbSession,
    *,
    offer_id: int,
    storage_id: str,
    position: int = 0,
) -> int | None:
    now = utc_now_iso()
    row = session.execute(
        """
        WITH candidate AS (
            SELECT op.id
            FROM offer_photos op
            WHERE op.offer_id = %s
              AND op.storage_id = %s
              AND op.deleted_at IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM offers o
                  WHERE o.id = op.offer_id
                    AND o.deleted_at IS NULL
              )
              AND EXISTS (
                  SELECT 1
                  FROM storage_objects so
                  WHERE so.id = op.storage_id
                    AND so.status = 'ready'
                    AND so.purpose = 'offer_photo'
                    AND so.agency_id = op.agency_id
              )
            ORDER BY op.id DESC
            LIMIT 1
        )
        UPDATE offer_photos op
        SET deleted_at = NULL,
            delete_origin = NULL,
            delete_parent_scope = NULL,
            delete_parent_id = NULL,
            position = %s,
            updated_at = %s,
            row_version = row_version + 1
        FROM candidate
        WHERE op.id = candidate.id
        RETURNING op.id
        """,
        (offer_id, storage_id, position, now),
    ).fetchone()
    return row_int(row, "id") if row else None


def count_active_storage_refs(session: DbSession, *, storage_id: str) -> int:
    row = session.execute(
        """
        SELECT COUNT(*) AS count
        FROM offer_photos
        WHERE storage_id = %s AND deleted_at IS NULL
        """,
        (storage_id,),
    ).fetchone()
    return row_int(row, "count") if row else 0


def create_offer_photo(
    session: DbSession,
    *,
    offer_id: int,
    storage_id: str,
    position: int = 0,
) -> tuple[int, bool]:
    now = utc_now_iso()
    row = session.execute(
        """
        INSERT INTO offer_photos
        (agency_id, offer_id, storage_id, position, created_at, updated_at)
        SELECT
            o.agency_id,
            o.id,
            %s, %s, %s, %s
        FROM offers o
        WHERE o.id = %s AND o.deleted_at IS NULL
        ON CONFLICT (offer_id, storage_id) WHERE deleted_at IS NULL
        DO UPDATE SET updated_at = offer_photos.updated_at
        RETURNING id, (xmax = 0) AS inserted
        """,
        (storage_id, position, now, now, offer_id),
    ).fetchone()
    if not row:
        raise NotFoundError("Offer not found")
    return row_int(row, "id"), bool(row.get("inserted"))


def mark_offer_photo_deleted(
    session: DbSession,
    *,
    photo_id: int,
    delete_origin: str = PHOTO_DELETE_ORIGIN_MANUAL,
    delete_parent_scope: str | None = None,
    delete_parent_id: int | None = None,
) -> bool:
    now = utc_now_iso()
    session.execute(
        """
        UPDATE offer_photos
        SET deleted_at = %s,
            delete_origin = %s,
            delete_parent_scope = %s,
            delete_parent_id = %s,
            updated_at = %s,
            row_version = row_version + 1
        WHERE id = %s AND deleted_at IS NULL
        """,
        (now, delete_origin, delete_parent_scope, delete_parent_id, now, photo_id),
    )
    return session.rowcount > 0


def mark_offer_photos_deleted_for_offers(
    session: DbSession,
    *,
    offer_ids: list[int],
    delete_origin: str,
    delete_parent_scope: str,
    delete_parent_id: int,
    include_deleted_for_cleanup: bool = False,
) -> list[str]:
    if not offer_ids:
        return []
    now = utc_now_iso()
    deleted_filter = "" if include_deleted_for_cleanup else "AND deleted_at IS NULL"
    rows = session.execute(
        f"""
        UPDATE offer_photos
        SET deleted_at = COALESCE(deleted_at, %s),
            delete_origin = %s,
            delete_parent_scope = %s,
            delete_parent_id = %s,
            updated_at = %s,
            row_version = row_version + 1
        WHERE offer_id = ANY(%s)
          {deleted_filter}
        RETURNING storage_id
        """,
        (now, delete_origin, delete_parent_scope, delete_parent_id, now, offer_ids),
    ).fetchall()
    return [str(row.get("storage_id")) for row in rows if row.get("storage_id")]


def restore_offer_photos_for_offers(
    session: DbSession,
    *,
    offer_ids: list[int],
    delete_origin: str,
    delete_parent_scope: str,
    delete_parent_id: int,
) -> int:
    if not offer_ids:
        return 0
    now = utc_now_iso()
    session.execute(
        """
        UPDATE offer_photos
        SET deleted_at = NULL,
            delete_origin = NULL,
            delete_parent_scope = NULL,
            delete_parent_id = NULL,
            updated_at = %s,
            row_version = row_version + 1
        WHERE offer_id = ANY(%s)
          AND deleted_at IS NOT NULL
          AND delete_origin = %s
          AND delete_parent_scope = %s
          AND delete_parent_id = %s
          AND EXISTS (
              SELECT 1
              FROM storage_objects so
              WHERE so.id = offer_photos.storage_id
                AND so.status = 'ready'
                AND so.purpose = 'offer_photo'
                AND so.agency_id = offer_photos.agency_id
          )
        """,
        (now, offer_ids, delete_origin, delete_parent_scope, delete_parent_id),
    )
    return session.rowcount


def list_storage_ids_for_offer_ids(
    session: DbSession,
    *,
    offer_ids: list[int],
    include_deleted: bool = False,
    delete_origin: str | None = None,
    delete_parent_scope: str | None = None,
    delete_parent_id: int | None = None,
) -> list[str]:
    if not offer_ids:
        return []
    sql = "SELECT storage_id FROM offer_photos WHERE offer_id = ANY(%s)"
    params: list[object] = [offer_ids]
    if not include_deleted:
        sql += " AND deleted_at IS NULL"
    if delete_origin is not None:
        sql += " AND delete_origin = %s"
        params.append(delete_origin)
    if delete_parent_scope is not None:
        sql += " AND delete_parent_scope = %s"
        params.append(delete_parent_scope)
    if delete_parent_id is not None:
        sql += " AND delete_parent_id = %s"
        params.append(delete_parent_id)
    rows = session.execute(sql, params).fetchall()
    return [str(row.get("storage_id")) for row in rows if row.get("storage_id")]
