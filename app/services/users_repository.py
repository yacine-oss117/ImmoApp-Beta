"""User management API client helpers."""

from __future__ import annotations

from typing import cast

from app.services.api_client import (
    api_delete_resilient,
    api_get,
    api_post,
    api_post_resilient,
    api_put_resilient,
    as_dict,
)
from app.services.api_types import ParamsDict


def list_users(
    *, include_inactive: bool = False, role: str | None = None
) -> list[dict[str, object]]:
    params: ParamsDict = {"limit": "200"}
    if include_inactive:
        params["include_inactive"] = "1"
    if role:
        params["role"] = role
    items: list[dict[str, object]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        if cursor:
            if cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
            params["cursor"] = cursor
        else:
            params.pop("cursor", None)
        payload = as_dict(api_get("/users", params=params))
        page_items = payload.get("items")
        if isinstance(page_items, list):
            items.extend(cast(list[dict[str, object]], page_items))
        next_cursor = payload.get("next_cursor")
        has_more = bool(payload.get("has_more"))
        cursor = str(next_cursor) if isinstance(next_cursor, str) and next_cursor.strip() else None
        if not has_more or not cursor:
            break
    return items


def get_user(user_id: int) -> dict[str, object]:
    payload = as_dict(api_get(f"/users/{user_id}"))
    return cast(dict[str, object], payload)


def create_user(payload: dict[str, object]) -> dict[str, object]:
    response = as_dict(api_post("/users", payload))
    return cast(dict[str, object], response)


def update_user(user_id: int, payload: dict[str, object]) -> dict[str, object]:
    result = api_put_resilient(
        f"/users/{user_id}",
        payload,
        dedupe_key=f"PUT:/users/{user_id}",
        label="user.update",
    )
    if result.queued:
        optimistic = dict(payload)
        optimistic["id"] = user_id
        optimistic["queued"] = True
        return optimistic
    response = as_dict(result.payload)
    return cast(dict[str, object], response)


def deactivate_user(user_id: int) -> None:
    api_delete_resilient(
        f"/users/{user_id}",
        dedupe_key=f"DELETE:/users/{user_id}",
        label="user.deactivate",
    )


def list_user_invites() -> list[dict[str, object]]:
    params: ParamsDict = {"limit": "200"}
    items: list[dict[str, object]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        if cursor:
            if cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
            params["cursor"] = cursor
        else:
            params.pop("cursor", None)
        payload = as_dict(api_get("/users/invites", params=params))
        page_items = payload.get("items")
        if isinstance(page_items, list):
            items.extend(cast(list[dict[str, object]], page_items))
        next_cursor = payload.get("next_cursor")
        has_more = bool(payload.get("has_more"))
        cursor = str(next_cursor) if isinstance(next_cursor, str) and next_cursor.strip() else None
        if not has_more or not cursor:
            break
    return items


def create_user_invite(payload: dict[str, object]) -> dict[str, object]:
    response = as_dict(api_post("/users/invites", payload))
    return cast(dict[str, object], response)


def resend_user_invite(invite_id: str, *, expires_seconds: int | None = None) -> dict[str, object]:
    payload: dict[str, object] = {}
    if expires_seconds is not None:
        payload["expires_seconds"] = int(expires_seconds)
    result = api_post_resilient(
        f"/users/invites/{invite_id}/resend",
        payload,
        dedupe_key=f"POST:/users/invites/{invite_id}/resend",
        label="invite.resend",
    )
    if result.queued:
        return {"id": invite_id, "queued": True}
    response = as_dict(result.payload)
    return cast(dict[str, object], response)


def revoke_user_invite(invite_id: str) -> dict[str, object]:
    result = api_post_resilient(
        f"/users/invites/{invite_id}/revoke",
        {},
        dedupe_key=f"POST:/users/invites/{invite_id}/revoke",
        label="invite.revoke",
    )
    if result.queued:
        return {"id": invite_id, "queued": True}
    response = as_dict(result.payload)
    return cast(dict[str, object], response)
