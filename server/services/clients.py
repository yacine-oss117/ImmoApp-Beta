"""
Postgres-backed client operations with validation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from core.data import client_repo_read as read
from core.data import client_repo_write as write
from core.data.match_cache import mark_client_dirty
from core.data.types import ClientInput
from core.matcher.ports.db import DbSession
from core.models import Client
from core.models_cast import as_int
from server.pg.uow import get_uow

from .ale_policy import CLIENT_ALE_POLICIES
from .match_jobs import enqueue_rebuild_client_pairs


def _fetch_clients_page(
    session: DbSession,
    *,
    limit: int | None,
    offset: int,
    search: str,
    status: str | None,
    include_deleted: bool,
) -> list[Client]:
    if limit is None or limit <= 0 or offset < 0:
        return read.fetch_clients(session, limit, offset, search, status, include_deleted)
    cursor: int | None = None
    current_offset = 0
    while current_offset < offset:
        step = min(limit, offset - current_offset)
        page = read.fetch_clients_cursor(
            session,
            limit=step,
            cursor=cursor,
            search=search,
            status=status,
            include_deleted=include_deleted,
        )
        current_offset += len(page)
        if len(page) < step:
            return []
        last_id = getattr(page[-1], "id", 0) if page else 0
        cursor = int(last_id) if int(last_id) > 0 else None
        if cursor is None:
            return []
    return read.fetch_clients_cursor(
        session,
        limit=limit,
        cursor=cursor,
        search=search,
        status=status,
        include_deleted=include_deleted,
    )


def _enqueue_client_pairs_callback(
    *,
    client_id: int,
    include_deleted: bool,
) -> Callable[[], None]:
    def _callback() -> None:
        enqueue_rebuild_client_pairs(client_id, include_deleted=include_deleted)

    return _callback


def _infer_client_total(*, limit: int | None, offset: int, item_count: int) -> int | None:
    if limit is None or limit <= 0:
        return None
    if item_count < limit:
        return max(0, int(offset)) + int(item_count)
    return None


def fetch_clients(
    *,
    limit: int | None = None,
    offset: int = 0,
    search: str = "",
    status: str | None = "active",
    include_deleted: bool = False,
) -> list[Client]:
    """Fetch clients with optional filtering."""
    with get_uow().session() as session:
        return _fetch_clients_page(
            session,
            limit=limit,
            offset=offset,
            search=search,
            status=status,
            include_deleted=include_deleted,
        )


def fetch_clients_with_count(
    *,
    limit: int | None = None,
    offset: int = 0,
    search: str = "",
    status: str | None = "active",
    include_deleted: bool = False,
) -> tuple[list[Client], int]:
    """Fetch paginated clients and total count using a single DB session."""
    with get_uow().session() as session:
        items = _fetch_clients_page(
            session,
            limit=limit,
            offset=offset,
            search=search,
            status=status,
            include_deleted=include_deleted,
        )
        inferred_total = _infer_client_total(limit=limit, offset=offset, item_count=len(items))
        total = (
            inferred_total
            if inferred_total is not None
            else read.get_total_client_count(session, search, status, include_deleted)
        )
    return items, total


def fetch_clients_cursor(
    *,
    limit: int = 100,
    cursor: int | None = None,
    search: str = "",
    status: str | None = "active",
    include_deleted: bool = False,
) -> list[Client]:
    """Fetch clients using cursor pagination (id > cursor)."""
    with get_uow().session() as session:
        return read.fetch_clients_cursor(
            session,
            limit=limit,
            cursor=cursor,
            search=search,
            status=status,
            include_deleted=include_deleted,
        )


def get_total_client_count(
    *,
    search: str = "",
    status: str | None = "active",
    include_deleted: bool = False,
) -> int:
    """Get total client count for pagination."""
    with get_uow().session() as session:
        return int(read.get_total_client_count(session, search, status, include_deleted))


def get_clients_surface_generation(*, agency_id: int) -> int:
    """Return the durable generation for client list/count response caches."""
    with get_uow().session() as session:
        return int(read.get_clients_surface_generation(session, agency_id=int(agency_id)))


def get_total_deleted_client_count(
    *,
    search: str = "",
) -> int:
    """Get total deleted client count for pagination."""
    with get_uow().session() as session:
        return read.get_total_deleted_client_count(session, search)


def get_client_by_id(
    client_id: int,
    *,
    include_deleted: bool = False,
) -> Client | None:
    """Get a single client by ID."""
    with get_uow().session() as session:
        return read.get_client_by_id(session, client_id, include_deleted)


def find_client_ids_by_phone(phone: str, exclude_id: int | None = None) -> list[int]:
    """Return active client IDs matching a phone number within the current scope."""
    with get_uow().session() as session:
        return read.find_client_ids_by_phone(session, phone, exclude_id)


def fetch_deleted_clients(
    *,
    limit: int | None = None,
    offset: int = 0,
    search: str = "",
) -> list[Client]:
    """Fetch soft-deleted clients for trash management."""
    with get_uow().session() as session:
        return read.fetch_deleted_clients(session, limit, offset, search)


def delete_client(client_id: int, *, actor: str | None = None) -> None:
    """Soft-delete a client."""
    with get_uow().transaction(actor=actor) as session:
        write.delete_client(session, client_id)
        mark_client_dirty(session, client_id)
        session.on_commit(
            _enqueue_client_pairs_callback(
                client_id=int(client_id),
                include_deleted=False,
            )
        )


def restore_client(client_id: int, *, actor: str | None = None) -> None:
    """Restore a soft-deleted client."""
    with get_uow().transaction(actor=actor) as session:
        write.restore_client(session, client_id)
        mark_client_dirty(session, client_id)
        session.on_commit(
            _enqueue_client_pairs_callback(
                client_id=int(client_id),
                include_deleted=False,
            )
        )


def purge_client(client_id: int, *, actor: str | None = None) -> None:
    """Permanently delete a client."""
    with get_uow().transaction(actor=actor) as session:
        write.purge_client(session, client_id)
        mark_client_dirty(session, client_id)
        session.on_commit(
            _enqueue_client_pairs_callback(
                client_id=int(client_id),
                include_deleted=True,
            )
        )


def upsert_client(
    client_data: Mapping[str, object],
    *,
    actor: str | None = None,
) -> int:
    """Insert or update a client."""
    client_id = as_int(client_data.get("id"))
    should_rebuild_pairs = False
    with get_uow().transaction(actor=actor) as session:
        existing = None
        if client_id:
            existing = read.get_client_by_id_for_update(session, client_id)
        processed = normalize_client_data(client_data, existing=existing)
        if existing is not None:
            previous_status = str(existing.status or "")
            next_status = str(processed.get("status") or "")
            should_rebuild_pairs = previous_status != next_status
        client_id = write.upsert_client(session, processed)
        if client_id:
            mark_client_dirty(session, client_id)
        if should_rebuild_pairs and client_id:
            session.on_commit(
                _enqueue_client_pairs_callback(
                    client_id=int(client_id),
                    include_deleted=False,
                )
            )
    return int(client_id or 0)


def normalize_client_data(
    client_data: Mapping[str, object], existing: Client | None = None
) -> ClientInput:
    from .ale_helper import normalize_ale_fields

    workspace: dict[str, Any] = dict(existing.to_dict()) if existing else {}
    workspace.update(client_data)

    normalize_ale_fields(
        workspace,
        CLIENT_ALE_POLICIES,
        changed_fields=set(client_data.keys()),
    )

    processed: ClientInput = {
        "family_name": str(workspace.get("family_name", "")),
        "phone": str(workspace.get("phone", "")),
        "remarks": str(workspace.get("remarks", "")),
        "tags": str(workspace.get("tags", "")),
        "is_vip": 1 if workspace.get("is_vip") else 0,
        "status": str(workspace.get("status", "active")),
        "created_at": (
            str(workspace["created_at"]) if workspace.get("created_at") is not None else None
        ),
        "created_loc": str(workspace.get("created_loc", "")),
        "updated_at": (
            str(workspace["updated_at"]) if workspace.get("updated_at") is not None else None
        ),
        "family_name_enc": str(workspace.get("family_name_enc", "")),
        "family_name_search_src": (
            str(workspace["family_name_search_src"])
            if workspace.get("family_name_search_src") is not None
            else None
        ),
        "phone_enc": str(workspace.get("phone_enc", "")),
        "phone_search_src": (
            str(workspace["phone_search_src"])
            if workspace.get("phone_search_src") is not None
            else None
        ),
        "remarks_enc": str(workspace.get("remarks_enc", "")),
    }
    client_id = as_int(workspace.get("id"), default=0)
    if client_id > 0:
        processed["id"] = client_id
    row_version = as_int(workspace.get("row_version"), default=0)
    if row_version > 0:
        processed["row_version"] = row_version
    agency_id = as_int(workspace.get("agency_id"), default=0)
    if agency_id > 0:
        processed["agency_id"] = agency_id
    return processed
