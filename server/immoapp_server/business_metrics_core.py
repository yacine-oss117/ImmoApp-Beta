"""Low-level business metrics primitives."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable, Iterable, Mapping, cast

MetricAttributes = Mapping[str, object]
ObservableCallback = Callable[[], Iterable[tuple[float, MetricAttributes]]]


class _NoopCounter:
    def add(self, _value: int, *, attributes: MetricAttributes | None = None) -> None:
        return


class _NoopHistogram:
    def record(self, _value: float, *, attributes: MetricAttributes | None = None) -> None:
        return


@lru_cache(maxsize=1)
def _meter() -> Any:
    try:
        from core.observability.metrics import get_meter

        return get_meter("immoapp.business.metrics")
    except Exception:
        return None


def _counter(name: str, description: str) -> _NoopCounter:
    meter = _meter()
    if meter is None:
        return _NoopCounter()
    return cast(_NoopCounter, meter.create_counter(name, unit="1", description=description))


def _histogram_ms(name: str, description: str) -> _NoopHistogram:
    meter = _meter()
    if meter is None:
        return _NoopHistogram()
    return cast(
        _NoopHistogram,
        meter.create_histogram(name, unit="ms", description=description),
    )


def _histogram(name: str, unit: str, description: str) -> _NoopHistogram:
    meter = _meter()
    if meter is None:
        return _NoopHistogram()
    return cast(
        _NoopHistogram,
        meter.create_histogram(name, unit=unit, description=description),
    )


def _observable_gauge(
    name: str,
    description: str,
    callback: ObservableCallback,
) -> object | None:
    meter = _meter()
    if meter is None:
        return None
    return cast(
        object,
        meter.create_observable_gauge(
            name,
            unit="1",
            description=description,
            callback=callback,
        ),
    )
