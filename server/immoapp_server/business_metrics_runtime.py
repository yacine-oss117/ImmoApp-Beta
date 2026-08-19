"""HTTP request business metrics owner."""

from __future__ import annotations

from functools import lru_cache

from server.immoapp_server.business_metrics_core import (
    _counter,
    _histogram_ms,
    _NoopCounter,
    _NoopHistogram,
)


@lru_cache(maxsize=1)
def _http_request_duration_hist() -> _NoopHistogram:
    return _histogram_ms(
        "immoapp.http.request.duration.ms",
        "HTTP request duration by route and status class.",
    )


@lru_cache(maxsize=1)
def _http_request_counter() -> _NoopCounter:
    return _counter(
        "immoapp.http.request.count",
        "HTTP request count by route, status class, and outcome.",
    )


def record_http_request_latency(
    *,
    route_name: str,
    status_code: int,
    duration_s: float,
    outcome: str,
) -> None:
    status_class = "unknown"
    if status_code >= 100:
        status_class = f"{int(status_code) // 100}xx"
    attrs = {
        "route_name": str(route_name or "unknown"),
        "status_class": status_class,
        "outcome": str(outcome or "unknown"),
    }
    _http_request_counter().add(1, attributes=attrs)
    _http_request_duration_hist().record(max(0.0, float(duration_s)) * 1000.0, attributes=attrs)


__all__ = [
    "record_http_request_latency",
]
