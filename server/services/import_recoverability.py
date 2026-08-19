"""Recoverability classification for importer rows."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from core.importer.normalize_pipeline import NormalizedRow
from server.services.import_constants import (
    ENTITY_TYPE_CLIENT,
    ENTITY_TYPE_DEMANDE,
    ENTITY_TYPE_LISTING,
    ENTITY_TYPE_OFFER,
)
from server.services.import_types import (
    RECOVERABILITY_AUTO,
    RECOVERABILITY_BLOCKING,
    RECOVERABILITY_REVIEW,
)

_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    ENTITY_TYPE_CLIENT: ("family_name", "phone"),
    ENTITY_TYPE_LISTING: ("phone",),
    ENTITY_TYPE_DEMANDE: ("action", "type", "wilaya"),
    ENTITY_TYPE_OFFER: (
        "action",
        "type",
        "wilaya",
        "location",
        "budget",
        "surface",
        "beds",
        "floor",
    ),
}

_RELATED_RECOVERY_FIELDS: dict[str, tuple[str, ...]] = {
    "wilaya": ("wilaya", "location", "locations"),
    "location": ("location", "locations"),
}


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _has_recovery_path(normalized: NormalizedRow, field_name: str) -> bool:
    related_fields = _RELATED_RECOVERY_FIELDS.get(field_name, (field_name,))
    for item in normalized.recovered_fields or ():
        if str(item.get("field", "") or "") in related_fields:
            return True
    for item in normalized.recovery_candidates or ():
        if str(item.get("field", "") or "") in related_fields:
            return True
    for review_field in normalized.review_fields or ():
        if str(review_field.field_name or "") in related_fields:
            return True
    return False


def _deferred_required_fields(fields: Iterable[str] | None) -> set[str]:
    return {str(field).strip() for field in (fields or ()) if str(field).strip()}


def blocking_reasons_for_row(
    normalized: NormalizedRow,
    *,
    entity_type: str,
    deferred_required_fields: Iterable[str] | None = None,
) -> list[str]:
    reasons = list(normalized.blocking_reasons or [])
    deferred = _deferred_required_fields(deferred_required_fields)
    for field_name in _REQUIRED_FIELDS.get(entity_type, ()):
        if field_name in deferred:
            continue
        if not _has_value(normalized.data.get(field_name)):
            if _has_recovery_path(normalized, field_name):
                continue
            reasons.append(f"Missing required field: {field_name}")
    if entity_type == ENTITY_TYPE_DEMANDE:
        if not any(
            _has_value(normalized.data.get(field_name))
            for field_name in ("budget_min", "budget_max")
        ) and not (
            _has_recovery_path(normalized, "budget_min")
            or _has_recovery_path(normalized, "budget_max")
        ):
            reasons.append("Missing required field: budget")
        if not any(
            _has_value(normalized.data.get(field_name))
            for field_name in ("surface_min", "surface_max")
        ) and not (
            _has_recovery_path(normalized, "surface_min")
            or _has_recovery_path(normalized, "surface_max")
        ):
            reasons.append("Missing required field: surface")
    if entity_type == ENTITY_TYPE_CLIENT and not any(
        _has_value(normalized.data.get(field_name)) for field_name in ("family_name", "phone")
    ):
        reasons.append("No usable client root identity could be recovered.")
    if entity_type == ENTITY_TYPE_LISTING and not any(
        _has_value(normalized.data.get(field_name)) for field_name in ("phone", "family_name")
    ):
        reasons.append("No usable listing root identity could be recovered.")
    deduped: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        clean_reason = str(reason or "").strip()
        if clean_reason and clean_reason not in seen:
            seen.add(clean_reason)
            deduped.append(clean_reason)
    return deduped


def classify_row_recoverability(
    normalized: NormalizedRow,
    *,
    entity_type: str,
    deferred_required_fields: Iterable[str] | None = None,
) -> str:
    if blocking_reasons_for_row(
        normalized,
        entity_type=entity_type,
        deferred_required_fields=deferred_required_fields,
    ):
        return RECOVERABILITY_BLOCKING
    if normalized.recovery_candidates or normalized.needs_review:
        return RECOVERABILITY_REVIEW
    return RECOVERABILITY_AUTO


def recoverability_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        RECOVERABILITY_AUTO: 0,
        RECOVERABILITY_REVIEW: 0,
        RECOVERABILITY_BLOCKING: 0,
    }
    for row in rows:
        key = str(row.get("recoverability_class", RECOVERABILITY_AUTO) or RECOVERABILITY_AUTO)
        if key not in summary:
            summary[key] = 0
        summary[key] += 1
    return summary


__all__ = [
    "blocking_reasons_for_row",
    "classify_row_recoverability",
    "recoverability_summary",
]
