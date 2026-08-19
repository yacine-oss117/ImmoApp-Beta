"""Named cache policies for hot read endpoints."""

from __future__ import annotations

import os
from typing import Literal, TypedDict


class CachePolicy(TypedDict):
    ttl_seconds: int
    stale_while_revalidate_seconds: int
    cache_layer: Literal["l1_l2", "l2_only", "off"]
    admit_after_hits: int
    max_entry_bytes: int
    cache_deep_offsets: bool
    cache_search_queries: bool


def _env_int(name: str, default: int, *, min_v: int, max_v: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_v, min(max_v, value))


def _env_ttl(default: int, *names: str) -> int:
    values: list[int] = []
    for name in names:
        raw = (os.environ.get(name) or "").strip()
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        values.append(max(1, min(int(value), 3600)))
    if values:
        return max(values)
    return max(1, min(int(default), 3600))


def _policy(
    *,
    ttl_seconds: int,
    cache_layer: Literal["l1_l2", "l2_only", "off"] = "l1_l2",
    cache_search_queries: bool = True,
) -> CachePolicy:
    return {
        "ttl_seconds": ttl_seconds,
        "stale_while_revalidate_seconds": 0,
        "cache_layer": cache_layer,
        "admit_after_hits": _env_int("IMMOAPP_CACHE_ADMIT_AFTER_HITS", 2, min_v=1, max_v=16),
        "max_entry_bytes": _env_int(
            "IMMOAPP_CACHE_L1_MAX_ENTRY_BYTES",
            262144,
            min_v=4096,
            max_v=4 * 1024 * 1024,
        ),
        "cache_deep_offsets": False,
        "cache_search_queries": cache_search_queries,
    }


CLIENTS_LIST_POLICY: CachePolicy = _policy(
    cache_layer="l2_only",
    ttl_seconds=_env_ttl(
        120,
        "IMMOAPP_CLIENTS_LIST_HTTP_CACHE_TTL_SECONDS",
        "IMMOAPP_CLIENT_LIST_CACHE_TTL_SECONDS",
    ),
)
CLIENTS_COUNT_POLICY: CachePolicy = _policy(
    ttl_seconds=_env_ttl(120, "IMMOAPP_CLIENT_COUNT_CACHE_TTL_SECONDS")
)
LISTINGS_LIST_POLICY: CachePolicy = _policy(
    cache_layer="l2_only",
    ttl_seconds=_env_ttl(
        120,
        "IMMOAPP_LISTINGS_LIST_HTTP_CACHE_TTL_SECONDS",
        "IMMOAPP_LISTING_LIST_CACHE_TTL_SECONDS",
    ),
)
LISTINGS_COUNT_POLICY: CachePolicy = _policy(
    ttl_seconds=_env_ttl(120, "IMMOAPP_LISTING_COUNT_CACHE_TTL_SECONDS")
)
USERS_LIST_POLICY: CachePolicy = _policy(
    ttl_seconds=_env_ttl(180, "IMMOAPP_USERS_LIST_HTTP_CACHE_TTL_SECONDS")
)
INVITES_LIST_POLICY: CachePolicy = _policy(
    ttl_seconds=_env_ttl(180, "IMMOAPP_INVITES_LIST_HTTP_CACHE_TTL_SECONDS")
)
NOTIFICATIONS_LIST_POLICY: CachePolicy = _policy(
    ttl_seconds=_env_ttl(
        60,
        "IMMOAPP_NOTIFICATIONS_LIST_HTTP_CACHE_TTL_SECONDS",
        "IMMOAPP_NOTIFICATION_LIST_CACHE_TTL_SECONDS",
    )
)
NOTIFICATIONS_COUNT_POLICY: CachePolicy = _policy(
    ttl_seconds=_env_ttl(60, "IMMOAPP_NOTIFICATION_COUNT_CACHE_TTL_SECONDS")
)


__all__ = [
    "CLIENTS_COUNT_POLICY",
    "CLIENTS_LIST_POLICY",
    "CachePolicy",
    "INVITES_LIST_POLICY",
    "LISTINGS_COUNT_POLICY",
    "LISTINGS_LIST_POLICY",
    "NOTIFICATIONS_COUNT_POLICY",
    "NOTIFICATIONS_LIST_POLICY",
    "USERS_LIST_POLICY",
]
