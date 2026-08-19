"""
Visit CRUD operations for CRM.
"""

from __future__ import annotations

from core.matcher.ports.db import DbSession
from core.models import Visit
from core.models_cast import as_int, row_at
from core.shared_types import VisitData
from core.utils.time import utc_now_iso


def create_visit(session: DbSession, data: VisitData) -> int:
    """Create a new visit. Returns visit ID."""
    now = utc_now_iso()
    session.execute(
        """
        INSERT INTO visits
        (agency_id, client_id, listing_id, scheduled_date, scheduled_time, status, notes, notes_enc, created_at, updated_at)
        SELECT
            c.agency_id,
            c.id,
            l.id,
            %s, %s, %s, %s, %s, %s, %s
        FROM clients c
        JOIN listings l ON l.id = %s AND l.deleted_at IS NULL
        WHERE c.id = %s
          AND c.deleted_at IS NULL
          AND c.agency_id = l.agency_id
        RETURNING id
    """,
        (
            data["scheduled_date"],
            data.get("scheduled_time", "10:00"),
            data.get("status", "scheduled"),
            data.get("notes", ""),
            data.get("notes_enc", ""),
            now,
            now,
            data["listing_id"],
            data["client_id"],
        ),
    )
    visit_id = session.lastrowid
    if not visit_id:
        raise ValueError("client and listing must belong to the same active agency")
    return int(visit_id or 0)


def fetch_visits(
    session: DbSession,
    status: str | None = None,
    client_id: str | int | None = None,
    scheduled_date: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Visit]:
    query = """
        SELECT v.*, c.family_name as client_name, ol.location as listing_location
        FROM visits v
        LEFT JOIN clients c ON v.client_id = c.id
        LEFT JOIN listings l ON v.listing_id = l.id
        LEFT JOIN LATERAL (
            SELECT o.location
            FROM offers o
            WHERE o.listing_id = l.id
              AND o.deleted_at IS NULL
            ORDER BY o.updated_at DESC NULLS LAST, o.id DESC
            LIMIT 1
        ) ol ON true
        WHERE v.deleted_at IS NULL
            AND (c.deleted_at IS NULL OR c.id IS NULL)
            AND (l.deleted_at IS NULL OR l.id IS NULL)
    """
    params: list[object] = []
    if status:
        query += " AND v.status = %s"
        params.append(status)
    if client_id:
        query += " AND v.client_id = %s"
        params.append(client_id)
    if scheduled_date:
        query += " AND v.scheduled_date = %s"
        params.append(scheduled_date)
    query += " ORDER BY v.scheduled_date DESC, v.scheduled_time DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])
    rows = session.execute(query, params).fetchall()
    return [Visit.from_row(row) for row in rows]


def get_total_visit_count(
    session: DbSession,
    status: str | None = None,
    client_id: str | int | None = None,
    scheduled_date: str | None = None,
) -> int:
    query = (
        "SELECT COUNT(*) FROM visits v LEFT JOIN clients c ON v.client_id = c.id "
        "LEFT JOIN listings l ON v.listing_id = l.id WHERE v.deleted_at IS NULL"
    )
    params: list[object] = []
    if status:
        query += " AND v.status = %s"
        params.append(status)
    if client_id:
        query += " AND v.client_id = %s"
        params.append(client_id)
    if scheduled_date:
        query += " AND v.scheduled_date = %s"
        params.append(scheduled_date)
    row = session.execute(query, params).fetchone()
    return as_int(row_at(row, 0)) if row else 0


def update_visit(session: DbSession, visit_id: int, data: dict[str, object]) -> None:
    row_version = as_int(data.get("row_version"), default=0)
    if row_version <= 0:
        raise ValueError("row_version required")
    session.execute(
        """
        UPDATE visits
        SET status = %s, notes = %s, notes_enc = %s, updated_at = %s,
            row_version = row_version + 1
        WHERE id = %s AND deleted_at IS NULL AND row_version = %s
    """,
        (
            data.get("status", "scheduled"),
            data.get("notes", ""),
            data.get("notes_enc", ""),
            utc_now_iso(),
            visit_id,
            row_version,
        ),
    )


def delete_visit(session: DbSession, visit_id: int) -> None:
    now = utc_now_iso()
    session.execute(
        "UPDATE visits SET deleted_at = %s, updated_at = %s, row_version = row_version + 1 WHERE id = %s",
        (now, now, visit_id),
    )


def fetch_deleted_visits(session: DbSession, limit: int = 100, offset: int = 0) -> list[Visit]:
    query = "SELECT v.*, c.family_name as client_name, ol.location as listing_location FROM visits v LEFT JOIN clients c ON v.client_id = c.id LEFT JOIN listings l ON v.listing_id = l.id LEFT JOIN LATERAL (SELECT o.location FROM offers o WHERE o.listing_id = l.id AND o.deleted_at IS NULL ORDER BY o.updated_at DESC, o.id DESC LIMIT 1) ol ON true WHERE v.deleted_at IS NOT NULL ORDER BY v.deleted_at DESC LIMIT %s OFFSET %s"
    rows = session.execute(query, [limit, offset]).fetchall()
    return [Visit.from_row(row) for row in rows]


def get_total_deleted_visit_count(session: DbSession) -> int:
    row = session.execute("SELECT COUNT(*) FROM visits WHERE deleted_at IS NOT NULL").fetchone()
    return as_int(row_at(row, 0)) if row else 0


def restore_visit(session: DbSession, visit_id: int) -> None:
    session.execute(
        "UPDATE visits SET deleted_at = NULL, updated_at = %s WHERE id = %s",
        (utc_now_iso(), visit_id),
    )


def purge_visit(session: DbSession, visit_id: int) -> None:
    session.execute("DELETE FROM visits WHERE id = %s", (visit_id,))


def get_visit_by_id(
    session: DbSession, visit_id: int, include_deleted: bool = False
) -> Visit | None:
    query = "SELECT v.*, c.family_name as client_name, ol.location as listing_location FROM visits v LEFT JOIN clients c ON v.client_id = c.id LEFT JOIN listings l ON v.listing_id = l.id LEFT JOIN LATERAL (SELECT o.location FROM offers o WHERE o.listing_id = l.id AND o.deleted_at IS NULL ORDER BY o.updated_at DESC, o.id DESC LIMIT 1) ol ON true WHERE v.id = %s"
    if not include_deleted:
        query += " AND v.deleted_at IS NULL"
    row = session.execute(query, [visit_id]).fetchone()
    return Visit.from_row(row) if row else None
