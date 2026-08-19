"""Execute-request orchestration helpers for import views."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from rest_framework import status
from rest_framework.request import Request

from server.imports.models import ImportJob
from server.services.import_status_policy import queue_poll_after_ms


@dataclass(frozen=True)
class ExecuteRequestOutcome:
    payload: dict[str, object]
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _normalize_column_mapping(value: object, fallback: object) -> dict[str, str]:
    candidates = [value, fallback, {}]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return {str(key): str(item) for key, item in candidate.items()}
    return {}


def execute_import_request(
    *,
    request: Request,
    session: ImportJob,
    user_id: int,
    agency_id: int,
    data: dict[str, object],
    request_correlation_id_fn: Callable[[Request], str | None],
    canonicalize_column_mapping_fn: Callable[..., dict[str, str]],
    normalize_import_entity_type_fn: Callable[[str | None], str],
    build_import_decision_fn: Callable[..., Any],
    normalize_duplicate_strategy_fn: Callable[[str | None], str],
    calculate_import_execution_cost_fn: Callable[..., int],
    effective_import_runtime_profile_fn: Callable[[], Any],
    admit_import_execute_fn: Callable[..., Any],
    record_import_execution_profile_fn: Callable[[str], object],
    record_import_execution_budget_decision_fn: Callable[..., object],
    initialize_distributed_workflow_fn: Callable[..., tuple[dict[str, object], bool]],
    save_workflow_payload_fn: Callable[[ImportJob, dict[str, object]], None],
    claim_execution_or_queue_fn: Callable[..., Any],
    enqueue_import_task_fn: Callable[..., Any],
    register_task_fn: Callable[..., object],
    get_active_schema_fn: Callable[[], str],
) -> ExecuteRequestOutcome:
    final_inference = dict((session.inference_summary or {}).get("final_inference", {}) or {})
    column_mapping = canonicalize_column_mapping_fn(
        column_mapping=_normalize_column_mapping(
            data.get("column_mapping"), session.column_mapping
        ),
        detected_columns=session.detected_columns or [],
        final_inference=final_inference,
    )
    if not column_mapping:
        return ExecuteRequestOutcome(
            payload={"detail": "column_mapping required"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    skip_rows = _optional_int(data.get("skip_rows")) or 0
    entity_type_raw = data.get("entity_type")
    entity_type = normalize_import_entity_type_fn(
        entity_type_raw if isinstance(entity_type_raw, str) else session.detected_entity
    )
    decision = build_import_decision_fn(
        final_inference=final_inference,
        detected_columns=session.detected_columns or [],
        column_mapping=column_mapping,
        detected_entity=entity_type,
        sheet_profiles=(session.inference_summary or {}).get("sheet_profiles", []),
        selected_sheet_name=str(
            (session.inference_summary or {}).get("selected_sheet_name", "") or ""
        ),
        preview_rows=session.preview_rows or [],
        recoverability_summary=(session.inference_summary or {}).get(
            "preview_recoverability_summary", {}
        ),
        preview_attention_summary=(session.inference_summary or {}).get(
            "preview_attention_summary", {}
        ),
    )
    if decision.outcome == "block":
        return ExecuteRequestOutcome(
            payload={"detail": decision.blocking_message or "This file cannot be imported safely."},
            status_code=status.HTTP_409_CONFLICT,
        )
    if decision.outcome == "manual_mapping":
        detail = "Manual mapping or review is required before execution."
        if decision.manual_mapping_reasons:
            detail = (
                f"{detail} {' '.join(str(reason) for reason in decision.manual_mapping_reasons)}"
            )
        return ExecuteRequestOutcome(
            payload={"detail": detail},
            status_code=status.HTTP_409_CONFLICT,
        )

    duplicate_strategy_raw = data.get("duplicate_strategy")
    duplicate_strategy = normalize_duplicate_strategy_fn(
        duplicate_strategy_raw if isinstance(duplicate_strategy_raw, str) else None
    )
    skip_review_rows = bool(data.get("skip_review_rows", False))
    corrections = data.get("corrections")
    row_count = _optional_int((session.result_summary or {}).get("row_count")) or 0
    bundle_mode = str(final_inference.get("bundle_mode", "single_entity") or "single_entity")
    preview_normalization = dict(
        (session.inference_summary or {}).get("preview_normalization_summary", {}) or {}
    )
    expected_review_ratio = 0.0
    try:
        preview_rows_total = float(preview_normalization.get("rows_total", 0) or 0)
        preview_rows_review = float(preview_normalization.get("rows_need_review", 0) or 0)
        if preview_rows_total > 0:
            expected_review_ratio = max(0.0, min(1.0, preview_rows_review / preview_rows_total))
    except Exception:
        expected_review_ratio = 0.0
    execution_cost = calculate_import_execution_cost_fn(
        rows=row_count,
        entity_type=entity_type,
        duplicate_strategy=duplicate_strategy,
        smart_review_enabled=not skip_review_rows,
        bundle_mode=bundle_mode,
        expected_review_ratio=expected_review_ratio,
    )
    profile = effective_import_runtime_profile_fn()

    admission = admit_import_execute_fn(
        agency_id=int(agency_id or 0),
        cost=execution_cost,
        execution_profile=profile.name,
    )
    record_import_execution_profile_fn(admission.execution_profile)
    record_import_execution_budget_decision_fn(
        allowed=admission.allowed,
        agency_id=int(agency_id or 0),
        cost=execution_cost,
        profile=admission.execution_profile,
    )
    if not admission.allowed and not admission.queue_on_pressure:
        return ExecuteRequestOutcome(
            payload={
                "code": "IMPORT_BACKPRESSURE",
                "detail": "Import capacity is temporarily saturated for this agency.",
                "status": "rejected",
                "queue_position": 0,
                "agency_queue_depth": 0,
                "execution_profile": str(admission.execution_profile or profile.name),
                "admission_mode": str(
                    getattr(admission, "admission_mode", "rejected") or "rejected"
                ),
                "pressure_reason": str(getattr(admission, "pressure_reason", "") or ""),
                "poll_after_ms": 1000,
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(max(1, int(admission.retry_after or 10)))},
        )

    workflow, _created = initialize_distributed_workflow_fn(
        job=session,
        entity_type=entity_type,
        duplicate_strategy=duplicate_strategy,
        skip_rows=skip_rows,
        skip_review_rows=skip_review_rows,
        corrections=corrections if isinstance(corrections, dict) else None,
    )
    workflow["execution_cost"] = int(execution_cost)
    workflow["execution_profile"] = str(admission.execution_profile or profile.name)
    workflow["admission_mode"] = "degraded" if admission.degraded else "normal"
    workflow["pressure_reason"] = str(getattr(admission, "pressure_reason", "") or "")
    existing_params = workflow.get("params", {})
    workflow["params"] = {
        **(dict(existing_params) if isinstance(existing_params, dict) else {}),
        "column_mapping": dict(column_mapping),
    }
    save_workflow_payload_fn(session, workflow)
    session.inference_summary = {
        **dict(session.inference_summary or {}),
        "manual_mapping_required": decision.manual_mapping_required,
        "manual_mapping_reasons": list(decision.manual_mapping_reasons),
        "manual_mapping_metrics": dict(decision.metrics or {}),
        "mapping_palette_mode": str(decision.mapping_palette_mode or "entity_only"),
        "import_decision": decision.as_dict(),
    }
    session.detected_entity = entity_type
    session.column_mapping = column_mapping
    session.save(
        update_fields=["detected_entity", "column_mapping", "inference_summary", "updated_at"]
    )

    claim = claim_execution_or_queue_fn(
        session,
        execution_profile=str(admission.execution_profile or profile.name),
        force_queue=bool(admission.queue_on_pressure and not admission.allowed),
    )
    if claim.status == "full":
        return ExecuteRequestOutcome(
            payload={
                "code": "IMPORT_AGENCY_QUEUE_FULL",
                "detail": "One import is running and one is already queued for this agency.",
                "status": "rejected",
                "queue_position": 0,
                "agency_queue_depth": claim.agency_queue_depth,
                "execution_profile": str(admission.execution_profile or profile.name),
                "admission_mode": "rejected",
                "pressure_reason": "agency_queue_full",
                "poll_after_ms": 1000,
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": "10"},
        )

    schema = get_active_schema_fn()
    task_id = str(session.id)
    if claim.status == "running":
        async_result = enqueue_import_task_fn(
            session_id=str(session.id),
            user_id=user_id,
            agency_id=agency_id,
            entity_type=entity_type,
            column_mapping=column_mapping,
            skip_rows=skip_rows,
            duplicate_strategy=duplicate_strategy,
            skip_review_rows=skip_review_rows,
            corrections=corrections,
            execution_cost=execution_cost,
            schema=schema,
            correlation_id=request_correlation_id_fn(request),
        )
        task_id = async_result.id
        register_task_fn(
            async_result.id,
            agency_id=agency_id,
            user_id=user_id,
        )
        session.task_id = async_result.id
        session.save(update_fields=["task_id", "updated_at"])
    else:
        session.task_id = str(session.id)
        session.save(update_fields=["task_id", "updated_at"])

    return ExecuteRequestOutcome(
        payload={
            "session_id": str(session.id),
            "task_id": task_id,
            "status": claim.status,
            "queue_position": claim.queue_position,
            "agency_queue_depth": claim.agency_queue_depth,
            "execution_profile": str(admission.execution_profile or profile.name),
            "admission_mode": "degraded" if admission.degraded else "normal",
            "pressure_reason": str(getattr(admission, "pressure_reason", "") or ""),
            "poll_after_ms": queue_poll_after_ms(claim_status=claim.status),
        },
        status_code=status.HTTP_202_ACCEPTED,
    )


__all__ = [
    "ExecuteRequestOutcome",
    "execute_import_request",
]
