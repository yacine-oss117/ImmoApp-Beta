"""
Listing Service - Manages listings via Unit of Work.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

from app.models import Listing
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

__all__ = [
    "fetch_listings",
    "get_total_listing_count",
    "get_listing_by_id",
    "upsert_listing",
    "delete_listing",
    "find_listing_ids_by_phone",
    "fetch_deleted_listings",
    "restore_listing",
    "purge_listing",
    "reset_listing_cursor_anchors",
]

_LISTING_CURSOR_ANCHORS_LOCK = threading.Lock()
_LISTING_CURSOR_ANCHORS: dict[tuple[int, str, str | None, bool], dict[int, int | None]] = {}


def _listing_cursor_key(
    *,
    limit: int,
    search: str,
    status: str | None,
    include_deleted: bool,
) -> tuple[int, str, str | None, bool]:
    return (
        int(limit),
        str(search or ""),
        status if status is not None else None,
        bool(include_deleted),
    )


def _reset_listing_cursor_anchors() -> None:
    with _LISTING_CURSOR_ANCHORS_LOCK:
        _LISTING_CURSOR_ANCHORS.clear()


def reset_listing_cursor_anchors() -> None:
    _reset_listing_cursor_anchors()


def _fetch_listings_cursor_page(
    *,
    limit: int,
    cursor: int | None,
    search: str,
    status: str | None,
    include_deleted: bool,
) -> tuple[list[Listing], int | None]:
    params: ParamsDict = {
        "limit": limit,
        "search": search,
        "status": status,
        "include_deleted": int(include_deleted),
    }
    if isinstance(cursor, int) and cursor > 0:
        params["cursor"] = cursor
    response = api_get("/listings", params=params)
    payload = as_dict(response)
    items_raw = payload.get("items")
    items = (
        [Listing.from_row(item) for item in items_raw if isinstance(item, dict)]
        if isinstance(items_raw, list)
        else []
    )
    next_cursor = as_int(payload.get("next_cursor"), default=0)
    return items, (next_cursor if next_cursor > 0 else None)


def upsert_listing(listing_data: Mapping[str, object]) -> int:
    """Insert or update a listing using UoW. Returns the listing ID."""
    processed_data = dict(listing_data)

    payload = dict(processed_data)
    listing_id = payload.get("id")
    if isinstance(listing_id, int) and listing_id > 0:
        try:
            result = update_entity(
                "listing",
                listing_id,
                f"/listings/{listing_id}",
                payload,
                dedupe_key=f"PUT:/listings/{listing_id}",
                label="listing.update",
            )
        except ApiError as exc:
            if exc.status_code == 409:
                raise ValueError(
                    "Listing changed since you opened it. Refresh and try again."
                ) from exc
            if exc.status_code == 404:
                raise ValueError("Listing not found.") from exc
            raise ValueError(exc.message) from exc
        if result.queued:
            _reset_listing_cursor_anchors()
            return listing_id
        response = result.payload
    elif isinstance(listing_id, int) and listing_id < 0:
        try:
            update_entity(
                "listing",
                listing_id,
                f"/listings/{listing_id}",
                payload,
                dedupe_key=f"PUT:/listings/{listing_id}",
                label="listing.update",
            )
        except ApiError as exc:
            raise ValueError(exc.message) from exc
        _reset_listing_cursor_anchors()
        return listing_id
    else:
        try:
            created_id = create_entity(
                OfflineCreateRequest(
                    entity_type="listing",
                    path="/listings",
                    request_body=payload,
                    projection_data=payload,
                    label="listing.create",
                )
            )
        except ApiError as exc:
            raise ValueError(exc.message) from exc
        _reset_listing_cursor_anchors()
        return int(created_id)
    _reset_listing_cursor_anchors()
    parsed = as_dict(response)
    fallback_id = listing_id if isinstance(listing_id, int) else 0
    return as_int(parsed.get("id"), default=fallback_id)


def delete_listing(listing_id: int) -> None:
    """Soft-delete a listing using UoW."""
    delete_entity(
        "listing",
        listing_id,
        f"/listings/{listing_id}",
        dedupe_key=f"DELETE:/listings/{listing_id}",
        label="listing.delete",
    )
    _reset_listing_cursor_anchors()


def restore_listing(listing_id: int) -> None:
    """Restore a soft-deleted listing using UoW."""
    api_post_resilient(
        f"/listings/{listing_id}/restore",
        dedupe_key=f"POST:/listings/{listing_id}/restore",
        label="listing.restore",
    )
    _reset_listing_cursor_anchors()


def purge_listing(listing_id: int) -> None:
    """Permanently delete a listing using UoW."""
    api_delete_resilient(
        f"/listings/{listing_id}/purge",
        params={"confirm": f"PURGE_LISTING_{listing_id}"},
        dedupe_key=f"DELETE:/listings/{listing_id}/purge",
        label="listing.purge",
    )
    _reset_listing_cursor_anchors()


def fetch_listings(
    limit: int | None = None,
    offset: int = 0,
    search: str = "",
    status: str | None = "available",
    include_deleted: bool = False,
) -> list[Listing]:
    """Fetch listings using UoW."""
    if limit is not None and limit > 0 and offset >= 0:
        cursor_key = _listing_cursor_key(
            limit=limit,
            search=search,
            status=status,
            include_deleted=include_deleted,
        )
        with _LISTING_CURSOR_ANCHORS_LOCK:
            anchors = _LISTING_CURSOR_ANCHORS.setdefault(cursor_key, {0: None})
            known_offsets = [value for value in anchors.keys() if value <= offset]
            anchor_offset = max(known_offsets) if known_offsets else 0
            cursor = anchors.get(anchor_offset)

        current_offset = int(anchor_offset)
        while current_offset < offset:
            step = min(limit, offset - current_offset)
            page, next_cursor = _fetch_listings_cursor_page(
                limit=step,
                cursor=cursor,
                search=search,
                status=status,
                include_deleted=include_deleted,
            )
            current_offset += len(page)
            with _LISTING_CURSOR_ANCHORS_LOCK:
                anchors = _LISTING_CURSOR_ANCHORS.setdefault(cursor_key, {0: None})
                anchors[current_offset] = next_cursor
            if len(page) < step or next_cursor is None:
                return []
            cursor = next_cursor

        page, next_cursor = _fetch_listings_cursor_page(
            limit=limit,
            cursor=cursor,
            search=search,
            status=status,
            include_deleted=include_deleted,
        )
        with _LISTING_CURSOR_ANCHORS_LOCK:
            anchors = _LISTING_CURSOR_ANCHORS.setdefault(cursor_key, {0: None})
            anchors[offset + len(page)] = next_cursor
        return overlay_model_list("listing", page)

    response = api_get(
        "/listings",
        params={
            "limit": limit,
            "offset": offset,
            "search": search,
            "status": status,
            "include_deleted": int(include_deleted),
        },
    )
    payload = as_dict(response)
    items = payload.get("items")
    if isinstance(items, list):
        listings = [Listing.from_row(item) for item in items if isinstance(item, dict)]
        return overlay_model_list("listing", listings)
    return overlay_model_list("listing", [])


def get_total_listing_count(
    search: str = "",
    status: str | None = "available",
    include_deleted: bool = False,
) -> int:
    """Get total listing count using UoW."""
    response = api_get(
        "/listings/count",
        params={
            "search": search,
            "status": status,
            "include_deleted": int(include_deleted),
        },
    )
    payload = as_dict(response)
    return as_int(payload.get("total"), default=0)


def get_listing_by_id(listing_id: int, include_deleted: bool = False) -> Listing | None:
    """Fetch a single listing by ID using UoW."""
    try:
        response = api_get(
            f"/listings/{listing_id}",
            params={"include_deleted": int(include_deleted)},
        )
    except ApiError as exc:
        if exc.status_code == 404:
            return None
        raise
    payload = as_dict(response)
    listing = Listing.from_row(payload) if payload else None
    return overlay_model_detail("listing", listing_id, listing)


def find_listing_ids_by_phone(phone: str, exclude_id: int | None = None) -> list[int]:
    """Find listing IDs by phone using UoW."""
    response = api_get(
        "/listings/phone-duplicates",
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


def fetch_deleted_listings(
    limit: int | None = None,
    offset: int = 0,
    search: str = "",
) -> list[Listing]:
    """Fetch soft-deleted listings using UoW."""
    response = api_get(
        "/listings/deleted",
        params={"limit": limit, "offset": offset, "search": search},
    )
    payload = as_dict(response)
    items = payload.get("items")
    if isinstance(items, list):
        return [Listing.from_row(item) for item in items if isinstance(item, dict)]
    return []
