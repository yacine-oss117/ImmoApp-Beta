"""Public importer status payload projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from server.services import tenant_resource_governor
from server.services.import_execution_governor import effective_import_runtime_profile
from server.services.import_execution_health import execution_health_snapshot
from server.services.import_follow_up import normalize_follow_up_outcome
from server.services.import_job_queue import queue_position_for_job
from server.services.import_mapping import canonicalize_column_mapping
from server.services.import_mapping_palette import derive_mapping_palette
from server.services.import_review_store import ensure_review_state, review_count_snapshot
from server.services.import_status_contracts import (
    BudgetStateSnapshotFn,
    CanonicalizeColumnMappingFn,
    DeriveMappingPaletteFn,
    EnsureReviewStateFn,
    ExecutionHealthSnapshotFn,
    ImportStatusSession,
    LiveAgencyQueueDepthFn,
    QueuePositionForJobFn,
    ResolveImportStatusFn,
    ReviewCountSnapshotFn,
    RuntimeProfileFn,
    WorkflowPayloadFn,
)
from server.services.import_status_policy import (
    cached_agency_queue_depth,
    coerce_progress_int,
    live_agency_queue_depth,
    optional_int,
    status_poll_after_ms,
)
from server.services.import_status_resolver import resolve_import_status
from server.services.import_status_summary import build_import_status_summary
from server.services.import_ui_summary import derive_terminal_result_state

DEFAULT_ENSURE_REVIEW_STATE_FN = cast(EnsureReviewStateFn, ensure_review_state)
DEFAULT_REVIEW_COUNT_SNAPSHOT_FN = cast(ReviewCountSnapshotFn, review_count_snapshot)
DEFAULT_RESOLVE_IMPORT_STATUS_FN = cast(ResolveImportStatusFn, resolve_import_status)
DEFAULT_RUNTIME_PROFILE_FN = cast(RuntimeProfileFn, effective_import_runtime_profile)
DEFAULT_BUDGET_STATE_SNAPSHOT_FN = cast(
    BudgetStateSnapshotFn, tenant_resource_governor.budget_state_snapshot
)
DEFAULT_EXECUTION_HEALTH_SNAPSHOT_FN = cast(ExecutionHealthSnapshotFn, execution_health_snapshot)
DEFAULT_QUEUE_POSITION_FOR_JOB_FN = cast(QueuePositionForJobFn, queue_position_for_job)
DEFAULT_CANONICALIZE_COLUMN_MAPPING_FN = cast(
    CanonicalizeColumnMappingFn, canonicalize_column_mapping
)
DEFAULT_DERIVE_MAPPING_PALETTE_FN = cast(DeriveMappingPaletteFn, derive_mapping_palette)
DEFAULT_LIVE_AGENCY_QUEUE_DEPTH_FN = cast(LiveAgencyQueueDepthFn, live_agency_queue_depth)


def _dict_copy(value: object) -> dict[str, object]:
    return (
        {str(key): item for key, item in dict(value).items()} if isinstance(value, Mapping) else {}
    )


def _items(value: object) -> list[object]:
    return (
        list(value)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
        else []
    )


def build_import_status_payload(
    *,
    session: ImportStatusSession,
    agency_id: int,
    workflow_payload_fn: WorkflowPayloadFn,
    ensure_review_state_fn: EnsureReviewStateFn = DEFAULT_ENSURE_REVIEW_STATE_FN,
    review_count_snapshot_fn: ReviewCountSnapshotFn = DEFAULT_REVIEW_COUNT_SNAPSHOT_FN,
    resolve_import_status_fn: ResolveImportStatusFn = DEFAULT_RESOLVE_IMPORT_STATUS_FN,
    effective_import_runtime_profile_fn: RuntimeProfileFn = DEFAULT_RUNTIME_PROFILE_FN,
    budget_state_snapshot_fn: BudgetStateSnapshotFn = DEFAULT_BUDGET_STATE_SNAPSHOT_FN,
    execution_health_snapshot_fn: ExecutionHealthSnapshotFn = (
        DEFAULT_EXECUTION_HEALTH_SNAPSHOT_FN
    ),
    queue_position_for_job_fn: QueuePositionForJobFn = DEFAULT_QUEUE_POSITION_FOR_JOB_FN,
    canonicalize_column_mapping_fn: CanonicalizeColumnMappingFn = (
        DEFAULT_CANONICALIZE_COLUMN_MAPPING_FN
    ),
    derive_mapping_palette_fn: DeriveMappingPaletteFn = DEFAULT_DERIVE_MAPPING_PALETTE_FN,
    live_agency_queue_depth_fn: LiveAgencyQueueDepthFn = DEFAULT_LIVE_AGENCY_QUEUE_DEPTH_FN,
) -> dict[str, object]:
    result_summary = _dict_copy(session.result_summary)
    follow_up = normalize_follow_up_outcome(result_summary.get("follow_up"))
    result_summary["follow_up"] = follow_up
    summary = build_import_status_summary(
        session=session,
        result_summary=result_summary,
        ensure_review_state_fn=ensure_review_state_fn,
        review_count_snapshot_fn=review_count_snapshot_fn,
    )
    workflow = _dict_copy(workflow_payload_fn(session))
    profile = effective_import_runtime_profile_fn()
    execution_profile = str(workflow.get("execution_profile", profile.name) or profile.name)
    resolved_status = resolve_import_status_fn(
        session_status=str(session.status),
        session_stage=str(session.stage),
        progress=coerce_progress_int(session.progress, default=0),
        progress_detail=summary.progress_detail,
        result_summary=result_summary,
        review_visible_count=summary.review_rows_visible,
    )

    budget_remaining = 0
    if resolved_status.public_status in {"queued", "running"}:
        try:
            budget_snapshot = budget_state_snapshot_fn(
                agency_ids=[int(agency_id or 0)],
                budget_names=["import_execute"],
            )
            budgets = budget_snapshot.get("budgets")
            import_budget = budgets.get("import_execute", {}) if isinstance(budgets, dict) else {}
            agency_budget = (
                import_budget.get(str(int(agency_id or 0)), {})
                if isinstance(import_budget, dict)
                else {}
            )
            budget_remaining = (
                optional_int(agency_budget.get("tokens")) if isinstance(agency_budget, dict) else 0
            ) or 0
        except Exception:
            budget_remaining = 0

    created_count = coerce_progress_int(result_summary.get("created_count"), default=0)
    updated_count = coerce_progress_int(result_summary.get("updated_count"), default=0)
    skipped_count = coerce_progress_int(result_summary.get("skipped_count"), default=0)
    terminal_state = derive_terminal_result_state(
        status=resolved_status.public_status,
        row_count=summary.row_count,
        created_count=created_count,
        updated_count=updated_count,
        skipped_count=skipped_count,
        error_count=resolved_status.terminal_error_count,
        review_total_count=summary.review_total_count,
        overflow_blocking=resolved_status.overflow_blocking,
        explicit_terminal_reason=result_summary.get("terminal_reason"),
        explicit_zero_change_reasons=result_summary.get("result_zero_change_reasons"),
        explicit_unchanged_count=result_summary.get("unchanged_count"),
    )
    execution_health = _dict_copy(execution_health_snapshot_fn(session))
    decision_snapshot = _dict_copy(summary.inference_summary.get("import_decision"))
    decision_reason_codes = _items(decision_snapshot.get("reason_codes"))
    canonical_mapping = canonicalize_column_mapping_fn(
        column_mapping=dict(session.column_mapping or {}),
        detected_columns=summary.detected_columns,
        final_inference=summary.inferred,
    )
    palette = derive_mapping_palette_fn(
        final_inference=summary.inferred,
        detected_columns=summary.detected_columns,
        column_mapping=canonical_mapping,
        manual_mapping_required=bool(
            summary.inference_summary.get("manual_mapping_required", False)
        ),
        detected_entity=str(session.detected_entity or ""),
        sheet_profiles=summary.sheet_profiles,
        selected_sheet_name=str(summary.inference_summary.get("selected_sheet_name", "") or ""),
    )
    cached_queue_depth = cached_agency_queue_depth(workflow, str(session.status))
    zero_change_reasons = terminal_state.get("result_zero_change_reasons", [])

    return {
        "session_id": str(session.id),
        "task_id": session.task_id,
        "status": resolved_status.public_status,
        "stage": resolved_status.public_stage,
        "progress": (
            100
            if resolved_status.public_status in {"completed", "failed"}
            else coerce_progress_int(session.progress, default=0)
        ),
        "error_message": session.error_message,
        "created_count": created_count,
        "updated_count": updated_count,
        "skipped_count": skipped_count,
        "error_count": resolved_status.terminal_error_count,
        "result_zero_change": bool(terminal_state.get("result_zero_change", False)),
        "result_zero_change_reasons": (
            list(zero_change_reasons) if isinstance(zero_change_reasons, list) else []
        ),
        "terminal_reason": terminal_state.get("terminal_reason"),
        "detected_columns": session.detected_columns,
        "detected_entity": session.detected_entity,
        "column_mapping": dict(canonical_mapping),
        "row_count": summary.row_count,
        "review_count": summary.review_rows_visible,
        "review_overflow_count": summary.review_overflow_count,
        "review_total_count": summary.review_total_count,
        "review_pending_group_count": int(summary.review_snapshot.pending_group_count or 0),
        "review_mode": "groups",
        "review_state": summary.review_state,
        "overflow_blocking": resolved_status.overflow_blocking,
        "review_disabled": resolved_status.review_disabled,
        "review_disabled_reason": resolved_status.review_disabled_reason or None,
        "preview_rows": session.preview_rows,
        "last_result": result_summary,
        "follow_up": follow_up,
        "progress_detail": summary.progress_detail,
        "execution_profile": execution_profile,
        "queue_name": "imports",
        "tenant_budget_remaining": budget_remaining,
        "review_conflict_count": int(summary.review_snapshot.conflict_count or 0),
        "inference_summary": summary.inference_summary,
        "manual_mapping_required": bool(
            summary.inference_summary.get("manual_mapping_required", False)
        ),
        "manual_mapping_reasons": [
            str(item) for item in _items(summary.inference_summary.get("manual_mapping_reasons"))
        ],
        "sheet_profiles": _items(summary.inference_summary.get("sheet_profiles")),
        "column_semantic_profiles": _items(
            summary.inference_summary.get("column_semantic_profiles")
        ),
        "agency_profile_hints_used": _dict_copy(
            summary.inference_summary.get("agency_profile_hints_used")
        ),
        "price_dialect_summary": _dict_copy(summary.inference_summary.get("price_dialect_summary")),
        "preview_entity_counts": summary.preview_entity_counts,
        "preview_auto_fix_summary": summary.preview_auto_fix_summary,
        "preview_attention_summary": summary.preview_attention_summary,
        "result_entity_counts": summary.result_entity_counts,
        "result_auto_fix_summary": summary.result_auto_fix_summary,
        "result_attention_summary": summary.result_attention_summary,
        "queue_position": queue_position_for_job_fn(session),
        "agency_queue_depth": (
            cached_queue_depth
            if cached_queue_depth is not None
            else live_agency_queue_depth_fn(
                agency_id=agency_id,
                session_status=str(session.status),
            )
        ),
        "cancellation_state": (
            "cancelled"
            if str(terminal_state.get("terminal_reason") or "") == "cancelled"
            else (
                "cancel_requested"
                if bool(workflow.get("cancel_requested", False))
                else (
                    "cancelled"
                    if str(session.status) == "failed"
                    and resolved_status.public_status == "failed"
                    and session.error_message
                    and "cancelled" in str(session.error_message).lower()
                    else "active"
                )
            )
        ),
        "admission_mode": str(workflow.get("admission_mode", "normal") or "normal"),
        "pressure_reason": str(workflow.get("pressure_reason", "") or ""),
        "poll_after_ms": status_poll_after_ms(
            public_status=resolved_status.public_status,
            public_stage=resolved_status.public_stage,
            progress_detail=summary.progress_detail,
            row_count=summary.row_count,
        ),
        **{
            key: execution_health.get(key)
            for key in (
                "queued_at",
                "started_at",
                "last_phase_started_at",
                "last_phase_heartbeat_at",
                "wait_state",
                "wait_reason",
                "wait_seconds",
                "stalled",
                "stalled_reason",
                "can_cancel",
                "can_close",
                "repair_attempted",
                "repair_attempt_count",
                "repair_last_reason",
            )
        },
        "mapping_palette_mode": (
            decision_snapshot.get("mapping_palette_mode")
            or palette.get("mapping_palette_mode", "entity_only")
        ),
        "decision_outcome": decision_snapshot.get("outcome"),
        "decision_reason_codes": [str(value) for value in decision_reason_codes],
    }


__all__ = ["build_import_status_payload"]
