"""
OpenTelemetry bootstrap for the ImmoApp server.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Protocol

logger = logging.getLogger(__name__)

_OBSERVABILITY_READY = False

if TYPE_CHECKING:
    from opentelemetry.metrics import Meter


SpanAttributeValue = str | bool | int | float | list[str] | list[bool] | list[int] | list[float]


class SpanLike(Protocol):
    def set_attribute(self, key: str, value: SpanAttributeValue) -> None: ...


class _NoopSpan:
    def set_attribute(self, _key: str, _value: SpanAttributeValue) -> None:
        return


def _normalize_span_attribute(value: object) -> SpanAttributeValue:
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        items = list(value)
        if all(isinstance(item, str) for item in items):
            return [str(item) for item in items]
        if all(isinstance(item, bool) for item in items):
            return [bool(item) for item in items]
        if all(isinstance(item, int) and not isinstance(item, bool) for item in items):
            return [int(item) for item in items]
        if all(isinstance(item, float) for item in items):
            return [float(item) for item in items]
    return str(value)


@contextmanager
def business_span(
    name: str,
    *,
    attributes: dict[str, object] | None = None,
    tracer_name: str = "immoapp.business",
) -> Iterator[SpanLike]:
    """Start a best-effort OpenTelemetry span for domain/business operations."""
    try:
        from opentelemetry import trace
    except ImportError:
        yield _NoopSpan()
        return

    tracer = trace.get_tracer(tracer_name)
    with tracer.start_as_current_span(name) as span:
        for key, value in (attributes or {}).items():
            if value is not None:
                span.set_attribute(key, _normalize_span_attribute(value))
        yield span


def setup_observability(*, service_name: str) -> None:
    """Initialize tracing, metrics, and log export when OTLP is configured."""
    global _OBSERVABILITY_READY
    if _OBSERVABILITY_READY:
        return

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return

    try:
        from opentelemetry import metrics, trace
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
        from opentelemetry.instrumentation.django import DjangoInstrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("OpenTelemetry dependencies not installed; observability disabled.")
        return

    resource = Resource.create({"service.name": service_name})

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint))
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)
    meter = metrics.get_meter("immoapp.observability")

    log_provider = LoggerProvider(resource=resource)
    log_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint))
    )
    set_logger_provider(log_provider)
    logging.getLogger().addHandler(LoggingHandler(level=logging.INFO, logger_provider=log_provider))

    DjangoInstrumentor().instrument()
    CeleryInstrumentor().instrument()
    RequestsInstrumentor().instrument()

    _wire_db_metrics(meter)
    _wire_cache_metrics(meter)
    _OBSERVABILITY_READY = True


def _wire_db_metrics(meter: Meter) -> None:
    from opentelemetry import trace

    try:
        from server.pg import observability as pg_observability
    except ImportError:
        return

    db_hist = meter.create_histogram(
        "db.query.duration.ms",
        unit="ms",
        description="Database query duration in milliseconds.",
    )
    db_rows = meter.create_counter(
        "db.query.rows",
        unit="1",
        description="Rows returned or affected by queries.",
    )
    tracer = trace.get_tracer("immoapp.db")

    def _query_hook(sql: str, duration_s: float, rowcount: int | None) -> None:
        duration_ms = duration_s * 1000.0
        attrs = {"db.system": "postgresql"}
        db_hist.record(duration_ms, attributes=attrs)
        if rowcount is not None and rowcount >= 0:
            db_rows.add(int(rowcount), attributes=attrs)

        end_ns = time.time_ns()
        start_ns = end_ns - int(duration_s * 1_000_000_000)
        span = tracer.start_span(
            "db.query",
            attributes={
                "db.system": "postgresql",
                "db.statement": _compact_sql(sql),
            },
            start_time=start_ns,
        )
        span.end(end_time=end_ns)

    pg_observability.set_query_hook(_query_hook)


def _wire_cache_metrics(meter: Meter) -> None:
    try:
        from server.pg import observability as pg_observability
    except ImportError:
        return

    cache_hits = meter.create_counter(
        "cache.hits",
        unit="1",
        description="Cache hits by cache name.",
    )
    cache_misses = meter.create_counter(
        "cache.misses",
        unit="1",
        description="Cache misses by cache name.",
    )

    def _cache_hook(cache_name: str, event: str) -> None:
        attrs = {"cache.name": cache_name}
        if event == "hit":
            cache_hits.add(1, attributes=attrs)
        else:
            cache_misses.add(1, attributes=attrs)

    pg_observability.set_cache_hook(_cache_hook)


def _compact_sql(sql: str) -> str:
    collapsed = " ".join(sql.split())
    return collapsed[:500] + "..." if len(collapsed) > 500 else collapsed
