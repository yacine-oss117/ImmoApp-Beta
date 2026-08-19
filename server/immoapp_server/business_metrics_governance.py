"""Governance and tenant-resource business metrics owner."""

from __future__ import annotations

import threading
from functools import lru_cache

from server.immoapp_server.business_metrics_core import (
    _counter,
    _NoopCounter,
    _observable_gauge,
)

_TENANT_USAGE_SNAPSHOT_LOCK = threading.Lock()
_TENANT_USAGE_SNAPSHOT: dict[int, dict[str, float]] = {}


@lru_cache(maxsize=1)
def _queue_saturation_counter() -> _NoopCounter:
    return _counter(
        "immoapp.queue.saturation.events",
        "Queue saturation/backpressure events by queue and outcome.",
    )


@lru_cache(maxsize=1)
def _tenant_budget_counter() -> _NoopCounter:
    return _counter(
        "immoapp.tenant.budget.events",
        "Tenant budget allow/backpressure events by budget name.",
    )


def _tenant_usage_observations(kind: str) -> list[tuple[float, dict[str, object]]]:
    with _TENANT_USAGE_SNAPSHOT_LOCK:
        items = list(_TENANT_USAGE_SNAPSHOT.items())
    if not items:
        return [(0.0, {"kind": kind})]
    max_value = max(float(values.get(kind, 0.0)) for _agency_id, values in items)
    return [(max_value, {"kind": kind})]


@lru_cache(maxsize=1)
def _tenant_usage_composite_gauge() -> object | None:
    return _observable_gauge(
        "immoapp.tenant.usage.ratio",
        "Composite tenant usage ratio.",
        lambda: _tenant_usage_observations("composite_ratio"),
    )


@lru_cache(maxsize=1)
def _tenant_usage_in_flight_gauge() -> object | None:
    return _observable_gauge(
        "immoapp.tenant.usage.in_flight_ratio",
        "Tenant in-flight work ratio.",
        lambda: _tenant_usage_observations("in_flight_ratio"),
    )


@lru_cache(maxsize=1)
def _tenant_usage_api_gauge() -> object | None:
    return _observable_gauge(
        "immoapp.tenant.usage.api_rate_ratio",
        "Tenant API rate usage ratio.",
        lambda: _tenant_usage_observations("api_rate_ratio"),
    )


def record_queue_saturation(*, queue: str, outcome: str, count: int = 1) -> None:
    if count <= 0:
        return
    _queue_saturation_counter().add(
        int(count),
        attributes={"queue": str(queue or "unknown"), "outcome": str(outcome or "unknown")},
    )


def record_tenant_budget_event(budget_name: str, outcome: str, agency_id: int | None) -> None:
    _ = agency_id
    attrs = {
        "outcome": str(outcome or "unknown"),
        "kind": str(budget_name or "unknown"),
    }
    _tenant_budget_counter().add(1, attributes=attrs)


def record_tenant_usage_gauge(
    agency_id: int,
    composite_ratio: float,
    in_flight_ratio: float,
    api_rate_ratio: float,
) -> None:
    _tenant_usage_composite_gauge()
    _tenant_usage_in_flight_gauge()
    _tenant_usage_api_gauge()
    with _TENANT_USAGE_SNAPSHOT_LOCK:
        _TENANT_USAGE_SNAPSHOT[int(agency_id)] = {
            "composite_ratio": max(0.0, min(1.0, float(composite_ratio))),
            "in_flight_ratio": max(0.0, min(1.0, float(in_flight_ratio))),
            "api_rate_ratio": max(0.0, min(1.0, float(api_rate_ratio))),
        }


__all__ = [
    "record_queue_saturation",
    "record_tenant_budget_event",
    "record_tenant_usage_gauge",
]
