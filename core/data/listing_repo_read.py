"""
Read operations for listings.
"""

from __future__ import annotations

from core.data.read_helpers import (
    build_like_search_conditions,
    build_people_search_conditions,
)
from core.data.surface_cache_generation import LISTINGS_SURFACE, agency_scope_key, read_generation
from core.data.tenant_scope import tenant_condition
from core.matcher.ports.db import DbSession
from core.models import Listing
from core.models_cast import as_int, row_at
from core.utils.row_casts import row_int

_LISTING_LIST_SELECT = (
    "l.id, l.family_name, l.phone, l.remarks, l.is_vip, l.status, "
    "l.deleted_at, l.created_at, l.created_loc, l.updated_at, l.row_version, "
    "l.family_name_enc, l.phone_enc"
)


def fetch_listings(
    session: DbSession,
    limit: int | None = None,
    offset: int = 0,
    search: str = "",
    status: str | None = "available",
    include_deleted: bool = False,
) -> list[Listing]:
    """
    Fetch listings from DB (with optional pagination and SQL-level filtering).
    """
    query, params = _build_listing_query(False, limit, offset, search, status, include_deleted)
    rows = session.execute(query, params).fetchall()
    return [Listing.from_row(row) for row in rows]


def fetch_listings_cursor(
    session: DbSession,
    *,
    limit: int = 100,
    cursor: int | None = None,
    search: str = "",
    status: str | None = "available",
    include_deleted: bool = False,
) -> list[Listing]:
    """Fetch listings using newest-first cursor pagination."""
    select_clause = f"SELECT {'DISTINCT ' if search else ''}{_LISTING_LIST_SELECT}"
    sql = f"{select_clause} FROM listings l"
    params: list[object] = []

    if search:
        sql += (
            " LEFT JOIN offers o ON l.id = o.listing_id "
            "AND o.agency_id = l.agency_id AND o.deleted_at IS NULL"
        )

    conditions: list[str] = []
    tenant_sql, tenant_params = tenant_condition("l")
    if tenant_sql is not None:
        conditions.append(tenant_sql)
        params.extend(tenant_params)

    if status is not None and status != "":
        conditions.append("l.status = %s")
        params.append(status)

    if not include_deleted:
        conditions.append("l.deleted_at IS NULL")

    if cursor is not None:
        conditions.append("l.id < %s")
        params.append(cursor)

    if search:
        search_cond, search_params = build_people_search_conditions(
            search=search,
            person_alias="l",
            join_fields=("o.type", "o.action", "o.location", "o.wilaya"),
        )
        conditions.append(search_cond)
        params.extend(search_params)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY l.id DESC LIMIT %s"
    params.append(limit)

    rows = session.execute(sql, params).fetchall()
    return [Listing.from_row(row) for row in rows]


def get_total_listing_count(
    session: DbSession,
    search: str = "",
    status: str | None = "available",
    include_deleted: bool = False,
) -> int:
    """Get total number of filtered listings for pagination."""
    query, params = _build_listing_query(True, None, 0, search, status, include_deleted)
    row = session.execute(query, params).fetchone()
    return as_int(row_at(row, 0)) if row else 0


def get_listings_surface_generation(session: DbSession, *, agency_id: int) -> int:
    """Return the cheap durable generation for listing-facing list/count reads."""
    resolved_agency_id = int(agency_id)
    return int(
        read_generation(
            session,
            surface=LISTINGS_SURFACE,
            scope_key=agency_scope_key(resolved_agency_id),
            agency_id=resolved_agency_id,
        )
    )


def _build_listing_query(
    count_only: bool,
    limit: int | None,
    offset: int,
    search: str,
    status: str | None,
    include_deleted: bool,
) -> tuple[str, list[object]]:
    """Helper to build a complex filtered query for listings."""
    if count_only:
        sql = "SELECT COUNT(DISTINCT l.id)" if search else "SELECT COUNT(*)"
    else:
        sql = f"SELECT {'DISTINCT ' if search else ''}{_LISTING_LIST_SELECT}"

    sql += " FROM listings l"

    if search:
        sql += (
            " LEFT JOIN offers o ON l.id = o.listing_id "
            "AND o.agency_id = l.agency_id AND o.deleted_at IS NULL"
        )

    conditions: list[str] = []
    params: list[object] = []
    tenant_sql, tenant_params = tenant_condition("l")
    if tenant_sql is not None:
        conditions.append(tenant_sql)
        params.extend(tenant_params)

    if status is not None and status != "":
        conditions.append("l.status = %s")
        params.append(status)

    if not include_deleted:
        conditions.append("l.deleted_at IS NULL")

    if search:
        search_cond, search_params = build_people_search_conditions(
            search=search,
            person_alias="l",
            join_fields=("o.type", "o.action", "o.location", "o.wilaya"),
        )
        conditions.append(search_cond)
        params.extend(search_params)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    if not count_only:
        sql += " ORDER BY l.id DESC"
        if limit is not None:
            sql += " LIMIT %s OFFSET %s"
            params.extend([limit, offset])

    return sql, params


def get_listing_by_id(
    session: DbSession,
    listing_id: int,
    include_deleted: bool = False,
) -> Listing | None:
    """Fetch a single listing by ID as typed Listing object."""
    conditions = ["l.id = %s"]
    params: list[object] = [listing_id]
    tenant_sql, tenant_params = tenant_condition("l")
    if tenant_sql is not None:
        conditions.append(tenant_sql)
        params.extend(tenant_params)

    if not include_deleted:
        conditions.append("l.deleted_at IS NULL")

    sql = "SELECT l.* FROM listings l WHERE " + " AND ".join(conditions)
    row = session.execute(sql, params).fetchone()
    return Listing.from_row(row) if row else None


def get_listing_by_id_for_update(
    session: DbSession,
    listing_id: int,
    include_deleted: bool = False,
) -> Listing | None:
    """Fetch a single listing row by ID and lock it for update in the current transaction."""
    conditions = ["l.id = %s"]
    params: list[object] = [listing_id]
    tenant_sql, tenant_params = tenant_condition("l")
    if tenant_sql is not None:
        conditions.append(tenant_sql)
        params.extend(tenant_params)

    if not include_deleted:
        conditions.append("l.deleted_at IS NULL")

    sql = "SELECT l.* FROM listings l WHERE " + " AND ".join(conditions) + " FOR UPDATE"
    row = session.execute(sql, params).fetchone()
    return Listing.from_row(row) if row else None


def find_listing_ids_by_phone(
    session: DbSession,
    phone: str,
    exclude_id: int | None = None,
) -> list[int]:
    """Return listing IDs matching a phone number, excluding an ID if provided."""
    if not phone:
        return []
    conditions = ["l.phone = %s", "l.deleted_at IS NULL"]
    params: list[object] = [phone]
    tenant_sql, tenant_params = tenant_condition("l")
    if tenant_sql is not None:
        conditions.append(tenant_sql)
        params.extend(tenant_params)

    if exclude_id is not None and exclude_id >= 0:
        conditions.append("l.id != %s")
        params.append(exclude_id)

    sql = "SELECT l.id FROM listings l WHERE " + " AND ".join(conditions)
    rows = session.execute(sql, params).fetchall()
    return [row_int(row, "id") for row in rows]


def fetch_deleted_listings(
    session: DbSession,
    limit: int | None = None,
    offset: int = 0,
    search: str = "",
) -> list[Listing]:
    """Fetch soft-deleted listings for trash management."""
    sql = "SELECT l.* FROM listings l"
    params: list[object] = []

    if search:
        sql += (
            " LEFT JOIN offers o ON l.id = o.listing_id "
            "AND o.agency_id = l.agency_id AND o.deleted_at IS NULL"
        )

    conditions = ["l.deleted_at IS NOT NULL"]
    tenant_sql, tenant_params = tenant_condition("l")
    if tenant_sql is not None:
        conditions.append(tenant_sql)
        params.extend(tenant_params)

    if search:
        search_cond, search_params = build_like_search_conditions(
            search=search,
            columns=(
                "l.family_name",
                "l.phone",
                "l.remarks",
                "o.type",
                "o.action",
                "o.location",
                "o.wilaya",
            ),
        )
        conditions.append(search_cond)
        params.extend(search_params)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY l.deleted_at DESC"
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])

    rows = session.execute(sql, params).fetchall()
    return [Listing.from_row(row) for row in rows]


def get_total_deleted_listing_count(
    session: DbSession,
    search: str = "",
) -> int:
    """Get total number of deleted listings for pagination."""
    sql = "SELECT COUNT(DISTINCT l.id) FROM listings l"
    params: list[object] = []

    if search:
        sql += (
            " LEFT JOIN offers o ON l.id = o.listing_id "
            "AND o.agency_id = l.agency_id AND o.deleted_at IS NULL"
        )

    conditions = ["l.deleted_at IS NOT NULL"]
    tenant_sql, tenant_params = tenant_condition("l")
    if tenant_sql is not None:
        conditions.append(tenant_sql)
        params.extend(tenant_params)

    if search:
        search_cond, search_params = build_like_search_conditions(
            search=search,
            columns=(
                "l.family_name",
                "l.phone",
                "l.remarks",
                "o.type",
                "o.action",
                "o.location",
                "o.wilaya",
            ),
        )
        conditions.append(search_cond)
        params.extend(search_params)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    row = session.execute(sql, params).fetchone()
    return as_int(row_at(row, 0)) if row else 0
