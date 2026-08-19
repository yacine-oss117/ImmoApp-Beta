"""
Dashboard Cache Service - Orchestrates dashboard data refreshing via UoW.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime

from app.models_cast import as_int
from app.services.api_client import api_get, as_dict
from app.services.api_config import get_api_base_url
from app.services.offline_account_scope import OfflineAccountScope, get_active_account_scope


@dataclass
class DashboardStats:
    """In-memory cache of dashboard stats from the API."""

    client_count: int = 0
    listing_count: int = 0
    today_visits: list[dict[str, object]] = field(default_factory=list)
    pending_contracts: list[dict[str, object]] = field(default_factory=list)
    expiring_contracts: list[dict[str, object]] = field(default_factory=list)
    hot_leads: list[dict[str, object]] = field(default_factory=list)
    last_refresh: datetime | None = None
    is_stale: bool = True
    last_error: str | None = None


__all__ = [
    "DashboardStats",
    "get_dashboard_stats",
    "is_cache_stale",
    "refresh_dashboard_stats",
    "reset_dashboard_cache",
]

_api_cache: dict[str, DashboardStats] = {}
_cache_lock = threading.Lock()


def _cache_key(scope: OfflineAccountScope | None = None) -> str:
    resolved = scope or get_active_account_scope()
    if resolved is not None:
        return resolved.account_key
    return str(get_api_base_url() or "default")


def _get_api_cache(*, scope: OfflineAccountScope | None = None) -> DashboardStats:
    key = _cache_key(scope)
    cached = _api_cache.get(key)
    if cached is None:
        with _cache_lock:
            cached = _api_cache.get(key)
            if cached is None:
                cached = DashboardStats()
                _api_cache[key] = cached
    return cached


def get_dashboard_stats() -> DashboardStats:
    """Get cached stats (instant)."""
    return _get_api_cache()


def is_cache_stale() -> bool:
    """Check if cache needs refresh."""
    return _get_api_cache().is_stale


def refresh_dashboard_stats() -> DashboardStats:
    """Refresh dashboard stats using UoW."""
    payload = as_dict(api_get("/dashboard"))
    cache = _get_api_cache()
    with _cache_lock:
        cache.client_count = as_int(payload.get("client_count"), default=0)
        cache.listing_count = as_int(payload.get("listing_count"), default=0)
        cache.today_visits = _as_dict_list(payload.get("today_visits"))
        cache.pending_contracts = _as_dict_list(payload.get("pending_contracts"))
        cache.expiring_contracts = _as_dict_list(payload.get("expiring_contracts"))
        cache.hot_leads = _as_dict_list(payload.get("hot_leads"))
        cache.last_refresh = datetime.now()
        cache.last_error = None
        cache.is_stale = False
    return cache


def _as_dict_list(items: object) -> list[dict[str, object]]:
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def reset_dashboard_cache() -> None:
    """Clear cached dashboard data."""
    scope = get_active_account_scope()
    if scope is None:
        with _cache_lock:
            _api_cache.clear()
        return
    cache = _get_api_cache(scope=scope)
    with _cache_lock:
        cache.client_count = 0
        cache.listing_count = 0
        cache.today_visits = []
        cache.pending_contracts = []
        cache.expiring_contracts = []
        cache.hot_leads = []
        cache.last_refresh = None
        cache.last_error = None
        cache.is_stale = True
