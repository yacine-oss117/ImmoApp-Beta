"""
Client Service - Manages clients via Unit of Work.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

from app.models import Client
from app.models_cast import as_int
from app.services.api_client import (
    ApiError,
    api_delete_resilient,
    api_get,
    api_post_resilient,
    as_dict,
)
from app.services.api_types import ParamsDict
from app.services.offline_entity_mutations import (
    OfflineCreateRequest,
    create_entity,
    delete_entity,
    update_entity,
)
from app.services.offline_projection import overlay_model_detail, overlay_model_list

_AUTH_SESSION_REQUIRED_MESSAGE = (
    "Your session or permissions changed while this page was open. " "Sign in again and try again."
)

__all__ = [
    "fetch_clients",
    "get_total_client_count",
    "get_client_by_id",
    "upsert_client",
    "delete_client",
    "find_client_ids_by_phone",
    "fetch_deleted_clients",
    "restore_client",
    "purge_client",
    "reset_client_cursor_anchors",
]

_CLIENT_CURSOR_ANCHORS_LOCK = threading.Lock()
_CLIENT_CURSOR_ANCHORS: dict[tuple[int, str, str | None, bool, str], dict[int, int | None]] = {}


def _client_cursor_key(
    *,
    limit: int,
    search: str,
    status: str | None,
    include_deleted: bool,
    fields: list[str] | None,
) -> tuple[int, str, str | None, bool, str]:
    return (
        int(limit),
        str(search or ""),
        status if status is not None else None,
        bool(include_deleted),
        ",".join(fields or []),
    )


def _reset_client_cursor_anchors() -> None:
    with _CLIENT_CURSOR_ANCHORS_LOCK:
        _CLIENT_CURSOR_ANCHORS.clear()


def reset_client_cursor_anchors() -> None:
    _reset_client_cursor_anchors()


def _raise_auth_session_required(exc: ApiError) -> None:
    if exc.status_code in (401, 403):
        raise PermissionError(_AUTH_SESSION_REQUIRED_MESSAGE) from exc


def _fetch_clients_cursor_page(
    *,
    limit: int,
    cursor: int | None,
    search: str,
    status: str | None,
    include_deleted: bool,
    fields: list[str] | None,
) -> tuple[list[Client], int | None]:
    params: ParamsDict = {
        "limit": limit,
        "search": search,
        "status": status,
        "include_deleted": int(include_deleted),
    }
    if isinstance(cursor, int) and cursor > 0:
        params["cursor"] = cursor
    if fields:
        params["fields"] = ",".join(fields)
    response = api_get("/clients", params=params)
    payload = as_dict(response)
    items_raw = payload.get("items")
    items = (
        [Client.from_row(item) for item in items_raw if isinstance(item, dict)]
        if isinstance(items_raw, list)
        else []
    )
    next_cursor = as_int(payload.get("next_cursor"), default=0)
    return items, (next_cursor if next_cursor > 0 else None)


def upsert_client(client_data: Mapping[str, object]) -> int:
    """Insert or update a client using UoW. Returns the client ID."""
    processed_data = dict(client_data)
    payload = dict(processed_data)
    client_id = payload.get("id")
    if isinstance(client_id, int) and client_id > 0:
        try:
            result = update_entity(
                "client",
                client_id,
                f"/clients/{client_id}",
                payload,
                dedupe_key=f"PUT:/clients/{client_id}",
                label="client.update",
            )
        except ApiError as exc:
            _raise_auth_session_required(exc)
            if exc.status_code == 409:
                raise ValueError(
                    "Client changed since you opened it. Refresh and try again."
                ) from exc
            if exc.status_code == 404:
                raise ValueError("Client not found.") from exc
            raise ValueError(exc.message) from exc
        if result.queued:
            _reset_client_cursor_anchors()
            return client_id
        response = result.payload
    elif isinstance(client_id, int) and client_id < 0:
        try:
            result = update_entity(
                "client",
                client_id,
                f"/clients/{client_id}",
                payload,
                dedupe_key=f"PUT:/clients/{client_id}",
                label="client.update",
            )
        except ApiError as exc:
            _raise_auth_session_required(exc)
            raise ValueError(exc.message) from exc
        _reset_client_cursor_anchors()
        return client_id if result.queued else client_id
    else:
        try:
            created_id = create_entity(
                OfflineCreateRequest(
                    entity_type="client",
                    path="/clients",
                    request_body=payload,
                    projection_data=payload,
                    label="client.create",
                )
            )
        except ApiError as exc:
            _raise_auth_session_required(exc)
            raise ValueError(exc.message) from exc
        _reset_client_cursor_anchors()
        return int(created_id)
    _reset_client_cursor_anchors()
    payload_out = as_dict(response)
    fallback_id = client_id if isinstance(client_id, int) else 0
    return as_int(payload_out.get("id"), default=fallback_id)


def delete_client(client_id: int) -> None:
    """Soft-delete a client and update match cache using UoW."""
    delete_entity(
        "client",
        client_id,
        f"/clients/{client_id}",
        dedupe_key=f"DELETE:/clients/{client_id}",
        label="client.delete",
    )
    _reset_client_cursor_anchors()


def restore_client(client_id: int) -> None:
    """Restore a soft-deleted client using UoW."""
    api_post_resilient(
        f"/clients/{client_id}/restore",
        dedupe_key=f"POST:/clients/{client_id}/restore",
        label="client.restore",
    )
    _reset_client_cursor_anchors()


def purge_client(client_id: int) -> None:
    """Permanently delete a client using UoW."""
    params: ParamsDict = {"confirm": f"PURGE_CLIENT_{client_id}"}
    api_delete_resilient(
        f"/clients/{client_id}/purge",
        params=params,
        dedupe_key=f"DELETE:/clients/{client_id}/purge",
        label="client.purge",
    )
    _reset_client_cursor_anchors()


def fetch_clients(
    limit: int | None = None,
    offset: int = 0,
    search: str = "",
    status: str | None = "active",
    include_deleted: bool = False,
    fields: list[str] | None = None,
) -> list[Client]:
    """Fetch clients using UoW."""
    if limit is not None and limit > 0 and offset >= 0:
        cursor_key = _client_cursor_key(
            limit=limit,
            search=search,
            status=status,
            include_deleted=include_deleted,
            fields=fields,
        )
        with _CLIENT_CURSOR_ANCHORS_LOCK:
            anchors = _CLIENT_CURSOR_ANCHORS.setdefault(cursor_key, {0: None})
            known_offsets = [value for value in anchors.keys() if value <= offset]
            anchor_offset = max(known_offsets) if known_offsets else 0
            cursor = anchors.get(anchor_offset)

        current_offset = int(anchor_offset)
        while current_offset < offset:
            step = min(limit, offset - current_offset)
            page, next_cursor = _fetch_clients_cursor_page(
                limit=step,
                cursor=cursor,
                search=search,
                status=status,
                include_deleted=include_deleted,
                fields=fields,
            )
            current_offset += len(page)
            with _CLIENT_CURSOR_ANCHORS_LOCK:
                anchors = _CLIENT_CURSOR_ANCHORS.setdefault(cursor_key, {0: None})
                anchors[current_offset] = next_cursor
            if len(page) < step or next_cursor is None:
                return []
            cursor = next_cursor

        page, next_cursor = _fetch_clients_cursor_page(
            limit=limit,
            cursor=cursor,
            search=search,
            status=status,
            include_deleted=include_deleted,
            fields=fields,
        )
        with _CLIENT_CURSOR_ANCHORS_LOCK:
            anchors = _CLIENT_CURSOR_ANCHORS.setdefault(cursor_key, {0: None})
            anchors[offset + len(page)] = next_cursor
        return overlay_model_list("client", page)

    params: ParamsDict = {
        "limit": limit,
        "offset": offset,
        "search": search,
        "status": status,
        "include_deleted": int(include_deleted),
    }
    if fields:
        params["fields"] = ",".join(fields)
    response = api_get(
        "/clients",
        params=params,
    )
    payload = as_dict(response)
    items = payload.get("items")
    if isinstance(items, list):
        clients = [Client.from_row(item) for item in items if isinstance(item, dict)]
        return overlay_model_list("client", clients)
    return overlay_model_list("client", [])


def get_total_client_count(
    search: str = "",
    status: str | None = "active",
    include_deleted: bool = False,
) -> int:
    """Get total client count using UoW."""
    response = api_get(
        "/clients/count",
        params={
            "search": search,
            "status": status,
            "include_deleted": int(include_deleted),
        },
    )
    payload = as_dict(response)
    return as_int(payload.get("total"), default=0)


def get_client_by_id(client_id: int, include_deleted: bool = False) -> Client | None:
    """Fetch a single client by ID using UoW."""
    try:
        params: ParamsDict = {"include_deleted": int(include_deleted)}
        response = api_get(
            f"/clients/{client_id}",
            params=params,
        )
    except ApiError as exc:
        if exc.status_code == 404:
            return None
        raise
    payload = as_dict(response)
    client = Client.from_row(payload) if payload else None
    return overlay_model_detail("client", client_id, client)


def find_client_ids_by_phone(phone: str, exclude_id: int | None = None) -> list[int]:
    """Find client IDs by phone using UoW."""
    response = api_get(
        "/clients/phone-duplicates",
        params={"phone": phone, "exclude_id": exclude_id},
    )
    payload = as_dict(response)
    ids = payload.get("ids")
    if not isinstance(ids, list):
        return []
    result: list[int] = []
    for value in ids:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


def fetch_deleted_clients(
    limit: int | None = None,
    offset: int = 0,
    search: str = "",
) -> list[Client]:
    """Fetch soft-deleted clients using UoW."""
    response = api_get(
        "/clients/deleted",
        params={"limit": limit, "offset": offset, "search": search},
    )
    payload = as_dict(response)
    items = payload.get("items")
    if isinstance(items, list):
        return [Client.from_row(item) for item in items if isinstance(item, dict)]
    return []
