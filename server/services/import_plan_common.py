"""Shared helpers for importer planning flows."""

from __future__ import annotations

from collections.abc import Callable

from core.importer.normalize_pipeline import NormalizedRow
from server.services.import_agency_memory import AgencyAliasMemory
from server.services.import_identity_resolution import ResolutionResult
from server.services.import_recovery import apply_row_recovery
from server.services.import_review_row_runtime import anchor_map_keys

PlanningRecoveryFn = Callable[..., dict[str, object]]
BlockedDuplicateResolutionErrorFn = Callable[..., dict[str, object]]
PrefetchRootMatchCacheFn = Callable[..., None]
PrefetchChildMatchCacheFn = Callable[..., None]
ResolveChildAnchorFn = Callable[..., int]
ValidateRowFn = Callable[[dict[str, object], str], tuple[dict[str, object], list[str]]]
ResolveExistingMatchesFn = Callable[..., ResolutionResult]


def matching_anchor_key(row_data: dict[str, object], known_anchor_keys: set[str]) -> str:
    for key in anchor_map_keys(row_data):
        if key in known_anchor_keys:
            return key
    return ""


def blocked_duplicate_resolution_error(*, row_num: int, resolution: object) -> dict[str, object]:
    suggested_reasons = [
        str(reason).strip()
        for reason in list(getattr(resolution, "suggested_reasons", []) or [])
        if str(reason).strip()
    ]
    low_signal_reasons = {
        "same phone",
        "same name",
        "very similar name",
        "similar name",
        "active record",
    }
    primary_reason = suggested_reasons[0] if suggested_reasons else ""
    message = (
        primary_reason
        if primary_reason.casefold() not in low_signal_reasons
        else "This line matches existing records in your agency and needs review."
    )
    return {"row": row_num, "errors": [message]}


def apply_planning_recovery(
    *,
    row_data: dict[str, object],
    original: dict[str, object],
    entity_type: str,
    column_types: dict[str, str],
    agency_memory: AgencyAliasMemory | None,
    bundle_context: dict[str, object] | None = None,
) -> dict[str, object]:
    normalized = NormalizedRow(data=dict(row_data))
    recovered = apply_row_recovery(
        normalized=normalized,
        raw_row=original,
        entity_type=entity_type,
        column_types=column_types,
        memory=agency_memory,
        bundle_context=bundle_context,
    )
    return dict(recovered.data)


__all__ = [
    "BlockedDuplicateResolutionErrorFn",
    "PlanningRecoveryFn",
    "PrefetchChildMatchCacheFn",
    "PrefetchRootMatchCacheFn",
    "ResolveChildAnchorFn",
    "ResolveExistingMatchesFn",
    "ValidateRowFn",
    "apply_planning_recovery",
    "blocked_duplicate_resolution_error",
    "matching_anchor_key",
]
