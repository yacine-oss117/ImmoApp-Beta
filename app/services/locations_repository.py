"""
Locations Service - Manages custom locations via Unit of Work.
"""

from __future__ import annotations

from app.services.api_client import (
    ApiError,
    api_delete_resilient,
    api_get,
    api_post,
    api_put_resilient,
    as_dict,
)
from app.services.api_config import get_api_base_url
from app.services.offline_account_scope import OfflineAccountScope, get_active_account_scope

__all__ = [
    "add_location",
    "get_all_locations",
    "peek_cached_locations",
    "delete_location",
    "update_location",
    "refresh_locations_cache",
]

_cached_locations: dict[str, list[str]] = {}


def _cache_key(scope: OfflineAccountScope | None = None) -> str:
    resolved = scope or get_active_account_scope()
    if resolved is not None:
        return resolved.account_key
    return str(get_api_base_url() or "default")


def _cache(scope: OfflineAccountScope | None = None) -> list[str]:
    return _cached_locations.setdefault(_cache_key(scope), [])


def get_all_locations() -> list[str]:
    """Get all available locations using UoW."""
    cached = _cache()
    try:
        payload = as_dict(api_get("/locations"))
    except Exception:
        if cached:
            return list(cached)
        raise
    items = payload.get("items")
    if not isinstance(items, list):
        return list(cached)
    normalized = [str(item) for item in items]
    _cached_locations[_cache_key()] = normalized
    return normalized


def peek_cached_locations() -> list[str]:
    """Return the current cached locations without network access."""
    return list(_cache())


def add_location(name: str) -> bool:
    """Add a new location using UoW."""
    try:
        payload = as_dict(api_post("/locations", {"name": name}))
    except ApiError as exc:
        raise ValueError(exc.message) from exc
    created = bool(payload.get("created"))
    cached = _cache()
    if created and name not in cached:
        cached.append(name)
        cached.sort()
    return created


def delete_location(name: str) -> bool:
    """Delete a custom location using UoW."""
    cached = _cache()
    try:
        result = api_delete_resilient(
            "/locations",
            params={"name": name},
            dedupe_key=f"DELETE:/locations:{name}",
            label="location.delete",
        )
    except ApiError as exc:
        raise ValueError(exc.message) from exc
    if result.queued:
        try:
            cached.remove(name)
        except ValueError:
            pass
        return True
    payload = as_dict(result.payload)
    deleted = bool(payload.get("deleted"))
    if deleted:
        try:
            cached.remove(name)
        except ValueError:
            pass
    return deleted


def update_location(old_name: str, new_name: str) -> bool:
    """Rename an existing location using UoW."""
    cached = _cache()
    try:
        result = api_put_resilient(
            "/locations",
            {"old_name": old_name, "new_name": new_name},
            dedupe_key=f"PUT:/locations:{old_name}",
            label="location.rename",
        )
    except ApiError as exc:
        raise ValueError(exc.message) from exc
    if result.queued:
        try:
            idx = cached.index(old_name)
            cached[idx] = new_name
            cached.sort()
        except ValueError:
            pass
        return True
    payload = as_dict(result.payload)
    updated = bool(payload.get("updated"))
    if updated:
        try:
            idx = cached.index(old_name)
            cached[idx] = new_name
            cached.sort()
        except ValueError:
            pass
    return updated


def refresh_locations_cache() -> None:
    """Refresh the in-memory locations cache using UoW."""
    get_all_locations()
