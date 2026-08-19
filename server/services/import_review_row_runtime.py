"""Review-row shaping and anchor helpers for importer planning and prepare flows."""

from __future__ import annotations

from typing import Any, cast

from server.services.import_diff_builder import has_immutable_conflict
from server.services.import_review_policy import (
    DECISION_OPTIONS,
    REVIEW_AMBIGUOUS,
    decision_policy_for_entity,
)
from server.services.import_types import (
    ReviewCandidatePayload,
    ReviewFieldDiffPayload,
    ReviewFieldPayload,
    ReviewRowPayload,
)


def anchor_map_keys(row_data: dict[str, Any]) -> list[str]:
    from server.services.duplicate_checker import _normalize_phone_for_dedup

    keys: list[str] = []
    phone = _normalize_phone_for_dedup(str(row_data.get("phone", "") or ""))
    if phone:
        keys.append(f"phone:{phone}")
    family_name = (
        str(row_data.get("family_name", "") or row_data.get("name", "") or "").strip().lower()
    )
    if family_name:
        keys.append(f"name:{family_name}")
    return keys


def remember_anchor(anchor_map: dict[str, int], row_data: dict[str, Any], entity_id: int) -> None:
    if entity_id <= 0:
        return
    for key in anchor_map_keys(row_data):
        anchor_map[key] = int(entity_id)


def normalized_review_fields(normalized: Any) -> list[ReviewFieldPayload]:
    return [
        {
            "field": rf.field_name,
            "original": rf.original_value,
            "normalized": rf.normalized_value,
            "confidence": rf.confidence,
            "remark": rf.remark,
            "metadata": dict(getattr(rf, "metadata", {}) or {}),
        }
        for rf in list(getattr(normalized, "review_fields", []) or [])
    ]


def review_row_from_resolution(
    *,
    row_num: int,
    row_data: dict[str, object],
    original: dict[str, object],
    entity_type: str,
    topology_side: str,
    resolution: Any,
    remarks: list[str] | None = None,
    review_fields: list[ReviewFieldPayload] | None = None,
    recoverability_class: str = "review_recoverable",
    recovered_fields: list[dict[str, object]] | None = None,
    recovery_candidates: list[dict[str, object]] | None = None,
    blocking_reasons: list[str] | None = None,
    learning_signal_eligible: bool = True,
) -> ReviewRowPayload:
    policy = decision_policy_for_entity(entity_type)
    candidate_matches = cast(
        list[ReviewCandidatePayload],
        list(getattr(resolution, "candidate_matches", []) or []),
    )
    suggested_existing_id = int(getattr(resolution, "suggested_existing_id", 0) or 0)
    selected_field_diff: ReviewFieldDiffPayload = next(
        (
            cast(
                ReviewFieldDiffPayload,
                dict(candidate.get("field_diff", {}) or {}),
            )
            for candidate in candidate_matches
            if int(candidate.get("id", 0) or 0) == suggested_existing_id
        ),
        cast(
            ReviewFieldDiffPayload,
            {"changed_mutable": [], "changed_immutable": [], "unchanged": []},
        ),
    )
    effective_remarks = list(remarks or [])
    if not effective_remarks and getattr(resolution, "suggested_reasons", None):
        effective_remarks = list(getattr(resolution, "suggested_reasons", []) or [])
    if not review_fields:
        review_fields = [
            {
                "field": "identity_resolution",
                "original": "",
                "normalized": "",
                "confidence": float(getattr(resolution, "suggested_confidence", 0.0) or 0.0),
                "remark": "; ".join(effective_remarks) if effective_remarks else "Review required",
            }
        ]
    return {
        "row": row_num,
        "data": row_data,
        "normalized_data": dict(row_data),
        "original": original,
        "raw_data": dict(original),
        "entity_type": entity_type,
        "topology_side": topology_side,
        "decision_options": list(DECISION_OPTIONS),
        "suggested_action": str(
            getattr(resolution, "suggested_action", REVIEW_AMBIGUOUS) or REVIEW_AMBIGUOUS
        ),
        "suggested_existing_id": suggested_existing_id,
        "suggested_confidence": float(getattr(resolution, "suggested_confidence", 0.0) or 0.0),
        "suggested_reasons": list(getattr(resolution, "suggested_reasons", []) or []),
        "candidate_matches": candidate_matches,
        "mutable_fields": list(policy.mutable_fields),
        "immutable_fields": list(policy.immutable_fields),
        "field_diff": selected_field_diff,
        "review_fields": review_fields,
        "remarks": effective_remarks,
        "inline_editable": True,
        "immutable_conflict": has_immutable_conflict(
            cast(dict[str, list[dict[str, Any]]], selected_field_diff)
        ),
        "recoverability_class": recoverability_class,
        "recovered_fields": list(recovered_fields or []),
        "recovery_candidates": list(recovery_candidates or []),
        "blocking_reasons": list(blocking_reasons or []),
        "learning_signal_eligible": bool(learning_signal_eligible),
    }


def manual_review_row(
    *,
    row_num: int,
    row_data: dict[str, object],
    original: dict[str, object],
    entity_type: str,
    topology_side: str,
    review_fields: list[ReviewFieldPayload],
    remarks: list[str],
    suggested_action: str = REVIEW_AMBIGUOUS,
    suggested_existing_id: int = 0,
    suggested_confidence: float = 0.0,
    suggested_reasons: list[str] | None = None,
    candidate_matches: list[ReviewCandidatePayload] | None = None,
    immutable_conflict: bool = False,
    recoverability_class: str = "review_recoverable",
    recovered_fields: list[dict[str, object]] | None = None,
    recovery_candidates: list[dict[str, object]] | None = None,
    blocking_reasons: list[str] | None = None,
    learning_signal_eligible: bool = True,
) -> ReviewRowPayload:
    policy = decision_policy_for_entity(entity_type)
    candidate_rows = list(candidate_matches or [])
    return {
        "row": row_num,
        "data": row_data,
        "normalized_data": dict(row_data),
        "original": original,
        "raw_data": dict(original),
        "entity_type": entity_type,
        "topology_side": topology_side,
        "decision_options": list(DECISION_OPTIONS),
        "suggested_action": suggested_action,
        "suggested_existing_id": int(suggested_existing_id or 0),
        "suggested_confidence": float(suggested_confidence or 0.0),
        "suggested_reasons": list(suggested_reasons or []),
        "candidate_matches": candidate_rows,
        "mutable_fields": list(policy.mutable_fields),
        "immutable_fields": list(policy.immutable_fields),
        "field_diff": {"changed_mutable": [], "changed_immutable": [], "unchanged": []},
        "review_fields": list(review_fields),
        "remarks": list(remarks),
        "inline_editable": True,
        "immutable_conflict": bool(immutable_conflict),
        "recoverability_class": recoverability_class,
        "recovered_fields": list(recovered_fields or []),
        "recovery_candidates": list(recovery_candidates or []),
        "blocking_reasons": list(blocking_reasons or []),
        "learning_signal_eligible": bool(learning_signal_eligible),
    }


__all__ = [
    "anchor_map_keys",
    "manual_review_row",
    "normalized_review_fields",
    "remember_anchor",
    "review_row_from_resolution",
]
