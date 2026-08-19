"""Importer execution metrics owner."""

from __future__ import annotations

import time

from server.immoapp_server.business_metrics_imports import record_import_execution
from server.services.import_execution_governor import effective_import_runtime_profile
from server.services.import_types import ImportResult


def record_import_metrics(
    *,
    entity_type: str,
    result: ImportResult,
    review_count: int,
    execution_started_at: float,
    total_db_time: float,
    duration_s: float | None = None,
) -> None:
    resolved_duration_s = (
        max(0.0, float(duration_s))
        if duration_s is not None
        else max(0.0, time.monotonic() - execution_started_at)
    )
    record_import_execution(
        entity_type=entity_type,
        outcome="success" if result.success else "failed",
        created=result.created_count,
        skipped=result.skipped_count,
        errors=result.error_count,
        review=review_count,
        duration_s=resolved_duration_s,
        db_duration_s=max(0.0, total_db_time),
        terminal_reason=str(result.terminal_reason or ""),
        result_zero_change=bool(result.result_zero_change),
    )
    record_import_execution(
        entity_type=entity_type,
        outcome=f"profile:{effective_import_runtime_profile().name}",
        created=0,
        skipped=0,
        errors=0,
        review=0,
        duration_s=0.0,
        db_duration_s=0.0,
    )


__all__ = ["record_import_metrics"]
