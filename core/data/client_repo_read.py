"""
Read operations for clients.
"""

from __future__ import annotations

from core.data.read_helpers import (
    build_like_search_conditions,
    build_people_search_conditions,
)
from core.data.surface_cache_generation import CLIENTS_SURFACE, agency_scope_key, read_generation
from core.data.tenant_scope import tenant_condition
from core.matcher.ports.db import DbSession
from core.models import Client
from core.models_cast import as_int, row_at
from core.utils.row_casts import row_int

_CLIENT_LIST_SELECT = (
    "c.id, c.family_name, c.phone, c.remarks, c.tags, c.is_vip, c.status, "
    "c.deleted_at, c.created_at, c.created_loc, c.updated_at, c.row_version, "
    "c.family_name_enc, c.phone_enc"
)


def fetch_clients(
    session: DbSession,
    limit: int | None = None,
    offset: int = 0,
    search: str = "",
    status: str | None = "active",
    include_deleted: bool = False,
) -> list[Client]:
    """
    Fetch clients from DB (with optional pagination and SQL-level filtering).
    """
    query, params = _build_client_query(False, limit, offset, search, status, include_deleted)
    rows = session.execute(query, params).fetchall()
    return [Client.from_row(row) for row in rows]


def fetch_clients_cursor(
    session: DbSession,
    *,
    limit: int = 100,
    cursor: int | None = None,
    search: str = "",
    status: str | None = "active",
    include_deleted: bool = False,
) -> list[Client]:
    """Fetch clients using newest-first cursor pagination."""
    select_clause = f"SELECT {'DISTINCT ' if search else ''}{_CLIENT_LIST_SELECT}"
    sql = f"{select_clause} FROM clients c"
    params: list[object] = []

    if search:
        sql += (
            " LEFT JOIN demandes d ON c.id = d.client_id "
            "AND d.agency_id = c.agency_id AND d.deleted_at IS NULL"
        )

    conditions: list[str] = []
    tenant_sql, tenant_params = tenant_condition("c")
    if tenant_sql is not None:
        conditions.append(tenant_sql)
        params.extend(tenant_params)

    if status is not None and status != "":
        conditions.append("c.status = %s")
        params.append(status)

    if not include_deleted:
        conditions.append("c.deleted_at IS NULL")

    if cursor is not None:
        conditions.append("c.id < %s")
        params.append(cursor)

    if search:
        search_cond, search_params = build_people_search_conditions(
            search=search,
            person_alias="c",
            join_fields=("d.type", "d.action", "d.locations"),
        )
        conditions.append(search_cond)
        params.extend(search_params)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY c.id DESC LIMIT %s"
    params.append(limit)

    rows = session.execute(sql, params).fetchall()
    return [Client.from_row(row) for row in rows]


def get_total_client_count(
    session: DbSession,
    search: str = "",
    status: str | None = "active",
    include_deleted: bool = False,
) -> int:
    """Get total number of filtered clients for pagination."""
    query, params = _build_client_query(True, None, 0, search, status, include_deleted)
    row = session.execute(query, params).fetchone()
    return as_int(row_at(row, 0)) if row else 0


def get_clients_surface_generation(session: DbSession, *, agency_id: int) -> int:
    """Return the cheap durable generation for client-facing list/count reads."""
    resolved_agency_id = int(agency_id)
    return int(
        read_generation(
            session,
            surface=CLIENTS_SURFACE,
            scope_key=agency_scope_key(resolved_agency_id),
            agency_id=resolved_agency_id,
        )
    )


def _build_client_query(
    count_only: bool,
    limit: int | None,
    offset: int,
    search: str,
    status: str | None,
    include_deleted: bool,
) -> tuple[str, list[object]]:
    """Helper to build a complex filtered query for clients."""
    if count_only:
        sql = "SELECT COUNT(DISTINCT c.id)" if search else "SELECT COUNT(*)"
    else:
        sql = f"SELECT {'DISTINCT ' if search else ''}{_CLIENT_LIST_SELECT}"

    sql += " FROM clients c"

    if search:
        sql += (
            " LEFT JOIN demandes d ON c.id = d.client_id "
            "AND d.agency_id = c.agency_id AND d.deleted_at IS NULL"
        )

    conditions: list[str] = []
    params: list[object] = []
    tenant_sql, tenant_params = tenant_condition("c")
    if tenant_sql is not None:
        conditions.append(tenant_sql)
        params.extend(tenant_params)

    if status is not None and status != "":
        conditions.append("c.status = %s")
        params.append(status)

    if not include_deleted:
        conditions.append("c.deleted_at IS NULL")

    if search:
        search_cond, search_params = build_people_search_conditions(
            search=search,
            person_alias="c",
            join_fields=("d.type", "d.action", "d.locations"),
        )
        conditions.append(search_cond)
        params.extend(search_params)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    if not count_only:
        sql += " ORDER BY c.id DESC"
        if limit is not None:
            sql += " LIMIT %s OFFSET %s"
            params.extend([limit, offset])

    return sql, params


def get_client_by_id(
    session: DbSession,
    client_id: int,
    include_deleted: bool = False,
) -> Client | None:
    """Fetch a single client by ID as typed Client object."""
    conditions = ["c.id = %s"]
    params: list[object] = [client_id]
    tenant_sql, tenant_params = tenant_condition("c")
    if tenant_sql is not None:
        conditions.append(tenant_sql)
        params.extend(tenant_params)

    if not include_deleted:
        conditions.append("c.deleted_at IS NULL")

    sql = "SELECT c.* FROM clients c WHERE " + " AND ".join(conditions)
    row = session.execute(sql, params).fetchone()
    return Client.from_row(row) if row else None


def get_client_by_id_for_update(
    session: DbSession,
    client_id: int,
    include_deleted: bool = False,
) -> Client | None:
    """Fetch a single client row by ID and lock it for update in the current transaction."""
    conditions = ["c.id = %s"]
    params: list[object] = [client_id]
    tenant_sql, tenant_params = tenant_condition("c")
    if tenant_sql is not None:
        conditions.append(tenant_sql)
        params.extend(tenant_params)

    if not include_deleted:
        conditions.append("c.deleted_at IS NULL")

    sql = "SELECT c.* FROM clients c WHERE " + " AND ".join(conditions) + " FOR UPDATE"
    row = session.execute(sql, params).fetchone()
    return Client.from_row(row) if row else None


def find_client_ids_by_phone(
    session: DbSession,
    phone: str,
    exclude_id: int | None = None,
) -> list[int]:
    """Return client IDs matching a phone number, excluding an ID if provided."""
    if not phone:
        return []
    conditions = ["c.phone = %s", "c.deleted_at IS NULL"]
    params: list[object] = [phone]
    tenant_sql, tenant_params = tenant_condition("c")
    if tenant_sql is not None:
        conditions.append(tenant_sql)
        params.extend(tenant_params)

    if exclude_id is not None and exclude_id >= 0:
        conditions.append("c.id != %s")
        params.append(exclude_id)

    sql = "SELECT c.id FROM clients c WHERE " + " AND ".join(conditions)
    rows = session.execute(sql, params).fetchall()
    return [row_int(row, "id") for row in rows]


def fetch_deleted_clients(
    session: DbSession,
    limit: int | None = None,
    offset: int = 0,
    search: str = "",
) -> list[Client]:
    """Fetch soft-deleted clients for trash management."""
    sql = "SELECT c.* FROM clients c"
    params: list[object] = []

    if search:
        sql += (
            " LEFT JOIN demandes d ON c.id = d.client_id "
            "AND d.agency_id = c.agency_id AND d.deleted_at IS NULL"
        )

    conditions = ["c.deleted_at IS NOT NULL"]
    tenant_sql, tenant_params = tenant_condition("c")
    if tenant_sql is not None:
        conditions.append(tenant_sql)
        params.extend(tenant_params)

    if search:
        search_cond, search_params = build_like_search_conditions(
            search=search,
            columns=(
                "c.family_name",
                "c.phone",
                "c.remarks",
                "d.type",
                "d.action",
                "d.locations",
            ),
        )
        conditions.append(search_cond)
        params.extend(search_params)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY c.deleted_at DESC"
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])

    rows = session.execute(sql, params).fetchall()
    return [Client.from_row(row) for row in rows]


def get_total_deleted_client_count(
    session: DbSession,
    search: str = "",
) -> int:
    """Get total number of deleted clients for pagination."""
    sql = "SELECT COUNT(DISTINCT c.id) FROM clients c"
    params: list[object] = []

    if search:
        sql += (
            " LEFT JOIN demandes d ON c.id = d.client_id "
            "AND d.agency_id = c.agency_id AND d.deleted_at IS NULL"
        )

    conditions = ["c.deleted_at IS NOT NULL"]
    tenant_sql, tenant_params = tenant_condition("c")
    if tenant_sql is not None:
        conditions.append(tenant_sql)
        params.extend(tenant_params)

    if search:
        search_cond, search_params = build_like_search_conditions(
            search=search,
            columns=(
                "c.family_name",
                "c.phone",
                "c.remarks",
                "d.type",
                "d.action",
                "d.locations",
            ),
        )
        conditions.append(search_cond)
        params.extend(search_params)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    row = session.execute(sql, params).fetchone()
    return as_int(row_at(row, 0)) if row else 0
