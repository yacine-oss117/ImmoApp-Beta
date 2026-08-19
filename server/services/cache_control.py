"""Shared response-cache namespace helpers for migrated hot-read caches."""

from __future__ import annotations

from enum import StrEnum


class CacheNamespace(StrEnum):
    CLIENTS_LIST = "clients_list"
    CLIENTS_COUNT = "clients_count"
    LISTINGS_LIST = "listings_list"
    LISTINGS_COUNT = "listings_count"
    USERS_LIST = "users_list"
    INVITES_LIST = "invites_list"
    NOTIFICATIONS_LIST = "notifications_list"
    NOTIFICATIONS_COUNT = "notifications_count"


def namespace_key(
    namespace: CacheNamespace,
    *,
    agency_id: int | None,
    actor_id: int | None,
) -> str:
    if agency_id is not None:
        tenant_key = f"agency:{int(agency_id)}"
    elif actor_id is not None:
        tenant_key = f"actor:{int(actor_id)}"
    else:
        tenant_key = "global"
    return f"immoapp:response_cache:{namespace.value}:{tenant_key}"


__all__ = [
    "CacheNamespace",
    "namespace_key",
]
