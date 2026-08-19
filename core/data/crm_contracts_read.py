"""
Read/query operations for CRM contracts.
"""

from __future__ import annotations

from core.matcher.ports.db import DbSession
from core.models import Contract
from core.models_cast import as_int, row_at


def fetch_contracts(
    session: DbSession,
    status: str | None = None,
    contract_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Contract]:
    """Fetch contracts as typed Contract objects with optional filters. RLS filters by agency_id."""
    query = """
        SELECT c.*, cl.family_name as client_name, ol.location as listing_location
        FROM contracts c
        LEFT JOIN clients cl ON c.client_id = cl.id
        LEFT JOIN listings l ON c.listing_id = l.id
        LEFT JOIN LATERAL (
            SELECT o.location
            FROM offers o
            WHERE o.listing_id = l.id
              AND o.deleted_at IS NULL
            ORDER BY o.updated_at DESC NULLS LAST, o.id DESC
            LIMIT 1
        ) ol ON true
        WHERE c.deleted_at IS NULL
            AND (cl.deleted_at IS NULL OR cl.id IS NULL)
            AND (l.deleted_at IS NULL OR l.id IS NULL)
    """
    params: list[object] = []

    if status:
        query += " AND c.status = %s"
        params.append(status)

    if contract_type:
        query += " AND c.contract_type = %s"
        params.append(contract_type)

    query += " ORDER BY c.created_at DESC"
    query += " LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    rows = session.execute(query, params).fetchall()
    return [Contract.from_row(row) for row in rows]


def get_total_contract_count(
    session: DbSession,
    status: str | None = None,
    contract_type: str | None = None,
) -> int:
    """Get total number of contracts for pagination. RLS filters by agency_id."""
    query = """
        SELECT COUNT(*) FROM contracts c
        LEFT JOIN clients cl ON c.client_id = cl.id
        LEFT JOIN listings l ON c.listing_id = l.id
        WHERE c.deleted_at IS NULL
          AND (cl.deleted_at IS NULL OR cl.id IS NULL)
          AND (l.deleted_at IS NULL OR l.id IS NULL)
    """
    params: list[object] = []

    if status:
        query += " AND c.status = %s"
        params.append(status)

    if contract_type:
        query += " AND c.contract_type = %s"
        params.append(contract_type)

    row = session.execute(query, params).fetchone()
    return as_int(row_at(row, 0)) if row else 0


def get_contract_by_id(
    session: DbSession,
    contract_id: int,
    include_deleted: bool = False,
) -> Contract | None:
    """Fetch a single contract by ID.

    Args:
        agency_id: If provided, verify contract belongs to this agency.
    """
    query = """
        SELECT c.*, cl.family_name as client_name, ol.location as listing_location
        FROM contracts c
        LEFT JOIN clients cl ON c.client_id = cl.id
        LEFT JOIN listings l ON c.listing_id = l.id
        LEFT JOIN LATERAL (
            SELECT o.location
            FROM offers o
            WHERE o.listing_id = l.id
              AND o.deleted_at IS NULL
            ORDER BY o.updated_at DESC NULLS LAST, o.id DESC
            LIMIT 1
        ) ol ON true
        WHERE c.id = %s
    """
    params: list[object] = [contract_id]
    where_clause = ""
    if not include_deleted:
        where_clause += " AND c.deleted_at IS NULL"

    row = session.execute(query + where_clause, params).fetchone()
    return Contract.from_row(row) if row else None


def fetch_pending_contracts(session: DbSession) -> list[Contract]:
    """Fetch contracts awaiting signature."""
    return fetch_contracts(session, status="pending_signature")


def fetch_deleted_contracts(
    session: DbSession, limit: int = 100, offset: int = 0
) -> list[Contract]:
    """Fetch soft-deleted contracts for trash management. RLS filters by agency_id."""
    query = """
        SELECT c.*, cl.family_name as client_name, ol.location as listing_location
        FROM contracts c
        LEFT JOIN clients cl ON c.client_id = cl.id
        LEFT JOIN listings l ON c.listing_id = l.id
        LEFT JOIN LATERAL (
            SELECT o.location
            FROM offers o
            WHERE o.listing_id = l.id
              AND o.deleted_at IS NULL
            ORDER BY o.updated_at DESC NULLS LAST, o.id DESC
            LIMIT 1
        ) ol ON true
        WHERE c.deleted_at IS NOT NULL
    """
    params: list[object] = []

    query += " ORDER BY c.deleted_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    rows = session.execute(query, params).fetchall()
    return [Contract.from_row(row) for row in rows]


def get_total_deleted_contract_count(session: DbSession) -> int:
    """Get total number of deleted contracts for pagination. RLS filters by agency_id."""
    query = """
        SELECT COUNT(*) FROM contracts c
        LEFT JOIN clients cl ON c.client_id = cl.id
        LEFT JOIN listings l ON c.listing_id = l.id
        WHERE c.deleted_at IS NOT NULL
    """
    params: list[object] = []

    row = session.execute(query, params).fetchone()
    return as_int(row_at(row, 0)) if row else 0
