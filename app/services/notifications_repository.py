"""Client-side notification API wrapper."""

from __future__ import annotations

from app.models_cast import as_int
from app.services.api_client import api_get, api_post, as_dict, as_dict_list
from app.services.api_types import ParamsDict


def fetch_notifications(
    *, limit: int = 200, offset: int = 0
) -> tuple[list[dict[str, object]], int]:
    """Fetch notifications visible to the current user."""
    payload = as_dict(api_get("/notifications", params={"limit": limit, "offset": offset}))
    items = as_dict_list(payload.get("items"))
    total = as_int(payload.get("total"), default=len(items))
    return items, total


def fetch_notifications_page(
    *,
    limit: int = 200,
    cursor: int | None = None,
) -> tuple[list[dict[str, object]], int, int | None]:
    """Fetch one keyset page of notifications."""
    params: ParamsDict = {"limit": limit}
    if isinstance(cursor, int) and cursor > 0:
        params["cursor"] = cursor
    payload = as_dict(api_get("/notifications", params=params))
    items = as_dict_list(payload.get("items"))
    total = as_int(payload.get("total"), default=len(items))
    next_cursor = as_int(payload.get("next_cursor"), default=0)
    return items, total, (next_cursor if next_cursor > 0 else None)


def clear_notifications() -> int:
    """Clear all notifications the user is allowed to delete."""
    payload = as_dict(api_post("/notifications/clear", {}))
    return as_int(payload.get("deleted"), default=0)


def mark_notifications_read(ids: list[int] | None = None, *, mark_all: bool = False) -> int:
    """Mark notifications as read."""
    payload = {"ids": ids or [], "all": mark_all}
    response = as_dict(api_post("/notifications/mark-read", payload))
    return as_int(response.get("updated"), default=0)


def mark_notifications_unread(ids: list[int] | None = None, *, mark_all: bool = False) -> int:
    """Mark notifications as unread."""
    payload = {"ids": ids or [], "all": mark_all}
    response = as_dict(api_post("/notifications/mark-unread", payload))
    return as_int(response.get("updated"), default=0)


def fetch_unread_count() -> int:
    """Fetch the unread notification count."""
    payload = as_dict(api_get("/notifications/unread-count", params=None))
    return as_int(payload.get("unread"), default=0)


__all__ = [
    "clear_notifications",
    "fetch_notifications",
    "fetch_notifications_page",
    "fetch_unread_count",
    "mark_notifications_read",
    "mark_notifications_unread",
]
