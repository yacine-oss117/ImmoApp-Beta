from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Literal

import pytest


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


@dataclass
class _FakeCounter:
    name: str
    unit: str
    description: str
    events: list[tuple[int, dict[str, object]]] = field(default_factory=list)

    def add(self, value: int, *, attributes: dict[str, object] | None = None) -> None:
        self.events.append((int(value), dict(attributes or {})))


@dataclass
class _FakeHistogram:
    name: str
    unit: str
    description: str
    events: list[tuple[float, dict[str, object]]] = field(default_factory=list)

    def record(self, value: float, *, attributes: dict[str, object] | None = None) -> None:
        self.events.append((float(value), dict(attributes or {})))


@dataclass
class _FakeObservableGauge:
    name: str
    unit: str
    description: str
    callback: Callable[[], list[tuple[float, dict[str, object]]]]


class _FakeMeter:
    def __init__(self) -> None:
        self.counters: dict[str, _FakeCounter] = {}
        self.histograms: dict[str, _FakeHistogram] = {}
        self.gauges: dict[str, _FakeObservableGauge] = {}

    def create_counter(self, name: str, *, unit: str, description: str) -> _FakeCounter:
        counter = _FakeCounter(name=name, unit=unit, description=description)
        self.counters[name] = counter
        return counter

    def create_histogram(self, name: str, *, unit: str, description: str) -> _FakeHistogram:
        histogram = _FakeHistogram(name=name, unit=unit, description=description)
        self.histograms[name] = histogram
        return histogram

    def create_observable_gauge(
        self,
        name: str,
        *,
        unit: str,
        description: str,
        callback: Callable[[], list[tuple[float, dict[str, object]]]],
    ) -> _FakeObservableGauge:
        gauge = _FakeObservableGauge(
            name=name,
            unit=unit,
            description=description,
            callback=callback,
        )
        self.gauges[name] = gauge
        return gauge


class _FakeCursor:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def fetchone(self) -> dict[str, object] | None:
        return self._row


class _FakeSession:
    def __init__(self, row: dict[str, object] | None = None) -> None:
        self.row = row
        self.queries: list[tuple[str, tuple[object, ...] | None]] = []

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> _FakeCursor:
        self.queries.append((sql, params))
        return _FakeCursor(self.row)


class _Context:
    def __init__(self, value: object | None = None) -> None:
        self._value = value

    def __enter__(self) -> object | None:
        return self._value

    def __exit__(self, exc_type: object, exc: object, tb: object) -> Literal[False]:
        _ = (exc_type, exc, tb)
        return False


class _FakeUow:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def transaction(self, **_kwargs: object) -> _Context:
        return _Context(self._session)

    def session(self, **_kwargs: object) -> _Context:
        return _Context(self._session)


@pytest.fixture(autouse=True)
def _reset_metric_state() -> None:
    _ensure_django()
    from server.immoapp_server import (
        business_metrics_core,
        business_metrics_governance,
        business_metrics_imports,
        business_metrics_match,
        business_metrics_runtime,
    )

    for module in (
        business_metrics_core,
        business_metrics_governance,
        business_metrics_imports,
        business_metrics_match,
        business_metrics_runtime,
    ):
        for name in dir(module):
            candidate = getattr(module, name)
            if callable(candidate) and hasattr(candidate, "cache_clear"):
                candidate.cache_clear()
    with business_metrics_governance._TENANT_USAGE_SNAPSHOT_LOCK:
        business_metrics_governance._TENANT_USAGE_SNAPSHOT.clear()
    with business_metrics_match._MATCH_RUNTIME_PROFILE_SNAPSHOT_LOCK:
        business_metrics_match._MATCH_RUNTIME_PROFILE_SNAPSHOT.clear()
        business_metrics_match._MATCH_RUNTIME_PROFILE_SNAPSHOT.update(
            {"profile_value": 1.0, "stale": 0.0}
        )


def test_business_metric_split_preserves_metric_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.observability.metrics as metrics_module
    from server.immoapp_server import (
        business_metrics_governance,
        business_metrics_imports,
        business_metrics_match,
        business_metrics_runtime,
    )
    from server.pg import uow

    fake_meter = _FakeMeter()
    fake_session = _FakeSession(row={"statement_timeout_count": 7, "lock_timeout_count": 3})
    monkeypatch.setattr(metrics_module, "get_meter", lambda _name: fake_meter)
    monkeypatch.setattr(uow, "get_uow", lambda: _FakeUow(fake_session))
    monkeypatch.setattr(uow, "use_schema", lambda _schema: _Context())
    monkeypatch.setattr(
        uow,
        "use_security_context",
        lambda **_kwargs: _Context(),
    )

    business_metrics_imports.record_import_execution(
        entity_type="offers",
        outcome="success",
        created=3,
        skipped=1,
        errors=2,
        review=4,
        duration_s=1.25,
        db_duration_s=0.5,
        terminal_reason="",
        result_zero_change=False,
    )
    business_metrics_imports.record_import_status_signal(
        event="queued",
        wait_state="worker_pickup",
        count=2,
        wait_seconds=3.5,
    )
    business_metrics_imports.record_import_execution_budget_decision(
        allowed=False,
        agency_id=12,
        cost=5,
        profile="yellow",
    )
    business_metrics_imports.record_import_execution_profile("yellow")

    business_metrics_match.record_match_pair_rebuild(
        outcome="success",
        candidates=9,
        stored=5,
        duration_s=0.75,
    )
    business_metrics_match.record_match_artifact_pipeline(
        mode="direct",
        outcome="success",
        batch_size=11,
        candidates=20,
        ranked=15,
        stored=10,
        duration_s=1.5,
    )
    business_metrics_match.record_match_cache_lookup(
        cache_name="match_counts_cache",
        outcome="hit",
        count=4,
    )
    business_metrics_match.record_cache_event(
        "match_counts_cache",
        "l1",
        "hit",
        "tenant:12",
        2,
    )
    business_metrics_match.record_cache_fill_latency(
        "match_counts_cache",
        "source",
        0.25,
    )
    business_metrics_match.record_cache_payload_bytes(
        "match_counts_cache",
        "l1",
        512,
    )
    business_metrics_match.record_cache_pressure(
        "match_counts_cache",
        "l1",
        "state",
        4096,
        32,
    )
    business_metrics_match.record_match_artifact_timeout(
        kind="statement_timeout",
        count=2,
    )
    counters = business_metrics_match.read_match_artifact_timeout_counters()
    business_metrics_match.record_match_runtime_profile_transition(
        profile="yellow",
        reason="yellow_recovered",
    )
    business_metrics_match.record_match_runtime_profile_state(
        profile="yellow",
        reason="yellow_recovered",
        sample_age_seconds=5,
        stale=True,
    )

    business_metrics_runtime.record_http_request_latency(
        route_name="users-list",
        status_code=204,
        duration_s=0.2,
        outcome="ok",
    )
    business_metrics_governance.record_queue_saturation(
        queue="rebuild_batch",
        outcome="backpressured",
        count=3,
    )
    business_metrics_governance.record_tenant_budget_event(
        "rebuild_cache",
        "allowed",
        12,
    )
    business_metrics_governance.record_tenant_usage_gauge(
        12,
        composite_ratio=0.75,
        in_flight_ratio=0.5,
        api_rate_ratio=0.25,
    )

    created = (
        {name: ("counter", counter.unit) for name, counter in fake_meter.counters.items()}
        | {name: ("histogram", histogram.unit) for name, histogram in fake_meter.histograms.items()}
        | {name: ("gauge", gauge.unit) for name, gauge in fake_meter.gauges.items()}
    )
    assert created == {
        "immoapp.import.runs": ("counter", "1"),
        "immoapp.import.rows": ("counter", "1"),
        "immoapp.import.duration.ms": ("histogram", "ms"),
        "immoapp.import.status.events": ("counter", "1"),
        "immoapp.import.wait.seconds": ("histogram", "s"),
        "immoapp.matcher.pair_rebuild.runs": ("counter", "1"),
        "immoapp.matcher.pair_rebuild.rows": ("counter", "1"),
        "immoapp.matcher.pair_rebuild.duration.ms": ("histogram", "ms"),
        "immoapp.matcher.artifact_pipeline.runs": ("counter", "1"),
        "immoapp.matcher.artifact_pipeline.rows": ("counter", "1"),
        "immoapp.matcher.artifact_pipeline.duration.ms": ("histogram", "ms"),
        "immoapp.matcher.cache.lookups": ("counter", "1"),
        "immoapp.cache.events": ("counter", "1"),
        "immoapp.cache.fill.duration.ms": ("histogram", "ms"),
        "immoapp.cache.payload.bytes": ("histogram", "By"),
        "immoapp.cache.pressure": ("histogram", "1"),
        "immoapp.matcher.artifact_timeout.events": ("counter", "1"),
        "immoapp.matcher.runtime_profile.transitions": ("counter", "1"),
        "immoapp.matcher.runtime_profile.state": ("gauge", "1"),
        "immoapp.matcher.runtime_profile.stale": ("gauge", "1"),
        "immoapp.http.request.duration.ms": ("histogram", "ms"),
        "immoapp.http.request.count": ("counter", "1"),
        "immoapp.queue.saturation.events": ("counter", "1"),
        "immoapp.tenant.budget.events": ("counter", "1"),
        "immoapp.tenant.usage.ratio": ("gauge", "1"),
        "immoapp.tenant.usage.in_flight_ratio": ("gauge", "1"),
        "immoapp.tenant.usage.api_rate_ratio": ("gauge", "1"),
    }

    assert fake_meter.counters["immoapp.import.runs"].events[0] == (
        1,
        {
            "entity_type": "offers",
            "outcome": "success",
            "terminal_reason": "",
            "result_zero_change": "false",
        },
    )
    assert (3, {"event": "queued", "wait_state": "worker_pickup"}) not in fake_meter.histograms[
        "immoapp.import.wait.seconds"
    ].events
    assert fake_meter.histograms["immoapp.import.wait.seconds"].events == [
        (3.5, {"event": "queued", "wait_state": "worker_pickup"})
    ]
    assert any(
        attrs == {"mode": "direct", "outcome": "success", "kind": "run"}
        for _value, attrs in fake_meter.counters["immoapp.matcher.artifact_pipeline.runs"].events
    )
    assert fake_meter.counters["immoapp.http.request.count"].events == [
        (
            1,
            {
                "route_name": "users-list",
                "status_class": "2xx",
                "outcome": "ok",
            },
        )
    ]
    assert fake_meter.counters["immoapp.queue.saturation.events"].events == [
        (3, {"queue": "rebuild_batch", "outcome": "backpressured"})
    ]
    assert any(
        attrs == {"outcome": "allowed", "kind": "rebuild_cache"}
        for _value, attrs in fake_meter.counters["immoapp.tenant.budget.events"].events
    )
    assert fake_meter.gauges["immoapp.tenant.usage.ratio"].callback() == [
        (0.75, {"kind": "composite_ratio"})
    ]
    assert fake_meter.gauges["immoapp.tenant.usage.in_flight_ratio"].callback() == [
        (0.5, {"kind": "in_flight_ratio"})
    ]
    assert fake_meter.gauges["immoapp.tenant.usage.api_rate_ratio"].callback() == [
        (0.25, {"kind": "api_rate_ratio"})
    ]
    assert fake_meter.gauges["immoapp.matcher.runtime_profile.state"].callback() == [
        (2.0, {"kind": "profile_value"})
    ]
    assert fake_meter.gauges["immoapp.matcher.runtime_profile.stale"].callback() == [
        (1.0, {"kind": "stale"})
    ]
    assert counters == {"statement_timeout_count": 7, "lock_timeout_count": 3}
    assert "INSERT INTO match_artifact_timeout_counters" in fake_session.queries[0][0]
    assert "UPDATE match_artifact_timeout_counters" in fake_session.queries[1][0]
    assert fake_session.queries[1][1] == (2,)
    assert "SELECT" in fake_session.queries[2][0]


def test_business_metric_split_keeps_noop_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.observability.metrics as metrics_module
    from server.immoapp_server import (
        business_metrics_governance,
        business_metrics_imports,
        business_metrics_match,
        business_metrics_runtime,
    )

    def _boom(_name: str) -> object:
        raise RuntimeError("meter unavailable")

    monkeypatch.setattr(metrics_module, "get_meter", _boom)

    business_metrics_imports.record_import_execution(
        entity_type="offers",
        outcome="success",
        created=1,
        skipped=0,
        errors=0,
        review=0,
        duration_s=0.0,
        db_duration_s=0.0,
    )
    business_metrics_match.record_match_pair_rebuild(
        outcome="success",
        candidates=1,
        stored=1,
        duration_s=0.0,
    )
    business_metrics_runtime.record_http_request_latency(
        route_name="users-list",
        status_code=200,
        duration_s=0.0,
        outcome="ok",
    )
    business_metrics_governance.record_tenant_usage_gauge(
        12,
        composite_ratio=0.0,
        in_flight_ratio=0.0,
        api_rate_ratio=0.0,
    )
