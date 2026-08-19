"""Typed status-summary derivation for importer public payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from server.services.import_review_store import ensure_review_state, review_count_snapshot
from server.services.import_status_contracts import (
    EnsureReviewStateFn,
    ImportStatusSession,
    ReviewCountSnapshotFn,
    ReviewSnapshotProtocol,
)
from server.services.import_status_policy import coerce_progress_int, coerce_summary_mapping
from server.services.import_ui_summary import (
    review_overflow_count_for_payload,
    review_state_for_payload,
    review_total_count_for_payload,
    summarize_preview_rows,
    summarize_result_state,
)

DEFAULT_ENSURE_REVIEW_STATE_FN = cast(EnsureReviewStateFn, ensure_review_state)
DEFAULT_REVIEW_COUNT_SNAPSHOT_FN = cast(ReviewCountSnapshotFn, review_count_snapshot)


@dataclass(frozen=True)
class ImportStatusSummary:
    progress_detail: dict[str, object]
    inference_summary: dict[str, object]
    inferred: dict[str, object]
    detected_columns: list[dict[str, object]]
    sheet_profiles: list[dict[str, object]]
    row_count: int
    review_snapshot: ReviewSnapshotProtocol
    review_state: str
    review_rows_visible: int
    review_overflow_count: int
    review_total_count: int
    preview_entity_counts: dict[str, int]
    preview_auto_fix_summary: dict[str, int]
    preview_attention_summary: dict[str, int]
    result_entity_counts: dict[str, int]
    result_auto_fix_summary: dict[str, int]
    result_attention_summary: dict[str, int]


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


def _rows(value: object) -> list[dict[str, object]]:
    return [dict(row) for row in _items(value) if isinstance(row, Mapping)]


def build_import_status_summary(
    *,
    session: ImportStatusSession,
    result_summary: Mapping[str, object],
    ensure_review_state_fn: EnsureReviewStateFn = DEFAULT_ENSURE_REVIEW_STATE_FN,
    review_count_snapshot_fn: ReviewCountSnapshotFn = DEFAULT_REVIEW_COUNT_SNAPSHOT_FN,
) -> ImportStatusSummary:
    progress_detail = _dict_copy(session.progress_detail)
    inference_summary = _dict_copy(session.inference_summary)
    inferred = _dict_copy(inference_summary.get("final_inference"))
    detected_columns = _rows(session.detected_columns)
    sheet_profiles = _rows(inference_summary.get("sheet_profiles"))
    preview_rows = _rows(session.preview_rows)
    review_rows = _rows(session.review_rows)
    row_count = coerce_progress_int(result_summary.get("row_count"), default=0)

    preview_entity_counts = coerce_summary_mapping(
        inference_summary.get("preview_entity_counts"),
        allowed_keys={"client", "demande", "listing", "offer"},
    )
    preview_auto_fix_summary = coerce_summary_mapping(
        inference_summary.get("preview_auto_fix_summary"),
        allowed_keys={
            "phone_format_fixed",
            "name_case_fixed",
            "location_normalized",
            "grouped_related_rows",
            "other_auto_fixes",
        },
    )
    preview_attention_summary = coerce_summary_mapping(
        inference_summary.get("preview_attention_summary"),
        allowed_keys={
            "needs_attention",
            "blocking",
            "possible_duplicates",
            "missing_information",
        },
    )
    if not preview_entity_counts or not preview_auto_fix_summary or not preview_attention_summary:
        preview_entity_counts, preview_auto_fix_summary, preview_attention_summary = (
            summarize_preview_rows(
                preview_rows,
                bundle_mode=str(inferred.get("bundle_mode", "single_entity") or "single_entity"),
            )
        )

    result_entity_counts, result_auto_fix_summary, result_attention_summary = (
        summarize_result_state(
            result_summary=result_summary,
            review_rows=review_rows,
        )
    )
    if not any(int(value or 0) > 0 for value in result_auto_fix_summary.values()):
        result_auto_fix_summary = dict(preview_auto_fix_summary)

    review_snapshot = ensure_review_state_fn(session) or review_count_snapshot_fn(session)
    issue_counts = dict(review_snapshot.issue_counts or {})
    result_attention_summary["needs_attention"] = max(
        int(result_attention_summary.get("needs_attention", 0) or 0),
        int(review_snapshot.visible_review_count or 0)
        + coerce_progress_int(result_summary.get("error_count"), default=0),
    )
    result_attention_summary["possible_duplicates"] = max(
        int(result_attention_summary.get("possible_duplicates", 0) or 0),
        int(issue_counts.get("possible_duplicate", 0) or 0),
    )
    result_attention_summary["missing_information"] = max(
        int(result_attention_summary.get("missing_information", 0) or 0),
        int(issue_counts.get("missing_information", 0) or 0),
    )
    result_attention_summary["blocking"] = max(
        int(result_attention_summary.get("blocking", 0) or 0),
        int(issue_counts.get("field_conflict", 0) or 0),
    )

    review_rows_visible = int(review_snapshot.visible_review_count or 0)
    return ImportStatusSummary(
        progress_detail=progress_detail,
        inference_summary=inference_summary,
        inferred=inferred,
        detected_columns=detected_columns,
        sheet_profiles=sheet_profiles,
        row_count=row_count,
        review_snapshot=review_snapshot,
        review_state=review_state_for_payload(
            progress_detail=progress_detail,
            result_summary=result_summary,
        ),
        review_rows_visible=review_rows_visible,
        review_overflow_count=review_overflow_count_for_payload(
            progress_detail=progress_detail,
            result_summary=result_summary,
        ),
        review_total_count=review_total_count_for_payload(
            visible_review_count=review_rows_visible,
            progress_detail=progress_detail,
            result_summary=result_summary,
        ),
        preview_entity_counts=preview_entity_counts,
        preview_auto_fix_summary=preview_auto_fix_summary,
        preview_attention_summary=preview_attention_summary,
        result_entity_counts=result_entity_counts,
        result_auto_fix_summary=result_auto_fix_summary,
        result_attention_summary=result_attention_summary,
    )


__all__ = ["ImportStatusSummary", "build_import_status_summary"]
