"""Row-action collection stages for importer review resolution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Protocol, TypedDict, cast

from server.imports.models import ImportDeadLetterRow
from server.services.import_constants import (
    ENTITY_TYPE_CLIENT,
    ENTITY_TYPE_DEMANDE,
    ENTITY_TYPE_LISTING,
    ENTITY_TYPE_OFFER,
)
from server.services.import_dead_letter import build_dead_letter_row
from server.services.import_diff_builder import has_immutable_conflict
from server.services.import_review_conflicts import PendingCreateRow, load_job_field_price_metadata
from server.services.import_review_policy import CREATE_NEW, REVIEW_AMBIGUOUS, SKIP, UPDATE_EXISTING
from server.services.import_review_shapes import (
    ReviewAuditEntryPayload,
    build_review_audit_entry,
    build_review_row,
    normalize_review_key_token,
    review_candidate_matches,
    review_entry_metadata,
    review_row_lookup_keys,
)
from server.services.import_types import (
    ReviewCandidatePayload,
    ReviewFieldDiffPayload,
    ReviewFieldPayload,
    ReviewRowPayload,
)


class NormalizedReviewResult(Protocol):
    needs_review: bool
    data: dict[str, object]
    remarks: list[str]
    review_fields: list[NormalizedReviewField]
    recoverability_class: str
    recovered_fields: list[object]
    recovery_candidates: list[object]
    blocking_reasons: list[object]


class NormalizedReviewField(Protocol):
    field_name: str
    original_value: object
    normalized_value: object
    confidence: float
    remark: str
    metadata: dict[str, object]


class NormalizationPipelineProtocol(Protocol):
    def normalize_row(self, row_data: dict[str, object]) -> NormalizedReviewResult: ...


@dataclass(frozen=True)
class ReviewResolutionInputs:
    corrections_map: dict[str, dict[str, object]]
    decisions_map: dict[str, dict[str, object]]
    skip_rows_set: set[str]
    column_types: dict[str, str]
    field_price_metadata: dict[str, dict[str, object]]


class PendingUpdateRow(TypedDict):
    row_num: int
    entity_type: str
    validated_row: dict[str, object]
    existing_id: int
    row_version: int
    review_entry: ReviewRowPayload
    before_payload: dict[str, object]
    diff_payload: ReviewFieldDiffPayload
    correction_payload: dict[str, object]


class AppliedReviewRow(TypedDict):
    row_num: int
    action: str
    entity_type: str
    validated_row: dict[str, object]
    correction_payload: dict[str, object]
    review_entry: ReviewRowPayload


@dataclass
class ReviewResolutionState:
    create_pending_by_entity: dict[str, list[PendingCreateRow]] = dataclass_field(
        default_factory=dict
    )
    pending_updates: list[PendingUpdateRow] = dataclass_field(default_factory=list)
    still_review: list[ReviewRowPayload] = dataclass_field(default_factory=list)
    errors_list: list[dict[str, object]] = dataclass_field(default_factory=list)
    audit_entries: list[ReviewAuditEntryPayload] = dataclass_field(default_factory=list)
    applied_rows: list[AppliedReviewRow] = dataclass_field(default_factory=list)
    dead_letter_rows: list[object] = dataclass_field(default_factory=list)
    decision_summary: dict[str, int] = dataclass_field(
        default_factory=lambda: {
            CREATE_NEW: 0,
            UPDATE_EXISTING: 0,
            REVIEW_AMBIGUOUS: 0,
            SKIP: 0,
        }
    )


_PROTECTED_REVIEW_ROW_KEYS = frozenset(
    {
        "row",
        "data",
        "original",
        "review_fields",
        "remarks",
        "candidate_matches",
        "entity_type",
        "topology_side",
    }
)


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


def _as_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _review_entry_fields(review_entry: ReviewRowPayload) -> list[ReviewFieldPayload]:
    return [
        cast(ReviewFieldPayload, dict(item))
        for item in _as_list(review_entry.get("review_fields", []))
        if isinstance(item, dict)
    ]


def _review_entry_remarks(review_entry: ReviewRowPayload) -> list[str]:
    return [
        str(item) for item in _as_list(review_entry.get("remarks", [])) if str(item or "").strip()
    ]


def _normalized_review_fields(
    review_fields: list[NormalizedReviewField],
) -> list[ReviewFieldPayload]:
    return [
        {
            "field": field.field_name,
            "original": field.original_value,
            "normalized": field.normalized_value,
            "confidence": field.confidence,
            "remark": field.remark,
            "metadata": dict(field.metadata or {}),
        }
        for field in review_fields
    ]


def _still_review_row(
    *,
    row_num: int,
    row_data: dict[str, object],
    original: dict[str, object],
    review_fields: list[ReviewFieldPayload],
    remarks: list[str],
    candidate_matches: list[ReviewCandidatePayload],
    review_entry: ReviewRowPayload,
    entity_type: str,
    extra_fields: dict[str, object] | None = None,
) -> ReviewRowPayload:
    review_row = build_review_row(
        row_num=row_num,
        row_data=row_data,
        original=original,
        review_fields=review_fields,
        remarks=remarks,
        candidate_matches=candidate_matches,
    )
    metadata = review_entry_metadata(review_entry)
    metadata_overlap = sorted(_PROTECTED_REVIEW_ROW_KEYS & set(metadata))
    if metadata_overlap:
        raise ValueError(
            "review_entry_metadata returned protected review-row keys: "
            f"{', '.join(metadata_overlap)}"
        )
    extra_payload = dict(extra_fields or {})
    extra_overlap = sorted(_PROTECTED_REVIEW_ROW_KEYS & set(extra_payload))
    if extra_overlap:
        raise ValueError(
            "extra review-row fields overlap protected keys: " f"{', '.join(extra_overlap)}"
        )
    merged_review_row: dict[str, object] = dict(review_row)
    merged_review_row["entity_type"] = entity_type
    merged_review_row["topology_side"] = str(review_entry.get("topology_side", "") or "")
    merged_review_row.update(metadata)
    if extra_payload:
        merged_review_row.update(extra_payload)
    return cast(ReviewRowPayload, merged_review_row)


def normalize_resolution_inputs(
    *,
    corrections: Mapping[str, Mapping[str, object]] | None,
    decisions: Mapping[str, Mapping[str, object]] | None,
    skip_rows: list[int | str] | None,
    review_rows: list[ReviewRowPayload],
    job_id: str,
    agency_id: int,
) -> ReviewResolutionInputs:
    corrections_map = {
        normalize_review_key_token(key): dict(value or {})
        for key, value in (corrections or {}).items()
        if normalize_review_key_token(key)
    }
    decisions_map = {
        normalize_review_key_token(key): dict(value or {})
        for key, value in (decisions or {}).items()
        if normalize_review_key_token(key)
    }
    skip_rows_set = {
        token
        for token in (normalize_review_key_token(value) for value in (skip_rows or []))
        if token
    }
    column_types: dict[str, str] = {}
    field_price_metadata: dict[str, dict[str, object]] = {}
    for review_entry in review_rows:
        for review_field in _as_list(review_entry.get("review_fields", [])):
            if not isinstance(review_field, dict):
                continue
            field_name = str(review_field.get("field", "") or "").strip()
            metadata = _as_dict(review_field.get("metadata", {}))
            column_type = str(metadata.get("column_type", "") or "").strip()
            if field_name and column_type and field_name not in column_types:
                column_types[field_name] = column_type
            if field_name:
                field_price_metadata.setdefault(field_name, {}).update(
                    {
                        key: value
                        for key, value in metadata.items()
                        if key
                        in {
                            "source_header",
                            "price_dialect_hint",
                            "price_dialect_confidence",
                            "price_aliases",
                        }
                    }
                )
    for field_name, metadata in load_job_field_price_metadata(
        job_id=job_id,
        agency_id=agency_id,
    ).items():
        field_price_metadata.setdefault(str(field_name), {}).update(dict(metadata or {}))
    return ReviewResolutionInputs(
        corrections_map=corrections_map,
        decisions_map=decisions_map,
        skip_rows_set=skip_rows_set,
        column_types=column_types,
        field_price_metadata=field_price_metadata,
    )


def collect_review_actions(
    *,
    job_id: str,
    agency_id: int,
    user_id: int,
    entity_type: str,
    review_rows: list[ReviewRowPayload],
    inputs: ReviewResolutionInputs,
    normalization_pipeline_cls: Callable[..., object],
    validate_row_fn: Callable[[dict[str, object], str], tuple[dict[str, object], list[str]]],
) -> ReviewResolutionState:
    state = ReviewResolutionState()
    for review_entry in review_rows:
        row_num = _coerce_int(review_entry.get("row", 0))
        review_entity_type = (
            str(review_entry.get("entity_type") or entity_type or "").strip().lower()
        )
        lookup_keys = review_row_lookup_keys(
            row_num=row_num,
            entity_type=review_entity_type or entity_type,
        )
        if any(key in inputs.skip_rows_set for key in lookup_keys):
            disposition = (
                ImportDeadLetterRow.Disposition.BLOCKING_DISCARDED
                if _as_list(review_entry.get("blocking_reasons", []))
                else ImportDeadLetterRow.Disposition.HUMAN_SKIPPED
            )
            state.dead_letter_rows.append(
                build_dead_letter_row(
                    job_id=job_id,
                    agency_id=agency_id,
                    row_ordinal=row_num,
                    disposition=disposition,
                    phase="review",
                    actor_id=user_id,
                    entity_type=review_entity_type,
                    topology_side=str(review_entry.get("topology_side", "") or ""),
                    raw_data=_as_dict(review_entry.get("original", {})),
                    normalized_data=_as_dict(review_entry.get("data", {})),
                    recoverability_class=str(review_entry.get("recoverability_class", "") or ""),
                    recovered_fields=review_entry.get("recovered_fields"),
                    recovery_candidates=review_entry.get("recovery_candidates"),
                    blocking_reasons=review_entry.get("blocking_reasons"),
                    reason_codes=["review_skip"],
                    reason_messages=["Skipped during review."],
                )
            )
            state.decision_summary[SKIP] += 1
            continue

        row_data = _as_dict(review_entry.get("data", {}))
        original = _as_dict(review_entry.get("original", row_data))
        correction_payload: dict[str, object] = {}
        for key in lookup_keys:
            if key in inputs.corrections_map:
                correction_payload = _as_dict(inputs.corrections_map.get(key, {}) or {})
                break
        row_data.update(correction_payload)

        decision: dict[str, object] = {}
        for key in lookup_keys:
            if key in inputs.decisions_map:
                decision = _as_dict(inputs.decisions_map.get(key, {}) or {})
                break
        row_entity_type = (
            str(decision.get("entity_type") or review_entity_type or entity_type or "")
            .strip()
            .lower()
        )
        row_pipeline = cast(
            NormalizationPipelineProtocol,
            normalization_pipeline_cls(
                entity_type=row_entity_type or entity_type,
                column_types=inputs.column_types,
                field_metadata=inputs.field_price_metadata,
            ),
        )
        normalized = row_pipeline.normalize_row(row_data)
        candidate_matches = review_candidate_matches(review_entry)
        action = str(decision.get("action", "") or "").strip().lower()
        if action == CREATE_NEW:
            action = "create"
        elif action == UPDATE_EXISTING:
            action = "update"
        elif action == REVIEW_AMBIGUOUS:
            action = "review"
        existing_id_raw = decision.get("existing_id")
        existing_row_version_raw = decision.get("row_version")

        if normalized.needs_review:
            state.still_review.append(
                _still_review_row(
                    row_num=row_num,
                    row_data=normalized.data,
                    original=original,
                    review_fields=_normalized_review_fields(normalized.review_fields),
                    remarks=list(normalized.remarks),
                    candidate_matches=candidate_matches,
                    review_entry=review_entry,
                    entity_type=row_entity_type or entity_type,
                )
            )
            continue

        validated_row, row_errors = validate_row_fn(normalized.data, row_entity_type or entity_type)
        if row_errors:
            state.still_review.append(
                _still_review_row(
                    row_num=row_num,
                    row_data=normalized.data,
                    original=original,
                    review_fields=[
                        {
                            "field": "validation",
                            "original": "",
                            "normalized": "",
                            "confidence": 0.0,
                            "remark": "; ".join(row_errors),
                        }
                    ],
                    remarks=row_errors,
                    candidate_matches=candidate_matches,
                    review_entry=review_entry,
                    entity_type=row_entity_type or entity_type,
                )
            )
            state.errors_list.append(
                {
                    "row": row_num,
                    "entity_type": row_entity_type or entity_type,
                    "errors": row_errors,
                }
            )
            continue

        if candidate_matches and action not in {"create", "update", "skip", "review"}:
            state.still_review.append(
                _still_review_row(
                    row_num=row_num,
                    row_data=validated_row,
                    original=original,
                    review_fields=_review_entry_fields(review_entry),
                    remarks=_review_entry_remarks(review_entry)
                    + ["Choose create, update, review later, or skip for this duplicate row."],
                    candidate_matches=candidate_matches,
                    review_entry=review_entry,
                    entity_type=row_entity_type or entity_type,
                )
            )
            continue

        if action == "skip":
            state.decision_summary[SKIP] += 1
            disposition = (
                ImportDeadLetterRow.Disposition.BLOCKING_DISCARDED
                if _as_list(review_entry.get("blocking_reasons", []))
                else ImportDeadLetterRow.Disposition.HUMAN_SKIPPED
            )
            state.dead_letter_rows.append(
                build_dead_letter_row(
                    job_id=job_id,
                    agency_id=agency_id,
                    row_ordinal=row_num,
                    disposition=disposition,
                    phase="review",
                    actor_id=user_id,
                    entity_type=row_entity_type or entity_type,
                    topology_side=str(review_entry.get("topology_side", "") or ""),
                    raw_data=original,
                    normalized_data=validated_row,
                    recoverability_class=str(review_entry.get("recoverability_class", "") or ""),
                    recovered_fields=review_entry.get("recovered_fields"),
                    recovery_candidates=review_entry.get("recovery_candidates"),
                    blocking_reasons=review_entry.get("blocking_reasons"),
                    reason_codes=["review_skip"],
                    reason_messages=["Skipped during review."],
                )
            )
            state.audit_entries.append(
                build_review_audit_entry(
                    row_num=row_num,
                    entity_type=row_entity_type or entity_type,
                    action="skip",
                    validated_row=validated_row,
                    review_entry=review_entry,
                    correction_payload=correction_payload,
                )
            )
            continue

        if action == "review":
            state.decision_summary[REVIEW_AMBIGUOUS] += 1
            state.audit_entries.append(
                build_review_audit_entry(
                    row_num=row_num,
                    entity_type=row_entity_type or entity_type,
                    action="review",
                    validated_row=validated_row,
                    review_entry=review_entry,
                    existing_id=_coerce_int(review_entry.get("suggested_existing_id", 0)),
                    correction_payload=correction_payload,
                )
            )
            state.still_review.append(
                _still_review_row(
                    row_num=row_num,
                    row_data=validated_row,
                    original=original,
                    review_fields=_review_entry_fields(review_entry),
                    remarks=_review_entry_remarks(review_entry),
                    candidate_matches=candidate_matches,
                    review_entry=review_entry,
                    entity_type=row_entity_type or entity_type,
                )
            )
            continue

        if action == "update":
            candidate_ids = {_coerce_int(candidate.get("id", 0)) for candidate in candidate_matches}
            candidate_versions = {
                _coerce_int(candidate.get("id", 0)): _coerce_int(candidate.get("row_version", 0))
                for candidate in candidate_matches
            }
            existing_id = _coerce_int(existing_id_raw)
            if existing_id <= 0 and len(candidate_matches) == 1:
                existing_id = _coerce_int(candidate_matches[0].get("id", 0))
            if existing_id <= 0 or (candidate_ids and existing_id not in candidate_ids):
                state.still_review.append(
                    _still_review_row(
                        row_num=row_num,
                        row_data=validated_row,
                        original=original,
                        review_fields=_review_entry_fields(review_entry),
                        remarks=["Select the existing row to update."],
                        candidate_matches=candidate_matches,
                        review_entry=review_entry,
                        entity_type=row_entity_type or entity_type,
                    )
                )
                continue
            existing_row_version = _coerce_int(existing_row_version_raw)
            if existing_row_version <= 0:
                existing_row_version = _coerce_int(candidate_versions.get(existing_id, 0))
            if existing_row_version <= 0:
                state.still_review.append(
                    _still_review_row(
                        row_num=row_num,
                        row_data=validated_row,
                        original=original,
                        review_fields=_review_entry_fields(review_entry),
                        remarks=["Selected existing row is missing row version information."],
                        candidate_matches=candidate_matches,
                        review_entry=review_entry,
                        entity_type=row_entity_type or entity_type,
                    )
                )
                continue
            selected_candidate = next(
                (
                    candidate
                    for candidate in candidate_matches
                    if _coerce_int(candidate.get("id", 0)) == existing_id
                ),
                cast(ReviewCandidatePayload, {}),
            )
            selected_field_diff = cast(
                ReviewFieldDiffPayload,
                _as_dict(selected_candidate.get("field_diff", {})),
            )
            if has_immutable_conflict(cast(dict[str, list[dict[str, Any]]], selected_field_diff)):
                state.still_review.append(
                    _still_review_row(
                        row_num=row_num,
                        row_data=validated_row,
                        original=original,
                        review_fields=_review_entry_fields(review_entry),
                        remarks=["Immutable field conflicts must be resolved manually."],
                        candidate_matches=candidate_matches,
                        review_entry=review_entry,
                        entity_type=row_entity_type or entity_type,
                        extra_fields={"immutable_conflict": True},
                    )
                )
                continue
            if row_entity_type not in {
                ENTITY_TYPE_CLIENT,
                ENTITY_TYPE_LISTING,
                ENTITY_TYPE_DEMANDE,
                ENTITY_TYPE_OFFER,
            }:
                state.still_review.append(
                    _still_review_row(
                        row_num=row_num,
                        row_data=validated_row,
                        original=original,
                        review_fields=_review_entry_fields(review_entry),
                        remarks=["Unsupported entity type for update."],
                        candidate_matches=candidate_matches,
                        review_entry=review_entry,
                        entity_type=row_entity_type or entity_type,
                    )
                )
                continue
            state.pending_updates.append(
                PendingUpdateRow(
                    row_num=row_num,
                    entity_type=row_entity_type or entity_type,
                    validated_row=dict(validated_row),
                    existing_id=existing_id,
                    row_version=existing_row_version,
                    review_entry=review_entry,
                    before_payload=_as_dict(selected_candidate.get("snapshot", {})),
                    diff_payload=selected_field_diff,
                    correction_payload=dict(correction_payload),
                )
            )
            continue

        validated_row["created_by_id"] = user_id
        state.create_pending_by_entity.setdefault(row_entity_type or entity_type, []).append(
            PendingCreateRow(
                row_num=row_num,
                entity_type=row_entity_type or entity_type,
                validated_row=dict(validated_row),
                correction_payload=dict(correction_payload),
                review_entry=review_entry,
            )
        )
    return state


__all__ = [
    "AppliedReviewRow",
    "NormalizationPipelineProtocol",
    "PendingUpdateRow",
    "ReviewResolutionInputs",
    "ReviewResolutionState",
    "collect_review_actions",
    "normalize_resolution_inputs",
]
