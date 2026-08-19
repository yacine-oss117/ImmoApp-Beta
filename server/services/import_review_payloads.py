"""Shared payload shaping helpers for importer review flows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from rest_framework.request import Request

from server.imports.models import ImportJob, ImportReviewItem
from server.services.import_parsers import normalize_import_entity_type
from server.services.import_review_shapes import (
    normalize_review_key_token,
    promote_plain_row_mapping_keys,
    promote_plain_skip_row_tokens,
    review_row_key_from_payload,
)
from server.services.import_types import (
    ReviewGroupPayload,
    ReviewPagePayload,
    ReviewResolutionPayload,
    ReviewRowPayload,
)
from server.services.import_ui_summary import (
    review_overflow_count_for_payload,
    review_state_for_payload,
    review_total_count_for_payload,
    summarize_result_state,
)
from server.services.json_safe import json_safe_value

if TYPE_CHECKING:
    from server.services.import_review_conflicts import RowConflict


class ReviewCountSnapshotLike(Protocol):
    @property
    def visible_review_count(self) -> int: ...

    @property
    def pending_group_count(self) -> int: ...


@dataclass(frozen=True)
class NormalizedReviewSubmitRequest:
    corrections: dict[str, dict[str, object]]
    decisions: dict[str, ReviewResolutionPayload]
    item_decisions: dict[str, ReviewResolutionPayload]
    group_decisions: dict[str, ReviewResolutionPayload]
    skip_rows: list[str]
    skip_item_ids: list[int]
    bulk_operations: list[dict[str, object]]


@dataclass(frozen=True)
class PreparedReviewSubmitPayload:
    corrections: dict[str, dict[str, object]]
    decisions: dict[str, ReviewResolutionPayload]
    skip_rows: list[str]
    pending_rows: list[ReviewRowPayload]


def allowed_review_entity_types(job: ImportJob) -> set[str]:
    inference = dict((job.inference_summary or {}).get("final_inference", {}) or {})
    bundle_mode = str(inference.get("bundle_mode", "single_entity") or "single_entity")
    topology_side = str(inference.get("topology_side_hint", "unknown") or "unknown")
    if bundle_mode == "same_side_bundle":
        if topology_side == "client_side":
            return {"client", "demande"}
        if topology_side == "listing_side":
            return {"listing", "offer"}
    detected = normalize_import_entity_type(job.detected_entity)
    return {detected} if detected else set()


def query_int_param(request: Request, key: str, default: int) -> int:
    raw_value = request.query_params.get(key)
    if raw_value in {None, ""}:
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def query_bool_param(request: Request, key: str, default: bool) -> bool:
    raw_value = str(request.query_params.get(key, "") or "").strip().lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_submit_action(action: object) -> str:
    normalized = str(action or "").strip().lower()
    return {
        "create": "create_new",
        "update": "update_existing",
        "review": "review_ambiguous",
    }.get(normalized, normalized)


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _coerce_int(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _validate_decision_entity_types(
    *,
    allowed_entity_types: set[str],
    decision_map: dict[str, ReviewResolutionPayload],
    label: str,
) -> str | None:
    for key, raw_decision in decision_map.items():
        explicit_entity_type = raw_decision.get("entity_type")
        if explicit_entity_type in {None, ""}:
            continue
        normalized_entity_type = normalize_import_entity_type(str(explicit_entity_type))
        if normalized_entity_type not in allowed_entity_types:
            return f"{label} {key}: entity_type must stay within the allowed import bundle."
        raw_decision["entity_type"] = normalized_entity_type
    return None


def _row_decision_payload(decision: Mapping[str, object]) -> ReviewResolutionPayload:
    payload: ReviewResolutionPayload = {
        "action": _normalize_submit_action(decision.get("action", ""))
    }
    if decision.get("entity_type"):
        payload["entity_type"] = str(decision.get("entity_type") or "")
    if decision.get("existing_id") not in {None, ""}:
        payload["existing_id"] = _coerce_int(decision.get("existing_id", 0))
    if decision.get("row_version") not in {None, ""}:
        payload["row_version"] = _coerce_int(decision.get("row_version", 0))
    corrections = _as_dict(decision.get("corrections", {}))
    if corrections:
        payload["corrections"] = corrections
    return payload


def extra_row_metadata(row: Mapping[str, object]) -> dict[str, object]:
    explicit_keys = {
        "row",
        "data",
        "normalized_data",
        "original",
        "raw_data",
        "entity_type",
        "topology_side",
        "suggested_action",
        "suggested_existing_id",
        "suggested_confidence",
        "candidate_matches",
        "review_fields",
        "recovered_fields",
        "recovery_candidates",
        "blocking_reasons",
        "quick_fix_actions",
        "bulk_fix_groups",
        "inline_editable",
        "immutable_conflict",
        "recoverability_class",
        "issue_group",
        "issue_title",
        "issue_summary",
    }
    return {
        str(key): json_safe_value(value)
        for key, value in row.items()
        if str(key) not in explicit_keys
    }


def normalize_resolution_action(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return {
        "create": "create_new",
        "create_new": "create_new",
        "update": "update_existing",
        "update_existing": "update_existing",
        "review": "review_ambiguous",
        "review_ambiguous": "review_ambiguous",
        "skip": "skip",
    }.get(normalized, normalized)


def item_can_follow_group_resolution(
    row: Mapping[str, object],
    *,
    group_payload: Mapping[str, object],
) -> bool:
    if not bool(group_payload.get("apply_to_all_allowed", False)):
        return False
    if bool(_as_list(row.get("blocking_reasons", []))) or bool(
        row.get("immutable_conflict", False)
    ):
        return False
    row_entity_type = str(row.get("entity_type", "") or "").strip().lower()
    group_entity_type = str(group_payload.get("entity_type", "") or "").strip().lower()
    if row_entity_type == group_entity_type:
        return True
    if row_entity_type not in {"demande", "offer"}:
        return False
    if bool(_as_list(row.get("candidate_matches", []))):
        return False
    return str(row.get("issue_group", "") or "").strip().lower() == "parent_match_needed"


def group_resolution_blockers(
    row: Mapping[str, object],
    *,
    group_payload: Mapping[str, object],
) -> list[str]:
    if item_can_follow_group_resolution(row, group_payload=group_payload):
        return []
    blocking_reasons = _as_list(row.get("blocking_reasons", []))
    if blocking_reasons:
        return [str(reason) for reason in blocking_reasons if str(reason).strip()]
    if bool(row.get("immutable_conflict", False)):
        return ["immutable_conflict"]
    if bool(_as_list(row.get("candidate_matches", []))):
        return ["child_local_review"]
    row_entity_type = str(row.get("entity_type", "") or "").strip().lower()
    group_entity_type = str(group_payload.get("entity_type", "") or "").strip().lower()
    if row_entity_type != group_entity_type:
        return ["root_group_decision_not_enough"]
    return ["group_resolution_not_allowed"]


def _group_effective_resolution(item: ImportReviewItem) -> ReviewResolutionPayload:
    if not bool(item.group_resolvable):
        return {}
    resolution_scope = str(
        (item.group.metadata or {}).get("resolution_scope", "apply_to_all_pending_items")
        or "apply_to_all_pending_items"
    ).strip()
    if resolution_scope != "apply_to_all_pending_items":
        return {}
    group_resolution = dict(item.group.resolution_template or {})
    action = normalize_resolution_action(group_resolution.get("action", ""))
    if action not in {"create_new", "update_existing", "skip"}:
        return {}
    entity_type = str(item.entity_type or "").strip().lower()
    group_entity_type = str(item.group.entity_type or "").strip().lower()
    if action == "skip":
        return {"action": "skip", "entity_type": entity_type}
    if entity_type == group_entity_type:
        payload = cast(ReviewResolutionPayload, dict(group_resolution))
        payload["action"] = action
        payload["entity_type"] = entity_type
        return payload

    suggested_action = normalize_resolution_action(item.suggested_action)
    if suggested_action == "update_existing" and int(item.suggested_existing_id or 0) > 0:
        return {
            "action": "update_existing",
            "entity_type": entity_type,
            "existing_id": int(item.suggested_existing_id or 0),
        }
    if suggested_action == "skip":
        return {"action": "skip", "entity_type": entity_type}
    if suggested_action in {"", "create_new"} and not bool(
        list(item.candidate_matches or []) or []
    ):
        return {"action": "create_new", "entity_type": entity_type}
    return {}


def effective_resolution_payload(item: ImportReviewItem) -> ReviewResolutionPayload:
    explicit_resolution = cast(ReviewResolutionPayload, dict(item.resolution or {}))
    if explicit_resolution and str(item.resolution_source or "") == "item":
        explicit_resolution["action"] = normalize_resolution_action(
            explicit_resolution.get("action", "")
        )
        explicit_resolution.setdefault("entity_type", str(item.entity_type or ""))
        return explicit_resolution
    derived_resolution = _group_effective_resolution(item)
    if derived_resolution:
        return derived_resolution
    if explicit_resolution:
        explicit_resolution["action"] = normalize_resolution_action(
            explicit_resolution.get("action", "")
        )
        explicit_resolution.setdefault("entity_type", str(item.entity_type or ""))
        return explicit_resolution
    return {}


def normalize_review_submit_request(
    *,
    data: Mapping[str, object],
    allowed_entity_types: set[str],
) -> tuple[NormalizedReviewSubmitRequest | None, str | None]:
    normalized_decisions = {
        str(key): _row_decision_payload(_as_dict(value))
        for key, value in _as_dict(data.get("decisions", {})).items()
        if isinstance(value, dict)
    }
    validation_error = _validate_decision_entity_types(
        allowed_entity_types=allowed_entity_types,
        decision_map=normalized_decisions,
        label="Row",
    )
    if validation_error:
        return None, validation_error

    normalized_item_decisions = {
        str(key): _row_decision_payload(_as_dict(value))
        for key, value in _as_dict(data.get("item_decisions", {})).items()
        if isinstance(value, dict)
    }
    validation_error = _validate_decision_entity_types(
        allowed_entity_types=allowed_entity_types,
        decision_map=normalized_item_decisions,
        label="Item",
    )
    if validation_error:
        return None, validation_error

    normalized_group_decisions = {
        str(key): _row_decision_payload(_as_dict(value))
        for key, value in _as_dict(data.get("group_decisions", {})).items()
        if isinstance(value, dict)
    }
    validation_error = _validate_decision_entity_types(
        allowed_entity_types=allowed_entity_types,
        decision_map=normalized_group_decisions,
        label="Group",
    )
    if validation_error:
        return None, validation_error

    corrections = {
        str(key): _as_dict(value)
        for key, value in _as_dict(data.get("corrections", {})).items()
        if isinstance(value, dict)
    }
    raw_skip_rows = data.get("skip_rows", [])
    skip_rows = (
        [token for token in (normalize_review_key_token(value) for value in raw_skip_rows) if token]
        if isinstance(raw_skip_rows, list)
        else []
    )
    skip_item_ids = [_coerce_int(value) for value in _as_list(data.get("skip_item_ids", []))]
    bulk_operations = [
        dict(value)
        for value in _as_list(data.get("bulk_operations", []))
        if isinstance(value, dict)
    ]
    return (
        NormalizedReviewSubmitRequest(
            corrections=corrections,
            decisions=normalized_decisions,
            item_decisions=normalized_item_decisions,
            group_decisions=normalized_group_decisions,
            skip_rows=skip_rows,
            skip_item_ids=skip_item_ids,
            bulk_operations=bulk_operations,
        ),
        None,
    )


def merge_review_submit_payloads(
    *,
    request_payload: NormalizedReviewSubmitRequest,
    stored_corrections: Mapping[str, dict[str, object]],
    stored_decisions: Mapping[str, ReviewResolutionPayload],
    stored_skip_rows: list[str],
) -> NormalizedReviewSubmitRequest:
    merged_corrections = dict(stored_corrections)
    merged_corrections.update(request_payload.corrections)
    merged_decisions = dict(stored_decisions)
    merged_decisions.update(request_payload.decisions)
    merged_skip_rows = sorted(
        {
            str(value)
            for value in [*request_payload.skip_rows, *stored_skip_rows]
            if str(value).strip()
        }
    )
    return NormalizedReviewSubmitRequest(
        corrections=merged_corrections,
        decisions=merged_decisions,
        item_decisions=dict(request_payload.item_decisions),
        group_decisions=dict(request_payload.group_decisions),
        skip_rows=merged_skip_rows,
        skip_item_ids=list(request_payload.skip_item_ids),
        bulk_operations=list(request_payload.bulk_operations),
    )


def prepare_effective_review_submit_payload(
    *,
    pending_rows: list[ReviewRowPayload],
    corrections: Mapping[str, dict[str, object]],
    decisions: Mapping[str, ReviewResolutionPayload],
    skip_rows: list[str],
    bulk_operations: list[dict[str, object]],
) -> PreparedReviewSubmitPayload:
    from server.services.import_review_rescue import expand_bulk_operations

    pending_rows_by_key = {
        review_row_key_from_payload(row): row
        for row in pending_rows
        if review_row_key_from_payload(row)
    }
    plain_row_lookup: dict[str, list[str]] = {}
    for row_key, row_payload in pending_rows_by_key.items():
        plain_row_key = str(int(row_payload.get("row", 0) or 0))
        plain_row_lookup.setdefault(plain_row_key, []).append(row_key)

    promoted_corrections = promote_plain_row_mapping_keys(
        values=corrections,
        plain_row_lookup=plain_row_lookup,
    )
    promoted_decisions = promote_plain_row_mapping_keys(
        values=decisions,
        plain_row_lookup=plain_row_lookup,
    )
    promoted_skip_rows = promote_plain_skip_row_tokens(
        values=[str(value) for value in skip_rows],
        plain_row_lookup=plain_row_lookup,
    )
    addressed_rows = {
        token
        for token in (normalize_review_key_token(value) for value in promoted_skip_rows)
        if token
    }
    addressed_rows.update(
        token
        for token in (normalize_review_key_token(key) for key in promoted_decisions.keys())
        if token
    )
    for row_key, row_payload in pending_rows_by_key.items():
        plain_row_key = str(int(row_payload.get("row", 0) or 0))
        if row_key in addressed_rows or plain_row_key in addressed_rows:
            continue
        promoted_decisions[str(row_key)] = {"action": "review_ambiguous"}

    expanded_corrections = expand_bulk_operations(
        review_rows=pending_rows,
        corrections=promoted_corrections,
        bulk_operations=bulk_operations,
    )
    return PreparedReviewSubmitPayload(
        corrections=expanded_corrections,
        decisions=promoted_decisions,
        skip_rows=sorted({str(value) for value in promoted_skip_rows if str(value).strip()}),
        pending_rows=pending_rows,
    )


def build_import_review_response(
    *,
    job: ImportJob,
    snapshot: ReviewCountSnapshotLike,
    review_groups: list[ReviewGroupPayload],
    review_page: ReviewPagePayload,
    review_items: list[ReviewRowPayload],
    review_rows: list[ReviewRowPayload],
    review_mode: str,
    selected_group_key: str | None,
    issue_group: str | None,
    search: str,
    pending_only: bool,
) -> dict[str, object]:
    review_overflow_count = review_overflow_count_for_payload(
        progress_detail=job.progress_detail or {},
        result_summary=job.result_summary or {},
    )
    review_state = review_state_for_payload(
        progress_detail=job.progress_detail or {},
        result_summary=job.result_summary or {},
    )
    overflow_blocking = bool(
        (job.result_summary or {}).get("overflow_blocking", False)
        or (job.progress_detail or {}).get("overflow_blocking", False)
        or review_state == "emergency_overflow"
    )
    review_disabled = bool(
        (job.result_summary or {}).get("review_disabled", False)
        or (job.progress_detail or {}).get("review_disabled", False)
        or overflow_blocking
    )
    review_disabled_reason = str(
        (job.result_summary or {}).get("review_disabled_reason", "")
        or (job.progress_detail or {}).get("review_disabled_reason", "")
        or (
            "This import produced more unresolved review items than the system can safely process in one job."
            if overflow_blocking
            else ""
        )
        or ""
    )
    review_total_count = review_total_count_for_payload(
        visible_review_count=int(snapshot.visible_review_count or 0),
        progress_detail=job.progress_detail or {},
        result_summary=job.result_summary or {},
    )
    (
        result_entity_counts_payload,
        result_auto_fix_summary_payload,
        result_attention_summary_payload,
    ) = summarize_result_state(
        result_summary=job.result_summary,
        review_rows=review_rows,
    )
    resolved_mode = review_mode if review_mode in {"groups", "items"} else "groups"
    return {
        "session_id": str(job.id),
        "status": str(job.status),
        "stage": str(job.stage),
        "review_count": int(snapshot.visible_review_count or 0),
        "review_overflow_count": review_overflow_count,
        "review_total_count": review_total_count,
        "review_pending_group_count": int(snapshot.pending_group_count or 0),
        "review_mode": resolved_mode,
        "review_state": review_state,
        "overflow_blocking": overflow_blocking,
        "review_disabled": review_disabled,
        "review_disabled_reason": review_disabled_reason or None,
        "group_apply_supported": any(
            bool(group.get("apply_to_all_allowed", False)) for group in review_groups
        ),
        "review_page": review_page,
        "review_filters": {
            "mode": resolved_mode,
            "group_key": selected_group_key or None,
            "issue_group": issue_group,
            "search": search,
            "pending_only": pending_only,
        },
        "review_groups": review_groups,
        "review_items": review_items,
        "review_rows": review_rows,
        "result_summary": job.result_summary,
        "review_submit_conflict": _as_dict(
            (job.result_summary or {}).get("review_submit_conflict")
        ),
        "review_submit_error": _as_dict((job.result_summary or {}).get("review_submit_error")),
        "result_entity_counts": result_entity_counts_payload,
        "result_auto_fix_summary": result_auto_fix_summary_payload,
        "result_attention_summary": result_attention_summary_payload,
    }


def build_review_capacity_exceeded_response(
    *,
    job: ImportJob,
    review_state: str,
) -> dict[str, object]:
    detail = "This import produced more unresolved review items than the system can safely process in one job."
    return {
        "code": "IMPORT_REVIEW_CAPACITY_EXCEEDED",
        "detail": detail,
        "session_id": str(job.id),
        "review_state": review_state,
        "overflow_blocking": True,
        "review_disabled": True,
        "review_disabled_reason": detail,
    }


def build_review_duplicate_conflict_response(
    *,
    job: ImportJob,
    detail: str,
    row_conflicts: list[RowConflict],
    conflict_groups: list[str],
    conflict_item_ids: list[int],
    correlation_id: str,
    snapshot: ReviewCountSnapshotLike,
    review_state: str,
) -> dict[str, object]:
    return {
        "code": "IMPORT_REVIEW_DUPLICATE_CONFLICT",
        "detail": detail,
        "row_conflicts": row_conflicts,
        "conflict_groups": sorted(set(conflict_groups)),
        "conflict_item_ids": sorted(set(conflict_item_ids)),
        "correlation_id": correlation_id,
        "session_id": str(job.id),
        "review_count": int(snapshot.visible_review_count or 0),
        "review_state": review_state,
        "overflow_blocking": False,
        "review_disabled": False,
        "review_disabled_reason": "",
    }


def build_review_submit_accepted_response(
    *,
    job: ImportJob,
    task_id: str,
    snapshot: ReviewCountSnapshotLike,
    poll_after_ms: int,
) -> dict[str, object]:
    review_state = review_state_for_payload(
        progress_detail=job.progress_detail or {},
        result_summary=job.result_summary or {},
    )
    overflow_blocking = bool(
        (job.result_summary or {}).get("overflow_blocking", False)
        or (job.progress_detail or {}).get("overflow_blocking", False)
        or review_state == "emergency_overflow"
    )
    review_disabled = bool(
        (job.result_summary or {}).get("review_disabled", False)
        or (job.progress_detail or {}).get("review_disabled", False)
        or overflow_blocking
    )
    review_disabled_reason = str(
        (job.result_summary or {}).get("review_disabled_reason", "")
        or (job.progress_detail or {}).get("review_disabled_reason", "")
        or (
            "This import produced more unresolved review items than the system can safely process in one job."
            if overflow_blocking
            else ""
        )
        or ""
    )
    return {
        "request_status": "accepted",
        "session_id": str(job.id),
        "task_id": str(task_id or ""),
        "status": str(job.status),
        "job_status": str(job.status),
        "stage": str(job.stage),
        "review_count": int(snapshot.visible_review_count or 0),
        "review_pending_group_count": int(snapshot.pending_group_count or 0),
        "review_overflow_count": review_overflow_count_for_payload(
            result_summary=job.result_summary or {},
            progress_detail=job.progress_detail or {},
        ),
        "review_total_count": review_total_count_for_payload(
            visible_review_count=int(snapshot.visible_review_count or 0),
            result_summary=job.result_summary or {},
            progress_detail=job.progress_detail or {},
        ),
        "review_state": review_state,
        "overflow_blocking": overflow_blocking,
        "review_disabled": review_disabled,
        "review_disabled_reason": review_disabled_reason or "",
        "result_summary": dict(job.result_summary or {}),
        "poll_after_ms": int(poll_after_ms or 0),
    }


def build_review_submit_success_response(
    *,
    job: ImportJob,
    summary: Mapping[str, object],
    review_result: Mapping[str, object],
    created_count: int,
    created_entity_counts: Mapping[str, int],
    updated_count: int,
    review_pending_group_count: int,
    still_review_count: int,
    review_overflow_count: int,
    review_total_count: int,
    error_count: int,
    errors: list[dict[str, object]],
    still_review: list[ReviewRowPayload],
    review_groups: list[ReviewGroupPayload],
    review_items: list[ReviewRowPayload],
    result_entity_counts: Mapping[str, int],
    result_auto_fix_summary: Mapping[str, object],
    result_attention_summary: Mapping[str, object],
    overflow_blocking: bool,
) -> dict[str, object]:
    return {
        "request_status": "ok",
        "status": job.status,
        "session_id": str(job.id),
        "job_status": job.status,
        "stage": job.stage,
        "decision_summary": _as_dict(review_result.get("decision_summary", {})),
        "audit_ready": True,
        "learning_summary": _as_dict(review_result.get("learning_summary", {})),
        "dead_letter_summary": _as_dict(review_result.get("dead_letter_summary", {})),
        "created_count": created_count,
        "created_entity_counts": dict(created_entity_counts),
        "updated_count": updated_count,
        "review_remaining": still_review_count + review_overflow_count,
        "review_pending_group_count": review_pending_group_count,
        "still_review_count": still_review_count,
        "review_overflow_count": review_overflow_count,
        "review_total_count": review_total_count,
        "error_count": error_count,
        "errors": errors,
        "still_review": still_review,
        "review_groups": review_groups,
        "review_items": review_items,
        "result_summary": dict(summary),
        "result_entity_counts": dict(result_entity_counts),
        "result_auto_fix_summary": dict(result_auto_fix_summary),
        "result_attention_summary": dict(result_attention_summary),
        "review_history_count": _coerce_int(summary.get("review_history_count", 0)),
        "conflict_groups": [],
        "conflict_item_ids": [],
        "review_state": str(summary.get("review_state", "normal") or "normal"),
        "overflow_blocking": overflow_blocking,
        "review_disabled": overflow_blocking,
        "review_disabled_reason": str(summary.get("review_disabled_reason", "") or ""),
    }


__all__ = [
    "NormalizedReviewSubmitRequest",
    "PreparedReviewSubmitPayload",
    "allowed_review_entity_types",
    "query_bool_param",
    "query_int_param",
    "effective_resolution_payload",
    "extra_row_metadata",
    "group_resolution_blockers",
    "item_can_follow_group_resolution",
    "normalize_resolution_action",
    "normalize_review_submit_request",
    "merge_review_submit_payloads",
    "prepare_effective_review_submit_payload",
    "build_import_review_response",
    "build_review_capacity_exceeded_response",
    "build_review_duplicate_conflict_response",
    "build_review_submit_accepted_response",
    "build_review_submit_success_response",
]
