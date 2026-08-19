"""Circuit breaker logic for API requests."""

from __future__ import annotations

import os
import random
import threading
import time
from typing import Any

_CB_FAILURE_THRESHOLD = 3
_CB_RESET_SECONDS = max(
    5.0,
    float(os.environ.get("API_CIRCUIT_RESET_SECONDS", "30")),
)
_CB_STATE_CLOSED = "closed"
_CB_STATE_OPEN = "open"
_CB_STATE_HALF_OPEN = "half_open"
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_BASE = 0.5
_RETRY_BACKOFF_MAX = 5.0
_RETRY_BACKOFF_JITTER_RATIO = min(
    0.9,
    max(0.0, float(os.environ.get("API_CIRCUIT_RETRY_JITTER_RATIO", "0.30"))),
)

_cb_lock = threading.Lock()
_cb_failures = 0
_cb_open_until = 0.0
_cb_state = _CB_STATE_CLOSED
_cb_probe_inflight = False


def circuit_check() -> None:
    """Raise if the circuit breaker is open."""
    now = time.monotonic()
    with _cb_lock:
        global _cb_probe_inflight, _cb_state
        if _cb_state == _CB_STATE_OPEN:
            if _cb_open_until > now:
                raise RuntimeError("API temporarily unavailable (circuit open)")
            _cb_state = _CB_STATE_HALF_OPEN
        if _cb_state == _CB_STATE_HALF_OPEN:
            if _cb_probe_inflight:
                raise RuntimeError("API temporarily unavailable (circuit half-open)")
            _cb_probe_inflight = True


def record_api_success() -> None:
    global _cb_failures, _cb_open_until, _cb_probe_inflight, _cb_state
    with _cb_lock:
        _cb_failures = 0
        _cb_open_until = 0.0
        _cb_state = _CB_STATE_CLOSED
        _cb_probe_inflight = False


def reset_api_circuit() -> None:
    """Force-reset the API circuit breaker state."""
    record_api_success()


def record_api_failure() -> None:
    global _cb_failures, _cb_open_until, _cb_probe_inflight, _cb_state
    now = time.monotonic()
    with _cb_lock:
        if _cb_state == _CB_STATE_HALF_OPEN:
            _cb_failures = _CB_FAILURE_THRESHOLD
            _cb_open_until = now + _CB_RESET_SECONDS
            _cb_state = _CB_STATE_OPEN
            _cb_probe_inflight = False
            return
        _cb_failures += 1
        if _cb_failures >= _CB_FAILURE_THRESHOLD:
            _cb_open_until = now + _CB_RESET_SECONDS
            _cb_state = _CB_STATE_OPEN


def retry_backoff(attempt: int) -> None:
    sleep_for = min(_RETRY_BACKOFF_MAX, _RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))
    if _RETRY_BACKOFF_JITTER_RATIO > 0.0:
        low = max(0.0, 1.0 - _RETRY_BACKOFF_JITTER_RATIO)
        high = 1.0 + _RETRY_BACKOFF_JITTER_RATIO
        sleep_for *= random.uniform(low, high)
        sleep_for = min(_RETRY_BACKOFF_MAX, sleep_for)
    time.sleep(sleep_for)


def should_retry_status(status_code: int) -> bool:
    return status_code in {429, 502, 503, 504}


def should_trip_circuit(status_code: int, payload: object | None = None) -> bool:
    if not should_retry_status(status_code):
        return False
    if status_code == 503 and isinstance(payload, dict):
        code = str(payload.get("code") or "").strip().upper()
        if code in {"REGISTRATION_UNAVAILABLE", "EMAIL_QUEUE_UNAVAILABLE"}:
            return False
    return True


def get_api_circuit_snapshot() -> dict[str, Any]:
    """Return a small thread-safe snapshot for UI and sync logic."""
    now = time.monotonic()
    with _cb_lock:
        open_for_seconds = 0.0
        if _cb_state == _CB_STATE_OPEN and _cb_open_until > now:
            open_for_seconds = _cb_open_until - now
        return {
            "state": _cb_state,
            "failures": _cb_failures,
            "open_for_seconds": open_for_seconds,
            "probe_inflight": _cb_probe_inflight,
        }


__all__ = [
    "circuit_check",
    "record_api_success",
    "reset_api_circuit",
    "record_api_failure",
    "retry_backoff",
    "should_retry_status",
    "should_trip_circuit",
    "get_api_circuit_snapshot",
    "_RETRY_ATTEMPTS",
]
