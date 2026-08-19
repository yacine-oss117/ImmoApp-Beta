"""Compatibility row projection and enrichment for importer review flows."""

from __future__ import annotations

from typing import cast

from server.imports.models import ImportJob, ImportReviewItem
from server.services.import_review_metadata_safety import project_review_metadata
from server.services.import_types import (
    ReviewCandidatePayload,
    ReviewFieldPayload,
    ReviewRowPayload,
)
from server.services.import_ui_summary import issue_metadata


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def build_compatibility_review_row(item: ImportReviewItem) -> ReviewRowPayload:
    metadata = dict(item.metadata or {})
    review_row: ReviewRowPayload = {
        "row": int(item.row_ordinal or 0),
        "data": dict(item.normalized_data or {}),
        "normalized_data": dict(item.normalized_data or {}),
        "original": dict(item.raw_data or {}),
        "raw_data": dict(item.raw_data or {}),
        "entity_type": str(item.entity_type or ""),
        "topology_side": str(item.topology_side or ""),
        "suggested_action": str(item.suggested_action or ""),
        "suggested_existing_id": int(item.suggested_existing_id or 0),
        "suggested_confidence": float(item.suggested_confidence or 0.0),
        "candidate_matches": cast(list[ReviewCandidatePayload], list(item.candidate_matches or [])),
        "review_fields": cast(list[ReviewFieldPayload], list(item.review_fields or [])),
        "recovered_fields": cast(list[dict[str, object]], list(item.recovered_fields or [])),
        "recovery_candidates": cast(list[dict[str, object]], list(item.recovery_candidates or [])),
        "blocking_reasons": list(item.blocking_reasons or []),
        "quick_fix_actions": cast(list[dict[str, object]], list(item.quick_fix_actions or [])),
        "bulk_fix_groups": cast(list[dict[str, object]], list(item.bulk_fix_groups or [])),
        "inline_editable": True,
        "immutable_conflict": bool(item.immutable_conflict),
        "recoverability_class": str(item.recoverability_class or "review_recoverable"),
        "issue_group": str(item.issue_group or "other"),
        "issue_title": str(item.issue_title or "Needs attention"),
        "issue_summary": str(
            item.issue_summary or "This line needs a quick review before we continue."
        ),
    }
    compatibility_row = project_review_metadata(review_row, metadata)
    compatibility_row.update(issue_metadata(compatibility_row))
    return cast(ReviewRowPayload, compatibility_row)


def enrich_review_items(
    *,
    job: ImportJob,
    review_items: list[ReviewRowPayload],
) -> tuple[list[ReviewRowPayload], list[ReviewRowPayload]]:
    from server.services.import_review_rescue import (
        allowed_reclassify_options,
        build_bulk_fix_groups,
        build_quick_fix_actions,
        bulk_fix_groups_for_row,
    )

    final_inference = dict((job.inference_summary or {}).get("final_inference", {}) or {})
    bundle_mode = str(final_inference.get("bundle_mode", "single_entity") or "single_entity")
    topology_side_hint = str(final_inference.get("topology_side_hint", "unknown") or "unknown")
    has_persisted_bulk_groups = any(
        bool(list(item.get("bulk_fix_groups", []) or [])) for item in review_items
    )
    legacy_rows: list[ReviewRowPayload] = []
    for item in review_items:
        row: ReviewRowPayload = {
            "row": int(item.get("row", 0) or 0),
            "data": dict(item.get("normalized_data", {}) or {}),
            "normalized_data": dict(item.get("normalized_data", {}) or {}),
            "original": dict(item.get("raw_data", {}) or {}),
            "raw_data": dict(item.get("raw_data", {}) or {}),
            "entity_type": str(item.get("entity_type", "") or ""),
            "topology_side": str(
                item.get("topology_side", topology_side_hint) or topology_side_hint
            ),
            "review_fields": list(item.get("review_fields", []) or []),
            "candidate_matches": list(item.get("candidate_matches", []) or []),
            "recovered_fields": list(item.get("recovered_fields", []) or []),
            "recovery_candidates": list(item.get("recovery_candidates", []) or []),
            "blocking_reasons": list(item.get("blocking_reasons", []) or []),
            "suggested_action": str(item.get("suggested_action", "") or ""),
            "suggested_existing_id": int(item.get("suggested_existing_id", 0) or 0),
            "suggested_confidence": float(item.get("suggested_confidence", 0.0) or 0.0),
            "quick_fix_actions": list(item.get("quick_fix_actions", []) or []),
            "bulk_fix_groups": list(item.get("bulk_fix_groups", []) or []),
            "inline_editable": True,
            "immutable_conflict": bool(item.get("immutable_conflict", False)),
            "recoverability_class": str(
                item.get("recoverability_class", "review_recoverable") or "review_recoverable"
            ),
            "item_id": int(item.get("item_id", 0) or 0),
            "group_key": str(item.get("group_key", "") or ""),
            "status": str(item.get("status", "pending") or "pending"),
            "issue_group": str(item.get("issue_group", "") or ""),
            "issue_title": str(item.get("issue_title", "") or ""),
            "issue_summary": str(item.get("issue_summary", "") or ""),
            "group_resolvable": bool(item.get("group_resolvable", False)),
            "group_resolution_blockers": list(item.get("group_resolution_blockers", []) or []),
            "resolution_source": str(item.get("resolution_source", "") or ""),
            "effective_action": item.get("effective_action"),
        }
        if isinstance(item.get("remarks"), list):
            row["remarks"] = list(item.get("remarks", []) or [])
        row.setdefault(
            "reclassify_options",
            allowed_reclassify_options(
                bundle_mode=bundle_mode,
                topology_side=str(
                    row.get("topology_side", topology_side_hint) or topology_side_hint
                ),
                entity_type=str(row.get("entity_type", "") or ""),
            ),
        )
        row.setdefault("quick_fix_actions", build_quick_fix_actions(row))
        legacy_rows.append(row)
    if not has_persisted_bulk_groups:
        all_bulk_fix_groups = build_bulk_fix_groups(legacy_rows)
        for row in legacy_rows:
            row["bulk_fix_groups"] = bulk_fix_groups_for_row(row, all_bulk_fix_groups)
    item_lookup = {int(row.get("item_id", 0) or 0): row for row in legacy_rows}
    normalized_items: list[ReviewRowPayload] = []
    for item in review_items:
        row = item_lookup.get(int(item.get("item_id", 0) or 0), {})
        normalized_item = cast(ReviewRowPayload, dict(item))
        normalized_item["quick_fix_actions"] = cast(
            list[dict[str, object]], _as_list(row.get("quick_fix_actions", []))
        )
        normalized_item["bulk_fix_groups"] = cast(
            list[dict[str, object]], _as_list(row.get("bulk_fix_groups", []))
        )
        normalized_item["reclassify_options"] = [
            str(value) for value in _as_list(row.get("reclassify_options", []))
        ]
        normalized_items.append(normalized_item)
    return normalized_items, legacy_rows


__all__ = [
    "build_compatibility_review_row",
    "enrich_review_items",
]
