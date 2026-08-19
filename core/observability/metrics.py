from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Mapping

from core.observability.metrics_guard import validate_metric_attributes

otel_metrics: Any | None
try:
    from opentelemetry import metrics as otel_metrics
except Exception:  # pragma: no cover
    otel_metrics = None


class _NoopCounter:
    def add(self, _value: int, *, attributes: Mapping[str, object] | None = None) -> None:
        return


class _NoopHistogram:
    def record(self, _value: float, *, attributes: Mapping[str, object] | None = None) -> None:
        return


class _NoopObservableGauge:
    def __init__(
        self, _callback: Callable[[], list[tuple[float, Mapping[str, object] | None]]]
    ) -> None:
        return


@dataclass(frozen=True)
class GuardedCounter:
    _inner: Any

    def add(self, value: int, *, attributes: Mapping[str, object] | None = None) -> None:
        validate_metric_attributes(attributes)
        self._inner.add(value, attributes=attributes)


@dataclass(frozen=True)
class GuardedHistogram:
    _inner: Any

    def record(self, value: float, *, attributes: Mapping[str, object] | None = None) -> None:
        validate_metric_attributes(attributes)
        self._inner.record(value, attributes=attributes)


@dataclass(frozen=True)
class GuardedObservableGauge:
    _inner: Any


class GuardedMeter:
    def __init__(self, inner: Any):
        self._inner = inner

    def create_counter(
        self, name: str, *, unit: str, description: str
    ) -> GuardedCounter | _NoopCounter:
        if self._inner is None:
            return _NoopCounter()
        return GuardedCounter(self._inner.create_counter(name, unit=unit, description=description))

    def create_histogram(
        self, name: str, *, unit: str, description: str
    ) -> GuardedHistogram | _NoopHistogram:
        if self._inner is None:
            return _NoopHistogram()
        return GuardedHistogram(
            self._inner.create_histogram(name, unit=unit, description=description)
        )

    def create_observable_gauge(
        self,
        name: str,
        *,
        unit: str,
        description: str,
        callback: Callable[[], list[tuple[float, Mapping[str, object] | None]]],
    ) -> GuardedObservableGauge | _NoopObservableGauge:
        if self._inner is None or otel_metrics is None:
            return _NoopObservableGauge(callback)

        def _wrapped(_options: Any) -> list[Any]:
            try:
                observations: list[Any] = []
                for value, attributes in callback():
                    validate_metric_attributes(attributes)
                    observations.append(otel_metrics.Observation(value, attributes))
                return observations
            except Exception:  # pragma: no cover
                return []

        return GuardedObservableGauge(
            self._inner.create_observable_gauge(
                name,
                callbacks=[_wrapped],
                unit=unit,
                description=description,
            )
        )


@lru_cache(maxsize=8)
def get_meter(name: str) -> GuardedMeter:
    """
    The only allowed way to obtain a meter in the codebase.
    Enforced by scripts/verify_no_direct_otel_metrics.py
    """
    if otel_metrics is None:
        return GuardedMeter(None)
    try:
        inner = otel_metrics.get_meter(name)
        return GuardedMeter(inner)
    except Exception:  # pragma: no cover
        return GuardedMeter(None)
