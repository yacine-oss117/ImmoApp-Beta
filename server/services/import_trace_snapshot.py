"""Stable importer trace snapshots for fixture-driven pipeline tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from server.services.import_mapping_palette import derive_mapping_palette


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[Any]:
    return (
        list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []
    )


def snapshot_mapping_step(*, controller_state: Mapping[str, object]) -> dict[str, Any]:
    state = _as_dict(controller_state)
    final_inference = {
        "bundle_mode": state.get("bundle_mode", "single_entity"),
        "topology_side_hint": state.get("topology_side_hint", "unknown"),
        "detected_entity": state.get("detected_entity", state.get("entity_hint", "")),
    }
    palette = derive_mapping_palette(
        final_inference=final_inference,
        detected_columns=_as_list(state.get("detected_columns")),
        column_mapping=_as_dict(state.get("column_mapping")),
        manual_mapping_required=bool(state.get("manual_mapping_required", False)),
        detected_entity=str(state.get("detected_entity", state.get("entity_hint", "")) or ""),
        sheet_profiles=_as_list(state.get("sheet_profiles")),
        selected_sheet_name=str(
            _as_dict(state.get("inference_summary")).get("selected_sheet_name", "") or ""
        ),
    )
    import_supported = bool(state.get("import_supported", True))
    blocking_message = str(state.get("blocking_message", "") or "").strip()
    continue_enabled = import_supported and not blocking_message
    return {
        "step_label": "Review your columns",
        "detected_entity": str(state.get("detected_entity", "") or ""),
        "manual_mapping_required": bool(state.get("manual_mapping_required", False)),
        "mapping_palette_mode": str(palette.get("mapping_palette_mode", "entity_only")),
        "mapping_palette_reason": str(palette.get("mapping_palette_reason", "")),
        "mapping_candidate_entities": [
            str(item) for item in _as_list(palette.get("mapping_candidate_entities"))
        ],
        "recoverable_by_manual_mapping": str(palette.get("mapping_palette_mode", "entity_only"))
        in {"same_side_union", "recovery_union"},
        "continue_enabled": continue_enabled,
        "allowed_actions": ["back", "continue"] if continue_enabled else ["back"],
    }


def snapshot_execution_step(*, status_payload: Mapping[str, object]) -> dict[str, Any]:
    payload = _as_dict(status_payload)
    wait_state = str(payload.get("wait_state", payload.get("status", "")) or "").strip().lower()
    cancellation_state = str(payload.get("cancellation_state", "") or "").strip().lower()
    stalled = bool(payload.get("stalled", False))
    allowed_actions: list[str] = []
    if bool(payload.get("can_close", True)):
        allowed_actions.append("close")
    if bool(payload.get("can_cancel", False)):
        allowed_actions.append("cancel")
    if stalled or str(payload.get("poll_state", "") or "").strip().lower() == "error":
        allowed_actions.append("retry_status")
    return {
        "step_label": "Prepare your import",
        "wait_state": wait_state,
        "stalled": stalled,
        "stalled_reason": str(payload.get("stalled_reason", "") or ""),
        "cancellation_state": cancellation_state or "active",
        "progress": int(payload.get("progress", 0) or 0),
        "allowed_actions": allowed_actions,
    }


def snapshot_summary_step(*, summary_state: Mapping[str, object]) -> dict[str, Any]:
    state = _as_dict(summary_state)
    status = str(state.get("status", "") or "").strip().lower()
    terminal_reason = str(state.get("terminal_reason", "") or "").strip().lower()
    result_zero_change = bool(
        state.get("result_zero_change", False) or terminal_reason == "zero_change"
    )
    if terminal_reason == "cancelled":
        tone = "error"
    elif result_zero_change:
        tone = "warning"
    elif terminal_reason in {"review_required", "emergency_overflow"}:
        tone = "attention"
    elif status == "completed":
        tone = "success"
    elif status == "failed" or terminal_reason == "failed":
        tone = "error"
    else:
        tone = "attention"
    return {
        "step_label": "Import summary",
        "status": status,
        "terminal_reason": terminal_reason,
        "result_zero_change": result_zero_change,
        "tone": tone,
        "auto_close": status == "completed" and tone == "success",
    }


def build_import_pipeline_trace(
    *,
    upload_response: Mapping[str, object] | None = None,
    parse_result: Mapping[str, object] | None = None,
    controller_state: Mapping[str, object] | None = None,
    preview_response: Mapping[str, object] | None = None,
    execute_response: Mapping[str, object] | None = None,
    status_payloads: Sequence[Mapping[str, object]] | None = None,
    review_response: Mapping[str, object] | None = None,
    summary_state: Mapping[str, object] | None = None,
    tab_handoff: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    trace: dict[str, Any] = {}
    if upload_response:
        upload = _as_dict(upload_response)
        trace["upload"] = {
            "session_id": str(upload.get("session_id", "") or ""),
            "filename": str(upload.get("filename", "") or ""),
        }
    if parse_result:
        parse = _as_dict(parse_result)
        trace["parse"] = {
            "detected_entity": str(parse.get("detected_entity", "") or ""),
            "bundle_mode": str(parse.get("bundle_mode", "single_entity") or "single_entity"),
            "topology_side_hint": str(parse.get("topology_side_hint", "unknown") or "unknown"),
            "row_count": int(parse.get("row_count", 0) or 0),
        }
    if controller_state:
        trace["mapping"] = snapshot_mapping_step(controller_state=controller_state)
    if preview_response:
        preview = _as_dict(preview_response)
        trace["preview"] = {
            "manual_mapping_required": bool(preview.get("manual_mapping_required", False)),
            "mapping_palette_mode": str(preview.get("mapping_palette_mode", "entity_only")),
            "mapping_candidate_entities": [
                str(item) for item in _as_list(preview.get("mapping_candidate_entities"))
            ],
            "entity_counts": _as_dict(preview.get("entity_counts")),
        }
    if execute_response:
        execute = _as_dict(execute_response)
        trace["execute"] = {
            "task_id": str(execute.get("task_id", "") or ""),
            "status": str(execute.get("status", "") or ""),
        }
    if status_payloads:
        trace["execution"] = [
            snapshot_execution_step(status_payload=_as_dict(payload)) for payload in status_payloads
        ]
    if review_response:
        review = _as_dict(review_response)
        trace["review"] = {
            "mode": str(review.get("review_mode", review.get("mode", "")) or ""),
            "review_total_count": int(review.get("review_total_count", 0) or 0),
            "overflow_blocking": bool(review.get("overflow_blocking", False)),
        }
    if summary_state:
        trace["summary"] = snapshot_summary_step(summary_state=summary_state)
    if tab_handoff:
        handoff = _as_dict(tab_handoff)
        trace["tab_handoff"] = {
            "target_tab": str(handoff.get("target_tab", "") or ""),
            "rows_visible": bool(handoff.get("rows_visible", False)),
            "banner_visible": bool(handoff.get("banner_visible", False)),
        }
    return trace


__all__ = [
    "build_import_pipeline_trace",
    "snapshot_execution_step",
    "snapshot_mapping_step",
    "snapshot_summary_step",
]
