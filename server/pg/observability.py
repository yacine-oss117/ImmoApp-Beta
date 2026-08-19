"""
Lightweight observability hooks for the Postgres data layer.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

QueryHook = Callable[[str, float, int | None], None]
_QUERY_HOOK: QueryHook | None = None
CacheHook = Callable[[str, str], None]
_CACHE_HOOK: CacheHook | None = None


def _read_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_SLOW_QUERY_MS = max(0, _read_int_env("PG_SLOW_QUERY_MS", 500))
_MAX_SQL_LOG_LEN = max(80, _read_int_env("PG_MAX_SQL_LOG_LEN", 500))
_LOG_QUERIES = os.environ.get("PG_LOG_QUERIES", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def set_query_hook(hook: QueryHook | None) -> None:
    """Register a query timing hook for external metrics systems."""
    global _QUERY_HOOK
    _QUERY_HOOK = hook


def set_cache_hook(hook: CacheHook | None) -> None:
    """Register a cache event hook for external metrics systems."""
    global _CACHE_HOOK
    _CACHE_HOOK = hook


def record_query(sql: str, duration_s: float, rowcount: int | None = None) -> None:
    """Record a query timing event."""
    if _QUERY_HOOK is not None:
        _QUERY_HOOK(sql, duration_s, rowcount)
    duration_ms = duration_s * 1000.0
    if _LOG_QUERIES or duration_ms >= _SLOW_QUERY_MS:
        logger.info(
            "DB query %.1fms rows=%s sql=%s",
            duration_ms,
            rowcount,
            _compact_sql(sql),
        )


def _compact_sql(sql: str) -> str:
    collapsed = " ".join(sql.split())
    if len(collapsed) <= _MAX_SQL_LOG_LEN:
        return collapsed
    return collapsed[:_MAX_SQL_LOG_LEN] + "..."


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0


_CACHE_STATS: dict[str, CacheStats] = {}


def record_cache_hit(cache_name: str) -> None:
    """Track a cache hit for the named cache."""
    stats = _CACHE_STATS.setdefault(cache_name, CacheStats())
    stats.hits += 1
    if _CACHE_HOOK is not None:
        _CACHE_HOOK(cache_name, "hit")


def record_cache_miss(cache_name: str) -> None:
    """Track a cache miss for the named cache."""
    stats = _CACHE_STATS.setdefault(cache_name, CacheStats())
    stats.misses += 1
    if _CACHE_HOOK is not None:
        _CACHE_HOOK(cache_name, "miss")


def get_cache_stats() -> dict[str, dict[str, float]]:
    """Return cache hit/miss counters and hit rates."""
    snapshot: dict[str, dict[str, float]] = {}
    for cache_name, stats in _CACHE_STATS.items():
        total = stats.hits + stats.misses
        hit_rate = (stats.hits / total) if total else 0.0
        snapshot[cache_name] = {
            "hits": float(stats.hits),
            "misses": float(stats.misses),
            "hit_rate": hit_rate,
        }
    return snapshot
