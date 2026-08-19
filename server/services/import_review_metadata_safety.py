"""Safe metadata projection helpers for review payloads."""

from __future__ import annotations

from collections.abc import Mapping

PROTECTED_REVIEW_PAYLOAD_KEYS = frozenset(
    {
        "item_id",
        "group_key",
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
        "status",
        "group_resolvable",
        "group_resolution_blockers",
        "resolution_source",
        "effective_action",
        "metadata",
    }
)
PROMOTED_REVIEW_METADATA_KEYS: frozenset[str] = frozenset()


def non_shadowing_review_metadata(metadata: object) -> dict[str, object]:
    if not isinstance(metadata, Mapping):
        return {}
    return {
        str(key): value
        for key, value in metadata.items()
        if str(key) not in PROTECTED_REVIEW_PAYLOAD_KEYS
    }


def project_review_metadata(
    row: Mapping[str, object],
    metadata: object,
) -> dict[str, object]:
    projected = dict(row)
    safe_metadata = non_shadowing_review_metadata(metadata)
    raw_existing_metadata = projected.get("metadata", {})
    existing_metadata = (
        dict(raw_existing_metadata) if isinstance(raw_existing_metadata, Mapping) else {}
    )
    if safe_metadata:
        existing_metadata.update(safe_metadata)
    projected["metadata"] = existing_metadata
    for key in PROMOTED_REVIEW_METADATA_KEYS:
        if key in safe_metadata and key not in projected:
            projected[key] = safe_metadata[key]
    return projected


__all__ = [
    "PROMOTED_REVIEW_METADATA_KEYS",
    "PROTECTED_REVIEW_PAYLOAD_KEYS",
    "non_shadowing_review_metadata",
    "project_review_metadata",
]
