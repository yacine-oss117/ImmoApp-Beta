"""Settings cache helpers for agency settings."""

from __future__ import annotations

from app.services.api_client import api_get, api_post_resilient, as_dict
from app.services.api_config import get_api_base_url
from app.services.offline_account_scope import OfflineAccountScope, get_active_account_scope

_settings_cache: dict[str, dict[str, str]] = {}


def _cache_key(scope: OfflineAccountScope | None = None) -> str:
    resolved = scope or get_active_account_scope()
    if resolved is not None:
        return resolved.account_key
    return str(get_api_base_url() or "default")


def _get_settings_cache(*, scope: OfflineAccountScope | None = None) -> dict[str, str]:
    """Retrieve settings from cache, fetching from API if not cached."""
    key = _cache_key(scope)
    cached = _settings_cache.get(key)
    if cached is None:
        payload = as_dict(api_get("/settings/agency"))
        settings = payload.get("settings")
        if isinstance(settings, dict):
            cached = {str(k): str(v) for k, v in settings.items()}
        else:
            cached = {}
        _settings_cache[key] = cached
    return cached


def _update_settings_cache(
    key: str,
    value: str,
    *,
    scope: OfflineAccountScope | None = None,
) -> None:
    """Update a specific key in the settings cache."""
    cache_key = _cache_key(scope)
    cached = _settings_cache.setdefault(cache_key, {})
    cached[str(key)] = str(value)


def invalidate_agency_settings_cache(*, scope: OfflineAccountScope | None = None) -> None:
    """Invalidate cached agency settings for one account or all accounts."""
    if scope is None:
        resolved = get_active_account_scope()
        if resolved is None:
            _settings_cache.clear()
            return
        _settings_cache.pop(resolved.account_key, None)
        return
    _settings_cache.pop(scope.account_key, None)


def get_agency_setting(key: str, default: str = "") -> str:
    """Get a single agency setting by key, returning default if not found."""
    return _get_settings_cache().get(key, default)


def set_agency_setting(key: str, value: str) -> None:
    """Set a single agency setting and sync to server."""
    api_post_resilient(
        "/settings/agency/set",
        {"key": key, "value": value},
        dedupe_key=f"POST:/settings/agency/set:{key}",
        label="agency_setting.set",
    )
    _update_settings_cache(key, value)


def get_all_agency_settings() -> dict[str, str]:
    """Get all agency settings as a dictionary."""
    return dict(_get_settings_cache())


def get_agency_name() -> str:
    """Get the agency display name."""
    return get_agency_setting("agency_name", "Real Estate Agency")


def set_agency_name(name: str) -> None:
    """Set the agency display name."""
    set_agency_setting("agency_name", name)


def get_contract_serial_prefix() -> str:
    """Get the prefix used for contract serial numbers."""
    return get_agency_setting("contract_serial_prefix", "C21")


def get_audit_actor_name() -> str:
    """Get the current audit actor name for logging changes."""
    return get_agency_setting("audit_actor", "Yacine")


def set_audit_actor_name(actor: str) -> None:
    """Set the audit actor name for logging changes."""
    set_agency_setting("audit_actor", actor)


__all__ = [
    "get_agency_name",
    "get_agency_setting",
    "get_all_agency_settings",
    "get_audit_actor_name",
    "get_contract_serial_prefix",
    "invalidate_agency_settings_cache",
    "set_agency_name",
    "set_agency_setting",
    "set_audit_actor_name",
    "_update_settings_cache",
]
