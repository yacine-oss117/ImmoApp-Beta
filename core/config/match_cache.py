"""Match cache performance and retry settings."""

from __future__ import annotations

import os

from core.runtime.hub_runtime_profile import resolve_hub_runtime_profile


def _read_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _read_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


CACHE_BATCH_THRESHOLD = _read_int("CACHE_BATCH_THRESHOLD", 1000, minimum=100, maximum=50_000)
CACHE_CHUNK_SIZE = _read_int("CACHE_CHUNK_SIZE", 5000, minimum=200, maximum=50_000)
CACHE_LOCK_TIMEOUT_MS = _read_int("CACHE_LOCK_TIMEOUT_MS", 250, minimum=50, maximum=2_000)
CACHE_STATEMENT_TIMEOUT_MS = _read_int(
    "CACHE_STATEMENT_TIMEOUT_MS", 5_000, minimum=2_000, maximum=15_000
)
CACHE_WRITE_MAX_ATTEMPTS = _read_int("CACHE_WRITE_MAX_ATTEMPTS", 4, minimum=3, maximum=6)
CACHE_RETRY_BASE_DELAY_SEC = _read_float(
    "CACHE_RETRY_BASE_DELAY_SEC", 0.05, minimum=0.025, maximum=0.1
)
CACHE_DIRTY_MARK_CHUNK_SIZE = _read_int(
    "CACHE_DIRTY_MARK_CHUNK_SIZE", 10_000, minimum=1_000, maximum=50_000
)

MATCH_CACHE_MAX_ROWS_PER_RUN = _read_int(
    "MATCH_CACHE_MAX_ROWS_PER_RUN", 200_000, minimum=20_000, maximum=2_000_000
)
MATCH_CACHE_DB_BATCH_SIZE = min(
    _read_int("MATCH_CACHE_DB_BATCH_SIZE", 1_000, minimum=50, maximum=20_000),
    resolve_hub_runtime_profile().limits.match_batch_size,
)
MATCH_CACHE_SOFT_TIME_LIMIT_SEC = _read_int(
    "MATCH_CACHE_SOFT_TIME_LIMIT_SEC", 240, minimum=60, maximum=900
)
MATCH_CACHE_HARD_TIME_LIMIT_SEC = _read_int(
    "MATCH_CACHE_HARD_TIME_LIMIT_SEC",
    max(MATCH_CACHE_SOFT_TIME_LIMIT_SEC + 60, 300),
    minimum=MATCH_CACHE_SOFT_TIME_LIMIT_SEC + 30,
    maximum=MATCH_CACHE_SOFT_TIME_LIMIT_SEC + 120,
)
MATCH_CACHE_CHECKPOINT_LEASE_SEC = _read_int(
    "MATCH_CACHE_CHECKPOINT_LEASE_SEC", 120, minimum=15, maximum=3600
)
MATCH_CACHE_LOCK_TIMEOUT_MS = _read_int(
    "MATCH_CACHE_LOCK_TIMEOUT_MS", 250, minimum=50, maximum=2_000
)


__all__ = [
    "CACHE_BATCH_THRESHOLD",
    "CACHE_CHUNK_SIZE",
    "CACHE_DIRTY_MARK_CHUNK_SIZE",
    "CACHE_LOCK_TIMEOUT_MS",
    "CACHE_RETRY_BASE_DELAY_SEC",
    "CACHE_STATEMENT_TIMEOUT_MS",
    "CACHE_WRITE_MAX_ATTEMPTS",
    "MATCH_CACHE_CHECKPOINT_LEASE_SEC",
    "MATCH_CACHE_DB_BATCH_SIZE",
    "MATCH_CACHE_HARD_TIME_LIMIT_SEC",
    "MATCH_CACHE_LOCK_TIMEOUT_MS",
    "MATCH_CACHE_MAX_ROWS_PER_RUN",
    "MATCH_CACHE_SOFT_TIME_LIMIT_SEC",
]
