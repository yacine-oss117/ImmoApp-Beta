"""
Lookup Service - Manages reference data lookups via Unit of Work.
"""

from __future__ import annotations

import threading

from app.models_cast import as_int
from app.services.api_client import api_get, as_dict

__all__ = [
    "get_property_type_id",
    "get_property_type_name",
    "get_action_id",
    "get_action_name",
    "get_wilaya_id",
    "get_wilaya_name",
    "get_all_property_types",
    "get_all_actions",
    "get_all_wilayas",
]

_property_types_cache: list[tuple[int, str]] | None = None
_actions_cache: list[tuple[int, str]] | None = None
_wilayas_cache: list[tuple[int, str, str]] | None = None
_lookup_lock = threading.Lock()


def _get_property_types_cache() -> list[tuple[int, str]]:
    global _property_types_cache
    with _lookup_lock:
        if _property_types_cache is not None:
            return _property_types_cache
        payload = as_dict(api_get("/lookup/property-types"))
        items = payload.get("items")
        if not isinstance(items, list):
            _property_types_cache = []
            return _property_types_cache
        _property_types_cache = []
        for item in items:
            if not isinstance(item, dict):
                continue
            _property_types_cache.append(
                (as_int(item.get("id"), default=0), str(item.get("name") or ""))
            )
        return _property_types_cache


def _get_actions_cache() -> list[tuple[int, str]]:
    global _actions_cache
    with _lookup_lock:
        if _actions_cache is not None:
            return _actions_cache
        payload = as_dict(api_get("/lookup/actions"))
        items = payload.get("items")
        if not isinstance(items, list):
            _actions_cache = []
            return _actions_cache
        _actions_cache = []
        for item in items:
            if not isinstance(item, dict):
                continue
            _actions_cache.append((as_int(item.get("id"), default=0), str(item.get("name") or "")))
        return _actions_cache


def _get_wilayas_cache() -> list[tuple[int, str, str]]:
    global _wilayas_cache
    with _lookup_lock:
        if _wilayas_cache is not None:
            return _wilayas_cache
        payload = as_dict(api_get("/lookup/wilayas"))
        items = payload.get("items")
        if not isinstance(items, list):
            _wilayas_cache = []
            return _wilayas_cache
        _wilayas_cache = []
        for item in items:
            if not isinstance(item, dict):
                continue
            _wilayas_cache.append(
                (
                    as_int(item.get("id"), default=0),
                    str(item.get("name") or ""),
                    str(item.get("code") or ""),
                )
            )
        return _wilayas_cache


def get_property_type_id(name: str) -> int | None:
    """Get property type ID by name using UoW."""
    if not name:
        return None
    normalized = name.strip().lower()
    for type_id, type_name in _get_property_types_cache():
        if type_name.strip().lower() == normalized:
            return type_id
    return None


def get_property_type_name(type_id: int) -> str | None:
    """Get property type name by ID using UoW."""
    for cached_id, type_name in _get_property_types_cache():
        if cached_id == type_id:
            return type_name
    return None


def get_action_id(name: str) -> int | None:
    """Get action ID by name using UoW."""
    if not name:
        return None
    normalized = name.strip().lower()
    for action_id, action_name in _get_actions_cache():
        if action_name.strip().lower() == normalized:
            return action_id
    return None


def get_action_name(action_id: int) -> str | None:
    """Get action name by ID using UoW."""
    for cached_id, action_name in _get_actions_cache():
        if cached_id == action_id:
            return action_name
    return None


def get_wilaya_id(name: str) -> int | None:
    """Get wilaya ID by name using UoW."""
    if not name:
        return None
    normalized = name.strip().lower()
    for wilaya_id, wilaya_name, _ in _get_wilayas_cache():
        if wilaya_name.strip().lower() == normalized:
            return wilaya_id
    return None


def get_wilaya_name(wilaya_id: int) -> str | None:
    """Get wilaya name by ID using UoW."""
    for cached_id, wilaya_name, _ in _get_wilayas_cache():
        if cached_id == wilaya_id:
            return wilaya_name
    return None


def get_all_property_types() -> list[tuple[int, str]]:
    """Get all property types using UoW."""
    return _get_property_types_cache()


def get_all_actions() -> list[tuple[int, str]]:
    """Get all actions using UoW."""
    return _get_actions_cache()


def get_all_wilayas() -> list[tuple[int, str, str]]:
    """Get all wilayas using UoW."""
    return _get_wilayas_cache()
