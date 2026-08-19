"""Importer business metrics owner."""

from __future__ import annotations

from functools import lru_cache

from server.immoapp_server.business_metrics_core import (
    _counter,
    _histogram,
    _histogram_ms,
    _NoopCounter,
    _NoopHistogram,
)
from server.immoapp_server.business_metrics_governance import record_tenant_budget_event


@lru_cache(maxsize=1)
def _import_runs_counter() -> _NoopCounter:
    return _counter("immoapp.import.runs", "Import executions by entity and outcome.")


@lru_cache(maxsize=1)
def _import_rows_counter() -> _NoopCounter:
    return _counter("immoapp.import.rows", "Rows processed by import outcome.")


@lru_cache(maxsize=1)
def _import_duration_hist() -> _NoopHistogram:
    return _histogram_ms("immoapp.import.duration.ms", "Import execution duration.")


@lru_cache(maxsize=1)
def _import_status_event_counter() -> _NoopCounter:
    return _counter(
        "immoapp.import.status.events",
        "Importer state, repair, mapping, and terminal outcome events.",
    )


@lru_cache(maxsize=1)
def _import_wait_hist() -> _NoopHistogram:
    return _histogram(
        "immoapp.import.wait.seconds",
        "s",
        "Importer queue and worker pickup wait duration.",
    )


def record_import_execution(
    *,
    entity_type: str,
    outcome: str,
    created: int,
    skipped: int,
    errors: int,
    review: int,
    duration_s: float,
    db_duration_s: float,
    terminal_reason: str = "",
    result_zero_change: bool = False,
) -> None:
    attrs = {
        "entity_type": entity_type,
        "outcome": outcome,
        "terminal_reason": str(terminal_reason or ""),
        "result_zero_change": "true" if result_zero_change else "false",
    }
    _import_runs_counter().add(1, attributes=attrs)
    if created > 0:
        _import_rows_counter().add(created, attributes={**attrs, "row_outcome": "created"})
    if skipped > 0:
        _import_rows_counter().add(skipped, attributes={**attrs, "row_outcome": "skipped"})
    if errors > 0:
        _import_rows_counter().add(errors, attributes={**attrs, "row_outcome": "error"})
    if review > 0:
        _import_rows_counter().add(review, attributes={**attrs, "row_outcome": "review"})
    _import_duration_hist().record(duration_s * 1000.0, attributes={**attrs, "phase": "total"})
    _import_duration_hist().record(db_duration_s * 1000.0, attributes={**attrs, "phase": "db"})


def record_import_status_signal(
    *,
    event: str,
    terminal_reason: str = "",
    wait_state: str = "",
    stalled_reason: str = "",
    mapping_palette_mode: str = "",
    file_model_hint: str = "",
    dominant_side: str = "",
    manual_mapping_required: bool = False,
    result_zero_change: bool = False,
    cancel_requested: bool = False,
    repair_attempted: bool = False,
    requeued_after_lease_expiry: bool = False,
    projection_conflict_count: int = 0,
    row_outlier_review_count: int = 0,
    count: int = 1,
    wait_seconds: float | None = None,
) -> None:
    if count <= 0:
        return
    attrs = {
        "event": str(event or "unknown"),
        "terminal_reason": str(terminal_reason or ""),
        "wait_state": str(wait_state or ""),
        "stalled_reason": str(stalled_reason or ""),
        "mapping_palette_mode": str(mapping_palette_mode or ""),
        "file_model_hint": str(file_model_hint or ""),
        "dominant_side": str(dominant_side or ""),
        "manual_mapping_required": "true" if manual_mapping_required else "false",
        "result_zero_change": "true" if result_zero_change else "false",
        "cancel_requested": "true" if cancel_requested else "false",
        "repair_attempted": "true" if repair_attempted else "false",
        "requeued_after_lease_expiry": "true" if requeued_after_lease_expiry else "false",
        "projection_conflict_count": str(max(0, int(projection_conflict_count or 0))),
        "row_outlier_review_count": str(max(0, int(row_outlier_review_count or 0))),
    }
    _import_status_event_counter().add(int(count), attributes=attrs)
    if wait_seconds is not None:
        _import_wait_hist().record(
            max(0.0, float(wait_seconds)),
            attributes={
                "event": str(event or "unknown"),
                "wait_state": str(wait_state or ""),
            },
        )


def record_import_execution_budget_decision(
    *,
    allowed: bool,
    agency_id: int | None,
    cost: int,
    profile: str,
) -> None:
    outcome = "allowed" if allowed else "backpressured"
    record_tenant_budget_event("import_execute", outcome, agency_id)
    _import_rows_counter().add(
        max(1, int(cost or 1)),
        attributes={
            "entity_type": "import_execute_budget",
            "outcome": outcome,
            "row_outcome": str(profile or "unknown"),
        },
    )


def record_import_execution_profile(profile: str) -> None:
    _import_runs_counter().add(
        1,
        attributes={
            "entity_type": "import_execute_profile",
            "outcome": str(profile or "unknown"),
        },
    )


__all__ = [
    "record_import_execution",
    "record_import_execution_budget_decision",
    "record_import_execution_profile",
    "record_import_status_signal",
]
