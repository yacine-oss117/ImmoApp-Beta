"""AIMD adaptive batch processor for background task loops."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Sequence
from typing import TypeVar

from django.db import connection

from core.env_flags import EnvBoolError, parse_bool_env_value
from core.runtime.hub_runtime_profile import detect_machine_capacity, resolve_hub_runtime_profile

try:  # pragma: no cover - optional dependency path
    import psutil
except Exception:  # pragma: no cover
    psutil = None

logger = logging.getLogger(__name__)

T = TypeVar("T")

_DEFAULT_BATCH_SIZE = 100
_MIN_SLEEP = 0.01
_MAX_SLEEP = 2.0
_INITIAL_SLEEP = 0.01
_LOAD_THRESHOLD = 0.7
_MULTIPLICATIVE_FACTOR = 2.0
_ADDITIVE_STEP = 0.005
_DB_PRESSURE_LOCK = threading.Lock()
_LAST_DB_PRESSURE: tuple[float, float] = (0.0, 0.0)


def _aimd_db_pressure_enabled() -> bool:
    try:
        return parse_bool_env_value(
            "IMMOAPP_AIMD_DB_PRESSURE_ENABLED",
            os.environ.get("IMMOAPP_AIMD_DB_PRESSURE_ENABLED"),
            default=True,
        )
    except EnvBoolError:
        logger.warning("Invalid IMMOAPP_AIMD_DB_PRESSURE_ENABLED value; using enabled fallback")
        return True


def _db_pressure_cache_seconds() -> float:
    raw = os.environ.get("IMMOAPP_AIMD_DB_PRESSURE_CACHE_SECONDS", "2").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 2.0
    return max(0.0, min(value, 60.0))


def _cpu_load_ratio() -> float:
    """Return current CPU load as ratio where ~1.0 is full saturation."""
    cpu_count = detect_machine_capacity().cpu_count
    getloadavg = getattr(os, "getloadavg", None)
    try:
        if getloadavg is not None:
            load_1min = getloadavg()[0]
            return max(0.0, float(load_1min) / float(cpu_count))
    except (AttributeError, OSError):
        pass
    if psutil is not None:
        try:
            return max(0.0, min(1.0, float(psutil.cpu_percent(interval=0.0)) / 100.0))
        except Exception:
            pass
    return 0.5


def _db_pressure_ratio() -> float:
    global _LAST_DB_PRESSURE
    if not _aimd_db_pressure_enabled():
        return 0.0
    now = time.monotonic()
    with _DB_PRESSURE_LOCK:
        last_checked, cached_value = _LAST_DB_PRESSURE
        if now - last_checked <= _db_pressure_cache_seconds():
            return float(cached_value)
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    (
                        SELECT COUNT(*)
                        FROM pg_stat_activity
                        WHERE state = 'active'
                          AND pid <> pg_backend_pid()
                    ) AS active,
                    current_setting('max_connections')::int AS max_conn
                """)
            row = cursor.fetchone()
        active = int(row[0]) if row and row[0] is not None else 0
        max_conn = int(row[1]) if row and row[1] is not None else 0
        value = min(1.0, max(0.0, float(active) / float(max(max_conn, 1))))
    except Exception:
        logger.warning("AIMD DB pressure probe failed; using fail-open fallback", exc_info=True)
        value = 0.0
    with _DB_PRESSURE_LOCK:
        _LAST_DB_PRESSURE = (now, float(value))
    return float(value)


def _system_load_ratio() -> float:
    """Return current pressure ratio where ~1.0 is full saturation."""
    return max(_cpu_load_ratio(), _db_pressure_ratio())


def adaptive_batch_process(
    items: Sequence[T],
    process_fn: Callable[[T], None],
    *,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    label: str = "batch",
) -> int:
    """
    Process items in chunks with AIMD-governed delay between chunks.

    Overload path increases sleep quickly; under-load path decreases sleep slowly.
    """
    if batch_size == _DEFAULT_BATCH_SIZE:
        batch_size = resolve_hub_runtime_profile().effective_limits().default_batch_size
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")
    if not items:
        return 0

    processed = 0
    sleep_time = _INITIAL_SLEEP
    total = len(items)

    for i in range(0, total, batch_size):
        batch = items[i : i + batch_size]
        for item in batch:
            process_fn(item)
            processed += 1

        if i + batch_size >= total:
            break

        load_ratio = _system_load_ratio()
        if load_ratio > _LOAD_THRESHOLD:
            sleep_time = min(sleep_time * _MULTIPLICATIVE_FACTOR, _MAX_SLEEP)
        else:
            sleep_time = max(sleep_time - _ADDITIVE_STEP, _MIN_SLEEP)

        logger.debug(
            "adaptive_batch [%s]: %d/%d load=%.3f sleep=%.3fs",
            label,
            processed,
            total,
            load_ratio,
            sleep_time,
        )
        time.sleep(sleep_time)

    return processed


__all__ = [
    "adaptive_batch_process",
    "_cpu_load_ratio",
    "_db_pressure_ratio",
    "_system_load_ratio",
]
