"""
Write operations for clients.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from core.contracts.import_batch_refs import CreatedRowRef
from core.data.errors import ConflictError, NotFoundError
from core.data.surface_cache_generation import (
    CLIENTS_SURFACE,
    agency_scope_key,
    bump_generation,
    bump_generations,
)
from core.data.types import ClientInput
from core.matcher.ports.db import DbSession
from core.models_cast import as_int
from core.models_client import Client
from core.utils.time import normalize_timestamp, utc_now_iso
from server.pg.tenant_context import resolve_agency_id

logger = logging.getLogger(__name__)


def _is_unique_violation(exc: Exception) -> bool:
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate == "23505":
        return True
    message = str(exc).lower()
    return "duplicate key value violates unique constraint" in message


def _resolve_agency_id(d: ClientInput) -> int:
    agency_id = resolve_agency_id(explicit=as_int(d.get("agency_id"), default=0) or None)
    if not isinstance(agency_id, int) or agency_id <= 0:
        raise ValueError("agency_id is required for client writes")
    return int(agency_id)


def _distinct_agency_ids(rows: Sequence[ClientInput]) -> list[int]:
    return sorted({_resolve_agency_id(row) for row in rows if row})


def _normalize_source_ordinals(
    *,
    source_ordinals: Sequence[int] | None,
    expected_count: int,
    context: str,
) -> list[int]:
    if source_ordinals is None:
        return list(range(max(0, int(expected_count))))
    normalized = [int(value) for value in source_ordinals]
    if len(normalized) != max(0, int(expected_count)):
        raise ValueError(
            f"{context} received {len(normalized)} source ordinals for "
            f"{int(expected_count)} input rows."
        )
    if any(value < 0 for value in normalized):
        raise ValueError(f"{context} requires non-negative source ordinals.")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{context} requires unique source ordinals.")
    return normalized


def _allocate_created_row_refs(
    session: DbSession,
    *,
    table_name: str,
    source_ordinals: Sequence[int],
    context: str,
) -> list[CreatedRowRef]:
    normalized_ordinals = _normalize_source_ordinals(
        source_ordinals=source_ordinals,
        expected_count=len(source_ordinals),
        context=context,
    )
    if not normalized_ordinals:
        return []
    rows = session.execute(
        """
        SELECT nextval(pg_get_serial_sequence(%s, %s)) AS id
        FROM generate_series(1, %s::integer)
        """,
        (table_name, "id", len(normalized_ordinals)),
    ).fetchall()
    if len(rows) != len(normalized_ordinals):
        raise ValueError(
            f"{context} allocated {len(rows)} ids for {len(normalized_ordinals)} input rows."
        )
    return [
        CreatedRowRef(
            source_ordinal=normalized_ordinals[index],
            created_id=int(str(row["id"])),
        )
        for index, row in enumerate(rows)
    ]


def _require_inserted_ids_match_allocated(
    *,
    returned_rows: Sequence[dict[str, object]],
    created_rows: Sequence[CreatedRowRef],
    context: str,
) -> None:
    returned_ids = [int(str(row["id"])) for row in returned_rows]
    expected_ids = [int(ref.created_id) for ref in created_rows]
    if len(returned_ids) != len(expected_ids):
        raise ValueError(
            f"{context} returned {len(returned_ids)} ids for {len(expected_ids)} allocated rows."
        )
    if set(returned_ids) != set(expected_ids):
        raise ValueError(f"{context} returned ids that did not match the allocated insert ids.")


def upsert_client(session: DbSession, d: ClientInput) -> int:
    """Insert or update a client. Returns the client ID.

    On update, agency_id is NOT modified to prevent cross-tenant data movement.
    """
    client_id = d.get("id")

    if client_id is not None:
        row_version = as_int(d.get("row_version"), default=0)
        if row_version <= 0:
            raise ValueError("row_version is required for client updates")
        # UPDATE: RLS handles the agency_id isolation automatically
        try:
            updated = session.execute(
                """
                UPDATE clients SET
                    family_name = %s,
                    phone = %s,
                    remarks = %s,
                    tags = %s,
                    is_vip = %s,
                    status = COALESCE(NULLIF(%s, ''), clients.status, 'active'),
                    updated_at = %s,
                    row_version = row_version + 1,
                    family_name_enc = %s,
                    family_name_search_idx = CASE
                        WHEN %s::text IS NULL THEN family_name_search_idx
                        ELSE immoapp_hash_trigrams(%s::text)
                    END,
                    phone_enc = %s,
                    remarks_enc = %s,
                    phone_search_idx = CASE
                        WHEN %s::text IS NULL THEN phone_search_idx
                        ELSE immoapp_hash_trigrams(%s::text)
                    END
                WHERE id = %s AND row_version = %s
                RETURNING id, row_version, agency_id
                """,
                (
                    d.get("family_name", ""),
                    d.get("phone", ""),
                    d.get("remarks", ""),
                    d.get("tags", ""),
                    d.get("is_vip", 0),
                    d.get("status", ""),
                    normalize_timestamp(d.get("updated_at")) or utc_now_iso(),
                    d.get("family_name_enc", ""),
                    d.get("family_name_search_src"),
                    d.get("family_name_search_src", ""),
                    d.get("phone_enc", ""),
                    d.get("remarks_enc", ""),  # Added remarks_enc
                    d.get("phone_search_src"),
                    d.get("phone_search_src", ""),
                    client_id,
                    row_version,
                ),
            ).fetchone()
        except Exception as exc:
            if _is_unique_violation(exc):
                raise ConflictError("A client with this phone already exists.") from exc
            raise
        if not updated:
            row = session.execute(
                "SELECT * FROM clients WHERE id = %s",
                (client_id,),
            ).fetchone()
            if row:
                current_version = as_int(row.get("row_version"), default=0)
                current_record = dict(Client.from_row(row).to_dict())
                raise ConflictError(
                    "Client was updated by another user. Please refresh and try again.",
                    current_version=current_version or None,
                    current_record=current_record,
                )
            raise NotFoundError("Client not found")
        updated_agency_id = as_int(updated.get("agency_id"), default=0)
        if updated_agency_id > 0:
            bump_generation(
                session,
                surface=CLIENTS_SURFACE,
                scope_key=agency_scope_key(updated_agency_id),
                agency_id=updated_agency_id,
            )
    else:
        agency_id = _resolve_agency_id(d)
        try:
            session.execute(
                """
                INSERT INTO clients
                (agency_id, family_name, phone, remarks, tags, is_vip, status,
                 created_at, created_loc, updated_at,
                 family_name_enc, family_name_search_idx, phone_enc, remarks_enc, phone_search_idx)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,immoapp_hash_trigrams(%s),%s,%s,immoapp_hash_trigrams(%s))
                RETURNING id
                """,
                (
                    agency_id,
                    d.get("family_name", ""),
                    d.get("phone", ""),
                    d.get("remarks", ""),
                    d.get("tags", ""),
                    d.get("is_vip", 0),
                    d.get("status") or "active",
                    normalize_timestamp(d.get("created_at")) or utc_now_iso(),
                    d.get("created_loc", ""),
                    normalize_timestamp(d.get("updated_at")) or utc_now_iso(),
                    d.get("family_name_enc", ""),
                    d.get("family_name_search_src", ""),
                    d.get("phone_enc", ""),
                    d.get("remarks_enc", ""),
                    d.get("phone_search_src", ""),
                ),
            )
        except Exception as exc:
            if _is_unique_violation(exc):
                raise ConflictError("A client with this phone already exists.") from exc
            raise
        client_id_res = session.lastrowid
        bump_generation(
            session,
            surface=CLIENTS_SURFACE,
            scope_key=agency_scope_key(agency_id),
            agency_id=agency_id,
        )
        return int(client_id_res or 0)

    return int(client_id or 0)


def insert_clients_batch(session: DbSession, rows: Sequence[ClientInput]) -> list[int]:
    """Insert a batch of clients using a single high-performance multi-row INSERT.

    RLS applies to the entire set. Returns one new ID per input row in input order.
    """
    if not rows:
        return []

    value_placeholders = []
    all_params = []

    for d in rows:
        value_placeholders.append(
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,immoapp_hash_trigrams(%s),%s,%s,immoapp_hash_trigrams(%s))"
        )
        all_params.extend(
            [
                _resolve_agency_id(d),
                d.get("family_name", ""),
                d.get("phone", ""),
                d.get("remarks", ""),
                d.get("tags", ""),
                d.get("is_vip", 0),
                d.get("status") or "active",
                normalize_timestamp(d.get("created_at")) or utc_now_iso(),
                d.get("created_loc", ""),
                normalize_timestamp(d.get("updated_at")) or utc_now_iso(),
                d.get("family_name_enc", ""),
                d.get("family_name_search_src", ""),
                d.get("phone_enc", ""),
                d.get("remarks_enc", ""),
                d.get("phone_search_src", ""),
            ]
        )

    sql = f"""
        INSERT INTO clients
        (agency_id, family_name, phone, remarks, tags, is_vip, status,
         created_at, created_loc, updated_at,
         family_name_enc, family_name_search_idx, phone_enc, remarks_enc, phone_search_idx)
        VALUES {', '.join(value_placeholders)}
        RETURNING id
    """

    try:
        result = session.execute(sql, all_params).fetchall()
    except Exception as exc:
        if _is_unique_violation(exc):
            raise ConflictError("A client with this phone already exists.") from exc
        raise
    agency_ids = _distinct_agency_ids(rows)
    if agency_ids:
        bump_generations(
            session,
            surface=CLIENTS_SURFACE,
            scopes=[(agency_scope_key(agency_id), agency_id) for agency_id in agency_ids],
        )
    return [int(str(row["id"])) for row in result]


def insert_clients_batch_refs(
    session: DbSession,
    rows: Sequence[ClientInput],
    *,
    source_ordinals: Sequence[int] | None = None,
) -> list[CreatedRowRef]:
    """Insert a batch of clients and return explicit source-to-created id refs."""
    if not rows:
        return []
    created_rows = _allocate_created_row_refs(
        session,
        table_name="clients",
        source_ordinals=_normalize_source_ordinals(
            source_ordinals=source_ordinals,
            expected_count=len(rows),
            context="client batch insert",
        ),
        context="client batch insert",
    )

    # Prepare values for a single multi-row insert (The Set-Based style)
    value_placeholders = []
    all_params = []

    for created_row, d in zip(created_rows, rows, strict=True):
        value_placeholders.append(
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,immoapp_hash_trigrams(%s),%s,%s,immoapp_hash_trigrams(%s))"
        )
        all_params.extend(
            [
                int(created_row.created_id),
                _resolve_agency_id(d),
                d.get("family_name", ""),
                d.get("phone", ""),
                d.get("remarks", ""),
                d.get("tags", ""),
                d.get("is_vip", 0),
                d.get("status") or "active",
                normalize_timestamp(d.get("created_at")) or utc_now_iso(),
                d.get("created_loc", ""),
                normalize_timestamp(d.get("updated_at")) or utc_now_iso(),
                d.get("family_name_enc", ""),
                d.get("family_name_search_src", ""),
                d.get("phone_enc", ""),
                d.get("remarks_enc", ""),
                d.get("phone_search_src", ""),
            ]
        )

    sql = f"""
        INSERT INTO clients
        (id, agency_id, family_name, phone, remarks, tags, is_vip, status,
         created_at, created_loc, updated_at,
         family_name_enc, family_name_search_idx, phone_enc, remarks_enc, phone_search_idx)
        VALUES {', '.join(value_placeholders)}
        RETURNING id
    """

    try:
        result = session.execute(sql, all_params).fetchall()
    except Exception as exc:
        if _is_unique_violation(exc):
            raise ConflictError("A client with this phone already exists.") from exc
        raise
    agency_ids = _distinct_agency_ids(rows)
    if agency_ids:
        bump_generations(
            session,
            surface=CLIENTS_SURFACE,
            scopes=[(agency_scope_key(agency_id), agency_id) for agency_id in agency_ids],
        )
    _require_inserted_ids_match_allocated(
        returned_rows=result,
        created_rows=created_rows,
        context="client batch insert",
    )
    return created_rows


def delete_client(session: DbSession, client_id: int) -> None:
    """Soft-delete a client and dependent records."""
    now = utc_now_iso()
    deleted = session.execute(
        "UPDATE clients SET deleted_at = %s, updated_at = %s, row_version = row_version + 1 "
        "WHERE id = %s "
        "RETURNING agency_id",
        (now, now, client_id),
    ).fetchone()
    session.execute(
        "UPDATE demandes SET deleted_at = %s, updated_at = %s, row_version = row_version + 1 "
        "WHERE client_id = %s",
        (now, now, client_id),
    )
    session.execute(
        "UPDATE visits SET deleted_at = %s, updated_at = %s, row_version = row_version + 1 "
        "WHERE client_id = %s",
        (now, now, client_id),
    )
    session.execute(
        "UPDATE contracts SET deleted_at = %s, updated_at = %s, row_version = row_version + 1 "
        "WHERE client_id = %s",
        (now, now, client_id),
    )
    deleted_agency_id = as_int((deleted or {}).get("agency_id"), default=0)
    if deleted_agency_id > 0:
        bump_generation(
            session,
            surface=CLIENTS_SURFACE,
            scope_key=agency_scope_key(deleted_agency_id),
            agency_id=deleted_agency_id,
        )


def restore_client(session: DbSession, client_id: int) -> None:
    """Restore a soft-deleted client and dependent records."""
    now = utc_now_iso()
    restored = session.execute(
        "UPDATE clients SET deleted_at = NULL, updated_at = %s, row_version = row_version + 1 "
        "WHERE id = %s "
        "RETURNING agency_id",
        (now, client_id),
    ).fetchone()
    session.execute(
        "UPDATE demandes SET deleted_at = NULL, updated_at = %s, row_version = row_version + 1 "
        "WHERE client_id = %s",
        (now, client_id),
    )
    session.execute(
        "UPDATE visits SET deleted_at = NULL, updated_at = %s, row_version = row_version + 1 "
        "WHERE client_id = %s",
        (now, client_id),
    )
    session.execute(
        "UPDATE contracts SET deleted_at = NULL, updated_at = %s, row_version = row_version + 1 "
        "WHERE client_id = %s",
        (now, client_id),
    )
    restored_agency_id = as_int((restored or {}).get("agency_id"), default=0)
    if restored_agency_id > 0:
        bump_generation(
            session,
            surface=CLIENTS_SURFACE,
            scope_key=agency_scope_key(restored_agency_id),
            agency_id=restored_agency_id,
        )


def purge_client(session: DbSession, client_id: int) -> None:
    """Permanently delete a client and dependent records."""
    session.execute("DELETE FROM demandes WHERE client_id = %s", (client_id,))
    session.execute("DELETE FROM visits WHERE client_id = %s", (client_id,))
    session.execute("DELETE FROM contracts WHERE client_id = %s", (client_id,))
    purged = session.execute(
        "DELETE FROM clients WHERE id = %s RETURNING agency_id",
        (client_id,),
    ).fetchone()
    purged_agency_id = as_int((purged or {}).get("agency_id"), default=0)
    if purged_agency_id > 0:
        bump_generation(
            session,
            surface=CLIENTS_SURFACE,
            scope_key=agency_scope_key(purged_agency_id),
            agency_id=purged_agency_id,
        )
