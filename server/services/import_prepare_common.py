"""Shared helpers for importer prepare flows."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from server.imports.models import ImportDeadLetterRow, ImportJob
from server.services.import_agency_memory import (
    AgencyAliasMemory,
    alias_domain_for_column_type,
    load_agency_alias_memory,
)
from server.services.import_dead_letter import build_dead_letter_row
from server.services.import_review_row_runtime import normalized_review_fields
from server.services.import_types import ImportResult, ReviewFieldPayload


class DownloadToTemp(Protocol):
    def __call__(self, storage_id: str, *, suffix: str | None = None) -> Path: ...


InferRowEntityFn = Callable[..., Any]


def agency_memory(job: ImportJob, column_types: dict[str, str]) -> AgencyAliasMemory:
    return load_agency_alias_memory(
        int(getattr(job, "agency_id", 0) or 0),
        domains={
            domain
            for domain in (
                alias_domain_for_column_type(column_type) for column_type in column_types.values()
            )
            if domain
        },
    )


def selected_sheet_name(job: ImportJob) -> str | None:
    selected = str((job.inference_summary or {}).get("selected_sheet_name", "") or "").strip()
    return selected or None


def normalized_review_fields_or_validation(normalized: Any) -> list[ReviewFieldPayload]:
    review_fields = normalized_review_fields(normalized)
    if review_fields:
        return review_fields
    blocking_reasons = list(getattr(normalized, "blocking_reasons", []) or [])
    if blocking_reasons:
        return [
            {
                "field": "validation",
                "original": "",
                "normalized": "",
                "confidence": 0.0,
                "remark": "; ".join(
                    str(reason) for reason in blocking_reasons if str(reason).strip()
                ),
            }
        ]
    return []


def _normalize_root_compare_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value).strip().casefold()


def bundle_row_has_root_identity(row_data: dict[str, Any]) -> bool:
    return any(
        _normalize_root_compare_value(row_data.get(field))
        for field in ("family_name", "name", "email", "phone")
    )


def duplicate_root_conflict_fields(
    existing_row: dict[str, Any],
    incoming_row: dict[str, Any],
) -> list[str]:
    conflicts: list[str] = []
    for field in ("family_name", "name", "email"):
        existing_value = _normalize_root_compare_value(existing_row.get(field))
        incoming_value = _normalize_root_compare_value(incoming_row.get(field))
        if not incoming_value:
            continue
        if not existing_value or existing_value != incoming_value:
            conflicts.append(field)
    return conflicts


_BUNDLE_ROOT_FIELDS = {
    "family_name",
    "name",
    "email",
    "phone",
    "remarks",
    "tags",
    "status",
    "is_vip",
}
_CLIENT_CHILD_FIELDS = {
    "client_id",
    "action",
    "type",
    "type_id",
    "action_id",
    "wilaya",
    "wilaya_id",
    "locations",
    "budget_min",
    "budget_max",
    "surface_min",
    "surface_max",
    "beds_min",
    "floor_min",
    "floor_max",
    "furnished",
    "elevator",
    "accessibility_required",
    "remarks",
}
_LISTING_CHILD_FIELDS = {
    "listing_id",
    "action",
    "type",
    "type_id",
    "action_id",
    "wilaya",
    "wilaya_id",
    "location",
    "budget",
    "surface",
    "beds",
    "floor",
    "furnished",
    "elevator",
    "accessibility_supported",
    "price_negotiable",
    "price_flex_pct",
    "link",
    "latitude",
    "longitude",
    "remarks",
}
_BUNDLE_CHILD_FIELDS_BY_SIDE = {
    "client_side": _CLIENT_CHILD_FIELDS,
    "listing_side": _LISTING_CHILD_FIELDS,
}


def bundle_root_payload(row_data: dict[str, Any]) -> dict[str, Any]:
    return {field: value for field, value in row_data.items() if field in _BUNDLE_ROOT_FIELDS}


def bundle_child_payload(
    row_data: dict[str, Any],
    *,
    topology_side: str,
) -> dict[str, Any]:
    allowed_fields = _BUNDLE_CHILD_FIELDS_BY_SIDE.get(topology_side)
    if not allowed_fields:
        return dict(row_data)
    return {field: value for field, value in row_data.items() if field in allowed_fields}


def append_prepare_dead_letter(
    *,
    rows: list[ImportDeadLetterRow],
    job: ImportJob,
    row_num: int,
    entity_type: str,
    topology_side: str,
    raw_row: dict[str, Any],
    normalized_data: dict[str, Any],
    recoverability_class: str,
    recovered_fields: list[dict[str, Any]],
    recovery_candidates: list[dict[str, Any]],
    blocking_reasons: list[str],
    disposition: str,
    reason_codes: list[str],
    reason_messages: list[str],
) -> None:
    rows.append(
        build_dead_letter_row(
            job=job,
            row_ordinal=row_num,
            disposition=disposition,
            phase="plan",
            entity_type=entity_type,
            topology_side=topology_side,
            raw_data=raw_row,
            normalized_data=normalized_data,
            recoverability_class=recoverability_class,
            recovered_fields=recovered_fields,
            recovery_candidates=recovery_candidates,
            blocking_reasons=blocking_reasons,
            reason_codes=reason_codes,
            reason_messages=reason_messages,
        )
    )


def merge_dead_letter_summary(result: ImportResult, summary: dict[str, int]) -> None:
    merged = {
        str(key): int(value)
        for key, value in dict(result.dead_letter_summary or {}).items()
        if isinstance(value, (int, float))
    }
    for key, value in dict(summary or {}).items():
        if not isinstance(value, (int, float)):
            continue
        key_text = str(key)
        merged[key_text] = merged.get(key_text, 0) + int(value)
    result.dead_letter_summary = merged


__all__ = [
    "DownloadToTemp",
    "InferRowEntityFn",
    "agency_memory",
    "append_prepare_dead_letter",
    "bundle_child_payload",
    "bundle_root_payload",
    "bundle_row_has_root_identity",
    "duplicate_root_conflict_fields",
    "merge_dead_letter_summary",
    "normalized_review_fields_or_validation",
    "selected_sheet_name",
]
