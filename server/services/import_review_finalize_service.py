"""Review-submit completion and finalization helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import cast

from django.db import transaction

from server.imports.models import ImportJob
from server.services.import_audit import record_row_audits
from server.services.import_review_compatibility import enrich_review_items
from server.services.import_review_db_state import clear_db_review_state, persist_review_rows
from server.services.import_review_queries import (
    ReviewCountSnapshot,
    compatibility_review_rows,
    paged_review_groups,
    paged_review_items,
)
from server.services.import_types import ReviewGroupPayload, ReviewRowPayload
from server.services.import_ui_summary import (
    review_overflow_count_for_payload,
    summarize_result_state,
)
from server.services.json_safe import json_safe_value

_LEGACY_COMPATIBILITY_LIMIT = 25
_REVIEW_HISTORY_WINDOW = 25


@dataclass(frozen=True)
class ReviewSubmitCompletion:
    summary: dict[str, object]
    created_count: int
    created_entity_counts: dict[str, int]
    updated_count: int
    review_pending_group_count: int
    still_review_count: int
    review_overflow_count: int
    review_total_count: int
    errors: list[dict[str, object]]
    legacy_rows: list[ReviewRowPayload]
    review_groups: list[ReviewGroupPayload]
    review_items: list[ReviewRowPayload]
    result_entity_counts: dict[str, int]
    result_auto_fix_summary: dict[str, int]
    result_attention_summary: dict[str, int]
    overflow_blocking: bool


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
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _safe_review_rows(review_rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    return [dict(row) for row in review_rows if isinstance(row, Mapping)]


def _merged_dead_letter_summary(
    *,
    summary: Mapping[str, object],
    review_result: Mapping[str, object],
) -> dict[str, int]:
    merged = {
        str(key): _coerce_int(value)
        for key, value in _as_dict(summary.get("dead_letter_summary", {})).items()
    }
    for key, value in _as_dict(review_result.get("dead_letter_summary", {})).items():
        merged[str(key)] = merged.get(str(key), 0) + _coerce_int(value)
    return merged


def finalize_review_submission(
    *,
    job: ImportJob,
    actor_user_id: int,
    review_result: Mapping[str, object],
) -> ReviewSubmitCompletion:
    created_count = _coerce_int(review_result.get("created_count", 0))
    updated_count = _coerce_int(review_result.get("updated_count", 0))
    created_entity_counts = {
        str(key): _coerce_int(value)
        for key, value in _as_dict(review_result.get("created_entity_counts", {})).items()
        if str(key or "").strip()
    }
    still_review_rows = _safe_review_rows(
        cast(list[Mapping[str, object]], review_result.get("still_review", []))
    )
    errors = [
        dict(error)
        for error in _as_list(review_result.get("errors", []))
        if isinstance(error, Mapping)
    ]
    audit_entries = [
        dict(entry)
        for entry in _as_list(review_result.get("audit_entries", []))
        if isinstance(entry, Mapping)
    ]
    completion_summary: dict[str, object] = {}
    review_pending_group_count = 0
    still_review_count = 0
    review_overflow_count = 0
    review_total_count = 0
    result_entity_counts_payload: dict[str, int] = {}
    result_auto_fix_summary: dict[str, int] = {}
    result_attention_summary: dict[str, int] = {}

    with transaction.atomic():
        if still_review_rows:
            snapshot = persist_review_rows(job=job, review_rows=still_review_rows)
            job.review_rows = compatibility_review_rows(job, limit=_LEGACY_COMPATIBILITY_LIMIT)
        else:
            clear_db_review_state(job)
            snapshot = ReviewCountSnapshot(
                visible_review_count=0,
                pending_group_count=0,
                conflict_count=0,
                issue_counts={},
            )
            job.review_rows = []

        summary = _as_dict(job.result_summary)
        visible_review_count = int(snapshot.visible_review_count or 0)
        terminal_error_count = 0 if visible_review_count > 0 else len(errors)
        prior_created = _coerce_int(summary.get("created_count", 0))
        prior_updated = _coerce_int(summary.get("updated_count", 0))
        prior_skipped = _coerce_int(summary.get("skipped_count", 0))
        dead_letter_summary = _merged_dead_letter_summary(
            summary=summary, review_result=review_result
        )
        dead_letter_total = sum(int(value or 0) for value in dead_letter_summary.values())

        summary["created_count"] = prior_created + created_count
        summary["updated_count"] = prior_updated + updated_count
        summary["skipped_count"] = prior_skipped + dead_letter_total
        summary["error_count"] = terminal_error_count
        summary["errors"] = cast(list[dict[str, object]], json_safe_value(errors))
        summary["review_count"] = visible_review_count
        summary["review_overflow_count"] = 0
        summary["review_total_count"] = visible_review_count
        summary["review_pending_group_count"] = int(snapshot.pending_group_count or 0)
        summary["review_storage_mode"] = "db_paged_v2"
        summary["review_state"] = "normal" if visible_review_count > 0 else "none"
        summary["overflow_blocking"] = False
        summary["review_disabled"] = False
        summary["review_disabled_reason"] = ""
        summary["dead_letter_summary"] = cast(
            dict[str, object], json_safe_value(dead_letter_summary)
        )
        summary["decision_summary"] = cast(
            dict[str, object], json_safe_value(_as_dict(review_result.get("decision_summary", {})))
        )
        summary["learning_summary"] = cast(
            dict[str, object], json_safe_value(_as_dict(review_result.get("learning_summary", {})))
        )

        result_entity_counts = {
            str(key): _coerce_int(value)
            for key, value in _as_dict(summary.get("result_entity_counts", {})).items()
            if str(key or "").strip()
        }
        for entity_type, count in created_entity_counts.items():
            result_entity_counts[entity_type] = result_entity_counts.get(entity_type, 0) + count
        summary["result_entity_counts"] = cast(
            dict[str, object], json_safe_value(result_entity_counts)
        )

        review_history = [
            dict(entry)
            for entry in _as_list(summary.get("review_history", []))
            if isinstance(entry, Mapping)
        ]
        prior_history_count = max(
            _coerce_int(summary.get("review_history_count", len(review_history))),
            len(review_history),
        )
        review_history.extend(audit_entries)
        summary["review_history"] = cast(
            list[object], json_safe_value(review_history[-_REVIEW_HISTORY_WINDOW:])
        )
        summary["review_history_count"] = prior_history_count + len(audit_entries)

        job.progress_detail = cast(
            dict[str, object],
            json_safe_value(
                {
                    **_as_dict(job.progress_detail),
                    "phase": "review" if still_review_rows else "done",
                    "error_count": terminal_error_count,
                    "review_overflow_count": 0,
                    "review_pending_group_count": int(snapshot.pending_group_count or 0),
                    "review_state": ("normal" if visible_review_count > 0 else "none"),
                    "overflow_blocking": False,
                    "review_disabled": False,
                    "review_disabled_reason": "",
                }
            ),
        )

        rows_changed_this_submit = created_count > 0 or updated_count > 0 or dead_letter_total > 0
        if visible_review_count > 0:
            job.status = ImportJob.Status.READY
            job.stage = ImportJob.Stage.REVIEW
            job.error_message = None
        elif len(errors) > 0 and not rows_changed_this_submit:
            job.status = ImportJob.Status.FAILED
            job.stage = ImportJob.Stage.EXECUTION
            job.error_message = "A few lines couldn't be imported safely."
            job.progress = 100
        else:
            job.status = ImportJob.Status.COMPLETED
            job.stage = ImportJob.Stage.EXECUTION
            job.error_message = None
            job.progress = 100

        (
            result_entity_counts_payload,
            result_auto_fix_summary,
            result_attention_summary,
        ) = summarize_result_state(
            result_summary=summary,
            review_rows=job.review_rows,
        )
        summary["result_entity_counts"] = cast(
            dict[str, object], json_safe_value(result_entity_counts_payload)
        )
        summary["result_auto_fix_summary"] = cast(
            dict[str, object], json_safe_value(result_auto_fix_summary)
        )
        summary["result_attention_summary"] = cast(
            dict[str, object], json_safe_value(result_attention_summary)
        )

        job.result_summary = cast(dict[str, object], json_safe_value(summary))
        update_fields = [
            "review_rows",
            "result_summary",
            "progress_detail",
            "status",
            "stage",
            "error_message",
            "updated_at",
        ]
        if job.status in {ImportJob.Status.COMPLETED, ImportJob.Status.FAILED}:
            update_fields.append("progress")
        job.save(update_fields=update_fields)

        if audit_entries:
            record_row_audits(
                job=job,
                actor_user_id=actor_user_id,
                audit_entries=audit_entries,
            )

        completion_summary = dict(job.result_summary or {})
        review_pending_group_count = int(snapshot.pending_group_count or 0)
        still_review_count = int(snapshot.visible_review_count or 0)
        review_overflow_count = review_overflow_count_for_payload(result_summary=completion_summary)
        review_total_count = _coerce_int(
            completion_summary.get("review_total_count", snapshot.visible_review_count)
        )

    review_groups: list[ReviewGroupPayload] = []
    review_items: list[ReviewRowPayload] = []
    legacy_rows: list[ReviewRowPayload] = []
    if still_review_count > 0:
        review_groups, _groups_page = paged_review_groups(
            job=job,
            page=1,
            page_size=200,
            issue_group=None,
            search="",
            pending_only=True,
        )
        selected_group_key = (
            str(review_groups[0].get("group_key", "") or "") if review_groups else None
        )
        review_items, _items_page = paged_review_items(
            job=job,
            page=1,
            page_size=200,
            group_key=selected_group_key,
            issue_group=None,
            search="",
            pending_only=True,
        )
        review_items, legacy_rows = enrich_review_items(job=job, review_items=review_items)

    return ReviewSubmitCompletion(
        summary=completion_summary,
        created_count=created_count,
        created_entity_counts=created_entity_counts,
        updated_count=updated_count,
        review_pending_group_count=review_pending_group_count,
        still_review_count=still_review_count,
        review_overflow_count=review_overflow_count,
        review_total_count=review_total_count,
        errors=errors,
        legacy_rows=legacy_rows,
        review_groups=review_groups,
        review_items=review_items,
        result_entity_counts=result_entity_counts_payload,
        result_auto_fix_summary=result_auto_fix_summary,
        result_attention_summary=result_attention_summary,
        overflow_blocking=False,
    )


__all__ = ["ReviewSubmitCompletion", "finalize_review_submission"]
