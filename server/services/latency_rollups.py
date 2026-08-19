"""Process-local rolling latency percentiles for API routes."""

from __future__ import annotations

import os
import threading
import time
from collections import deque

_WINDOW_SECONDS = max(
    60,
    min(
        3600,
        int((os.environ.get("IMMOAPP_LATENCY_ROLLUP_WINDOW_SECONDS") or "600").strip() or "600"),
    ),
)
_MAX_SAMPLES_PER_ROUTE = max(
    100,
    min(
        20000,
        int(
            (os.environ.get("IMMOAPP_LATENCY_ROLLUP_MAX_SAMPLES_PER_ROUTE") or "5000").strip()
            or "5000"
        ),
    ),
)
_LOCK = threading.Lock()
_ROUTE_SAMPLES: dict[str, deque[tuple[float, float]]] = {}


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    pos = max(0.0, min(float(q), 1.0)) * (len(ordered) - 1)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    if low == high:
        return float(ordered[low])
    ratio = pos - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * ratio)


def _trim(route: str, now_monotonic: float) -> None:
    bucket = _ROUTE_SAMPLES.get(route)
    if bucket is None:
        return
    cutoff = now_monotonic - float(_WINDOW_SECONDS)
    while bucket and bucket[0][0] < cutoff:
        bucket.popleft()
    while len(bucket) > _MAX_SAMPLES_PER_ROUTE:
        bucket.popleft()
    if not bucket:
        _ROUTE_SAMPLES.pop(route, None)


def record_latency_sample(*, route_name: str, duration_ms: float) -> None:
    route = str(route_name or "").strip() or "unknown"
    duration = max(0.0, float(duration_ms))
    now = time.monotonic()
    with _LOCK:
        bucket = _ROUTE_SAMPLES.get(route)
        if bucket is None:
            bucket = deque()
            _ROUTE_SAMPLES[route] = bucket
        bucket.append((now, duration))
        _trim(route, now)


def route_latency_snapshot(route_name: str) -> dict[str, object] | None:
    route = str(route_name or "").strip() or "unknown"
    now = time.monotonic()
    with _LOCK:
        _trim(route, now)
        bucket = _ROUTE_SAMPLES.get(route)
        if not bucket:
            return None
        values = [sample[1] for sample in bucket]
    return {
        "route_name": route,
        "sample_count": len(values),
        "p50_ms": round(_percentile(values, 0.50), 2),
        "p95_ms": round(_percentile(values, 0.95), 2),
        "p99_ms": round(_percentile(values, 0.99), 2),
        "window_seconds": _WINDOW_SECONDS,
    }


def _p95_sort_key(row: dict[str, object]) -> float:
    value = row.get("p95_ms", 0.0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def list_latency_snapshots(*, limit: int = 50) -> list[dict[str, object]]:
    now = time.monotonic()
    normalized_limit = max(1, min(int(limit), 500))
    with _LOCK:
        routes = list(_ROUTE_SAMPLES.keys())
        for route in routes:
            _trim(route, now)
        active_routes = list(_ROUTE_SAMPLES.keys())
    snapshots: list[dict[str, object]] = []
    for route in active_routes:
        snap = route_latency_snapshot(route)
        if snap is not None:
            snapshots.append(snap)
    snapshots.sort(key=_p95_sort_key, reverse=True)
    return snapshots[:normalized_limit]


def clear_latency_rollups() -> None:
    with _LOCK:
        _ROUTE_SAMPLES.clear()


def rollup_window_seconds() -> int:
    return _WINDOW_SECONDS


__all__ = [
    "clear_latency_rollups",
    "list_latency_snapshots",
    "record_latency_sample",
    "rollup_window_seconds",
    "route_latency_snapshot",
]
