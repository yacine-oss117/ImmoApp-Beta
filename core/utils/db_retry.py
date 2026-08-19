"""SQLSTATE-scoped retry helpers for transient DB lock contention."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

import psycopg

_T = TypeVar("_T")

RETRYABLE_SQLSTATES = {
    "40P01",  # deadlock_detected
    "55P03",  # lock_not_available
    "57014",  # query_canceled (lock_timeout / statement timeout)
}


def run_with_retry(
    fn: Callable[[], _T],
    *,
    max_attempts: int = 4,
    base_delay_seconds: float = 0.05,
) -> _T:
    """Run DB unit of work with bounded retries on lock/deadlock SQLSTATEs."""
    attempts = max(1, int(max_attempts))
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except psycopg.Error as exc:
            sqlstate = getattr(exc, "sqlstate", None)
            if sqlstate not in RETRYABLE_SQLSTATES or attempt >= attempts:
                raise
            backoff = base_delay_seconds * (2 ** (attempt - 1))
            time.sleep(backoff + (random.random() * backoff))
    raise RuntimeError("retry loop exhausted without returning")


__all__ = ["RETRYABLE_SQLSTATES", "run_with_retry"]
