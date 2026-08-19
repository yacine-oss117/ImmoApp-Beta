"""Review row and audit payload shaping for importer review resolution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar, cast

from server.services.import_constants import normalize_entity_type
from server.services.import_types import (
    ReviewAuditEntryPayload,
    ReviewCandidatePayload,
    ReviewFieldDiffPayload,
    ReviewFieldPayload,
    ReviewRowPayload,
)

_MappingValue = TypeVar("_MappingValue")


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


def _coerce_float(value: object, *, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _list_of_objects(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _dict_of_objects(value: object) -> dict[str, object]:
    return cast(dict[str, object], dict(value)) if isinstance(value, dict) else {}


def build_review_row(
    *,
    row_num: int,
    row_data: dict[str, object],
    original: dict[str, object],
    review_fields: list[ReviewFieldPayload],
    remarks: list[str],
    candidate_matches: list[ReviewCandidatePayload] | None = None,
) -> ReviewRowPayload:
    review_row: ReviewRowPayload = {
        "row": row_num,
        "data": row_data,
        "original": original,
        "review_fields": review_fields,
        "remarks": remarks,
    }
    if candidate_matches:
        review_row["candidate_matches"] = candidate_matches
    return review_row


def review_entry_metadata(review_entry: Mapping[str, object]) -> dict[str, object]:
    return {
        "suggested_action": str(review_entry.get("suggested_action", "") or ""),
        "suggested_existing_id": _coerce_int(review_entry.get("suggested_existing_id", 0)),
        "suggested_confidence": _coerce_float(review_entry.get("suggested_confidence", 0.0)),
        "suggested_reasons": _list_of_objects(review_entry.get("suggested_reasons", [])),
        "recoverability_class": str(
            review_entry.get("recoverability_class", "review_recoverable") or "review_recoverable"
        ),
        "recovered_fields": _list_of_objects(review_entry.get("recovered_fields", [])),
        "recovery_candidates": _list_of_objects(review_entry.get("recovery_candidates", [])),
        "blocking_reasons": _list_of_objects(review_entry.get("blocking_reasons", [])),
        "learning_signal_eligible": bool(review_entry.get("learning_signal_eligible", True)),
    }


def review_candidate_matches(review_entry: Mapping[str, object]) -> list[ReviewCandidatePayload]:
    return [
        cast(ReviewCandidatePayload, dict(candidate))
        for candidate in _list_of_objects(review_entry.get("candidate_matches"))
        if isinstance(candidate, dict)
    ]


def _selected_candidate_snapshot(
    candidate_matches: list[ReviewCandidatePayload],
    *,
    existing_id: int,
) -> ReviewCandidatePayload:
    for candidate in candidate_matches:
        if _coerce_int(candidate.get("id", 0)) == existing_id:
            return cast(ReviewCandidatePayload, dict(candidate))
    return cast(ReviewCandidatePayload, {})


def normalize_review_key_token(value: object) -> str:
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (int, float)):
        return str(int(value))
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text.isdigit():
        return str(int(text))
    return text


def review_row_key(*, row_num: int, entity_type: str) -> str:
    if not str(entity_type or "").strip():
        return str(int(row_num))
    normalized_entity_type = normalize_entity_type(entity_type)
    if normalized_entity_type:
        return f"{int(row_num)}:{normalized_entity_type}"
    return str(int(row_num))


def review_row_lookup_keys(*, row_num: int, entity_type: str) -> tuple[str, ...]:
    composite_key = review_row_key(row_num=row_num, entity_type=entity_type)
    plain_key = str(int(row_num))
    if composite_key == plain_key:
        return (plain_key,)
    return (composite_key, plain_key)


def review_row_key_from_payload(row: Mapping[str, object]) -> str:
    return review_row_key(
        row_num=_coerce_int(row.get("row", 0)),
        entity_type=str(row.get("entity_type", "") or ""),
    )


def promote_plain_row_mapping_keys(
    *,
    values: Mapping[str, _MappingValue],
    plain_row_lookup: Mapping[str, list[str]],
) -> dict[str, _MappingValue]:
    promoted: dict[str, _MappingValue] = {}
    for raw_key, value in values.items():
        normalized_key = normalize_review_key_token(raw_key)
        if not normalized_key:
            continue
        composite_keys = plain_row_lookup.get(normalized_key, [])
        target_key = composite_keys[0] if len(composite_keys) == 1 else normalized_key
        promoted[target_key] = value
    return promoted


def promote_plain_skip_row_tokens(
    *,
    values: list[object],
    plain_row_lookup: Mapping[str, list[str]],
) -> list[str]:
    promoted: list[str] = []
    for raw_value in values:
        normalized_value = normalize_review_key_token(raw_value)
        if not normalized_value:
            continue
        composite_keys = plain_row_lookup.get(normalized_value, [])
        promoted.append(composite_keys[0] if len(composite_keys) == 1 else normalized_value)
    return promoted


def build_review_audit_entry(
    *,
    row_num: int,
    entity_type: str,
    action: str,
    validated_row: dict[str, object],
    review_entry: Mapping[str, object],
    existing_id: int = 0,
    row_version: int = 0,
    before_payload: dict[str, object] | None = None,
    diff_payload: dict[str, object] | None = None,
    correction_payload: dict[str, object] | None = None,
) -> ReviewAuditEntryPayload:
    candidate_matches = review_candidate_matches(review_entry)
    selected_candidate = _selected_candidate_snapshot(
        existing_id=existing_id,
        candidate_matches=candidate_matches,
    )
    return {
        "row": row_num,
        "entity_type": entity_type,
        "action": action,
        "target_table": f"{entity_type}s" if entity_type else "",
        "existing_id": existing_id,
        "row_version": row_version,
        "suggested_action": str(review_entry.get("suggested_action", "") or ""),
        "suggested_existing_id": _coerce_int(review_entry.get("suggested_existing_id", 0)),
        "suggested_confidence": _coerce_float(review_entry.get("suggested_confidence", 0.0)),
        "suggested_reasons": _list_of_objects(review_entry.get("suggested_reasons", [])),
        "payload": dict(validated_row),
        "before_payload": _dict_of_objects(
            before_payload or selected_candidate.get("snapshot", {}) or {}
        ),
        "diff_payload": _dict_of_objects(
            diff_payload or selected_candidate.get("field_diff", {}) or {}
        ),
        "correction_payload": dict(correction_payload or {}),
        "candidate_count": len(candidate_matches),
        "selected_candidate": selected_candidate,
        "selected_field_diffs": _list_of_objects(selected_candidate.get("field_diffs", [])),
        "remarks": _list_of_objects(review_entry.get("remarks", [])),
    }


__all__ = [
    "ReviewAuditEntryPayload",
    "ReviewCandidatePayload",
    "ReviewFieldDiffPayload",
    "ReviewFieldPayload",
    "ReviewRowPayload",
    "build_review_audit_entry",
    "build_review_row",
    "normalize_review_key_token",
    "promote_plain_row_mapping_keys",
    "promote_plain_skip_row_tokens",
    "review_candidate_matches",
    "review_entry_metadata",
    "review_row_key",
    "review_row_key_from_payload",
    "review_row_lookup_keys",
]
