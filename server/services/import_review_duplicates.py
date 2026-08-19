"""Duplicate-review row shaping for importer database matches."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from core.importer.security import import_security_limits
from server.services.duplicate_checker import DbDuplicateCandidate, DbDuplicateMatch
from server.services.import_constants import ENTITY_TYPE_CLIENT, ENTITY_TYPE_DEMANDE
from server.services.import_diff_builder import has_immutable_conflict
from server.services.import_review_policy import (
    DECISION_OPTIONS,
    REVIEW_AMBIGUOUS,
    UPDATE_EXISTING,
    decision_policy_for_entity,
)
from server.services.import_review_runtime import append_review_row_limited
from server.services.import_types import (
    ReviewCandidatePayload,
    ReviewFieldDiffPayload,
    ReviewFieldPayload,
    ReviewRowPayload,
    ReviewRows,
)

_REVIEW_DIFF_FIELDS = ("family_name", "phone", "remarks", "status")


def _coerce_payload(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _build_candidate_field_diffs(
    row_data: Mapping[str, object],
    *,
    candidate: DbDuplicateCandidate,
) -> list[dict[str, object]]:
    diffs: list[dict[str, object]] = []
    for field_name in _REVIEW_DIFF_FIELDS:
        incoming = str(row_data.get(field_name, "") or "")
        existing = str(getattr(candidate, field_name, "") or "")
        if incoming == existing:
            continue
        diffs.append(
            {
                "field": field_name,
                "incoming": incoming,
                "existing": existing,
            }
        )
    return diffs


def _selected_field_diff(
    candidate_matches: list[ReviewCandidatePayload],
    *,
    existing_id: int,
) -> ReviewFieldDiffPayload:
    for candidate in candidate_matches:
        candidate_id = int(candidate.get("id", 0) or 0)
        if candidate_id != existing_id:
            continue
        raw_field_diff = candidate.get("field_diff", {})
        if not isinstance(raw_field_diff, dict):
            break
        return cast(
            ReviewFieldDiffPayload,
            {
                "changed_mutable": list(raw_field_diff.get("changed_mutable", []) or []),
                "changed_immutable": list(raw_field_diff.get("changed_immutable", []) or []),
                "unchanged": list(raw_field_diff.get("unchanged", []) or []),
            },
        )
    return cast(
        ReviewFieldDiffPayload,
        {
            "changed_mutable": [],
            "changed_immutable": [],
            "unchanged": [],
        },
    )


def _duplicate_remark(
    *,
    duplicate_count: int,
    suggested_action: str,
    suggested_confidence: float,
    suggested_reasons: list[str],
) -> str:
    duplicate_remark = "Phone already exists in database"
    if duplicate_count > 1:
        duplicate_remark = f"Phone matches {duplicate_count} existing rows in this agency"
    max_candidates = import_security_limits().max_duplicate_candidates
    if duplicate_count > max_candidates:
        duplicate_remark = f"{duplicate_remark}; showing up to top {max_candidates} matches"
    if suggested_action == UPDATE_EXISTING:
        if suggested_reasons:
            return (
                f"Suggested update: best match confidence {suggested_confidence:.2f}"
                f" ({', '.join(suggested_reasons)})"
            )
        return f"Suggested update: best match confidence {suggested_confidence:.2f}"
    return duplicate_remark


def _append_duplicate_review_row(
    review_rows: ReviewRows,
    review_row: ReviewRowPayload,
) -> bool:
    if not hasattr(review_rows, "overflow_count"):
        max_review_rows = import_security_limits().max_review_items_emergency
        if len(review_rows) >= max_review_rows:
            raise ValueError(
                f"Import generated more than {max_review_rows} review rows. "
                "Clean or split the file and retry."
            )
    return append_review_row_limited(review_rows, review_row)


def append_db_duplicate_reviews(
    *,
    entity_type: str,
    review_rows: ReviewRows,
    db_matches: list[DbDuplicateMatch],
    rows_by_index: Mapping[int, Mapping[str, object]],
) -> None:
    policy = decision_policy_for_entity(entity_type)
    for match in db_matches:
        row_index = int(match.row_index or 0)
        source_entry = rows_by_index.get(row_index, {})
        dup_row = _coerce_payload(source_entry.get("data", {}))
        original = _coerce_payload(source_entry.get("original", dup_row))
        candidate_matches: list[ReviewCandidatePayload] = []
        suggested_action = str(match.suggested_action or REVIEW_AMBIGUOUS)
        suggested_existing_id = int(match.suggested_existing_id or 0)
        suggested_confidence = 0.0
        suggested_reasons: list[str] = []
        candidate_version = 0

        for candidate in list(match.candidates or []):
            confidence = round(float(candidate.match_confidence or 0.0), 3)
            reasons = [str(value) for value in list(candidate.match_reasons or []) if value]
            field_diffs = _build_candidate_field_diffs(dup_row, candidate=candidate)
            changed_mutable = [
                diff for diff in field_diffs if str(diff.get("field", "")) in policy.mutable_fields
            ]
            changed_immutable = [
                diff
                for diff in field_diffs
                if str(diff.get("field", "")) in policy.immutable_fields
            ]
            candidate_payload: ReviewCandidatePayload = {
                "id": int(candidate.existing_id or 0),
                "row_version": int(candidate.row_version or 0),
                "family_name": str(candidate.family_name or ""),
                "phone": str(candidate.phone or ""),
                "remarks": str(candidate.remarks or ""),
                "status": str(candidate.status or ""),
                "match_confidence": confidence,
                "match_reasons": reasons,
                "field_diffs": field_diffs,
                "field_diff": {
                    "changed_mutable": changed_mutable,
                    "changed_immutable": changed_immutable,
                    "unchanged": [],
                },
            }
            candidate_matches.append(candidate_payload)
            candidate_id = int(candidate.existing_id or 0)
            if suggested_existing_id > 0 and candidate_id == suggested_existing_id:
                suggested_confidence = confidence
                suggested_reasons = reasons
                candidate_version = int(candidate.row_version or 0)

        selected_field_diff = _selected_field_diff(
            candidate_matches,
            existing_id=suggested_existing_id,
        )
        duplicate_remark = _duplicate_remark(
            duplicate_count=max(int(match.total_candidate_count or 0), len(candidate_matches)),
            suggested_action=suggested_action,
            suggested_confidence=suggested_confidence,
            suggested_reasons=suggested_reasons,
        )
        candidate_total_count = max(int(match.total_candidate_count or 0), len(candidate_matches))
        review_row: ReviewRowPayload = {
            "row": row_index,
            "data": dup_row,
            "normalized_data": dict(dup_row),
            "original": original,
            "raw_data": dict(original),
            "entity_type": entity_type,
            "topology_side": (
                "client_side"
                if entity_type in {ENTITY_TYPE_CLIENT, ENTITY_TYPE_DEMANDE}
                else "listing_side"
            ),
            "candidate_matches": candidate_matches,
            "suggested_action": suggested_action,
            "suggested_existing_id": suggested_existing_id,
            "candidate_version": candidate_version,
            "suggested_confidence": suggested_confidence,
            "suggested_reasons": suggested_reasons,
            "candidate_total_count": candidate_total_count,
            "candidate_matches_truncated": candidate_total_count > len(candidate_matches),
            "decision_options": list(DECISION_OPTIONS),
            "mutable_fields": list(policy.mutable_fields),
            "immutable_fields": list(policy.immutable_fields),
            "field_diff": selected_field_diff,
            "review_fields": [
                cast(
                    ReviewFieldPayload,
                    {
                        "field": "phone",
                        "original": str(dup_row.get("phone", "")),
                        "normalized": str(dup_row.get("phone", "")),
                        "confidence": suggested_confidence or 1.0,
                        "remark": duplicate_remark,
                    },
                )
            ],
            "remarks": [duplicate_remark],
            "inline_editable": True,
            "immutable_conflict": bool(
                has_immutable_conflict(cast(dict[str, list[dict[str, Any]]], selected_field_diff))
            ),
        }
        if not _append_duplicate_review_row(review_rows, review_row):
            return


__all__ = ["append_db_duplicate_reviews"]
