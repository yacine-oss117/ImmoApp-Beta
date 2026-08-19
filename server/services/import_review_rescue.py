"""Helpers for rescue-mode review UX and bulk correction expansion."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from server.services.import_agency_memory import alias_domain_for_field, normalize_alias_value
from server.services.import_review_shapes import review_row_key


def _price_candidate_label(candidate: Mapping[str, Any]) -> str:
    dialect = str(candidate.get("dialect", "") or "").strip()
    return {
        "dzd_millions": "Treat as DZD millions",
        "centime_millions": "Treat as local centime millions",
        "centime_milliards": "Treat as local centime milliards",
        "dzd_thousands": "Treat as DZD thousands",
        "raw_dzd": "Treat as DZD",
        "centime_scalar": "Treat as centimes",
    }.get(dialect, "Use this price")


def _price_review_fields(
    review_row: Mapping[str, Any],
) -> list[tuple[str, str, list[dict[str, Any]]]]:
    rows: list[tuple[str, str, list[dict[str, Any]]]] = []
    for field in list(review_row.get("review_fields", []) or []):
        if not isinstance(field, Mapping):
            continue
        field_name = str(field.get("field", "") or "").strip()
        original = str(field.get("original", "") or "").strip()
        metadata = dict(field.get("metadata", {}) or {})
        candidates = [
            dict(candidate)
            for candidate in list(metadata.get("interpretation_candidates", []) or [])
            if isinstance(candidate, Mapping)
        ]
        if field_name and original and candidates:
            rows.append((field_name, original, candidates))
    return rows


def build_quick_fix_actions(review_row: Mapping[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for candidate in list(review_row.get("recovery_candidates", []) or []):
        field_name = str(candidate.get("field", "") or "")
        candidate_label = str(candidate.get("candidate_label", "") or "")
        candidate_value = candidate.get("candidate_value")
        if not field_name or candidate_value in {None, ""}:
            continue
        actions.append(
            {
                "field": field_name,
                "label": f"Use {candidate_label or candidate_value}",
                "candidate_value": candidate_value,
            }
        )
    seen_price_actions: set[tuple[str, str]] = set()
    for field_name, _original, candidates in _price_review_fields(review_row):
        for candidate in candidates:
            candidate_value = candidate.get("normalized_dzd")
            if candidate_value in {None, ""}:
                continue
            label = _price_candidate_label(candidate)
            dedupe_key = (field_name, label)
            if dedupe_key in seen_price_actions:
                continue
            seen_price_actions.add(dedupe_key)
            actions.append(
                {
                    "field": field_name,
                    "label": label,
                    "candidate_value": candidate_value,
                }
            )
    return actions


def build_bulk_fix_groups(review_rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for review_row in review_rows:
        row_num = int(review_row.get("row", 0) or 0)
        original = dict(review_row.get("raw_data") or review_row.get("original") or {})
        normalized = dict(review_row.get("normalized_data") or review_row.get("data") or {})
        for candidate in list(review_row.get("recovery_candidates", []) or []):
            field_name = str(candidate.get("field", "") or "")
            if not field_name:
                continue
            source_value = str(
                original.get(field_name, "") or normalized.get(field_name, "") or ""
            ).strip()
            if not source_value:
                continue
            domain = alias_domain_for_field(field_name) or "location"
            group_key = (field_name, normalize_alias_value(domain, source_value))
            group = grouped.setdefault(
                group_key,
                {
                    "group_key": f"{field_name}:{group_key[1]}",
                    "field": field_name,
                    "source_value": source_value,
                    "occurrence_count": 0,
                    "suggested_candidate_label": str(
                        candidate.get("candidate_label", "") or candidate.get("candidate_value", "")
                    ),
                    "suggested_candidate_value": candidate.get("candidate_value"),
                    "target_rows": [],
                },
            )
            group["occurrence_count"] += 1
            group["target_rows"].append(row_num)
        for field_name, original_value, candidates in _price_review_fields(review_row):
            domain = alias_domain_for_field(field_name) or "price"
            normalized_source = normalize_alias_value(domain, original_value)
            if not normalized_source:
                continue
            for candidate in candidates:
                candidate_value = candidate.get("normalized_dzd")
                if candidate_value in {None, ""}:
                    continue
                dialect = str(candidate.get("dialect", "") or "").strip()
                label = _price_candidate_label(candidate)
                group_key = (f"{field_name}:{dialect}", normalized_source)
                group = grouped.setdefault(
                    group_key,
                    {
                        "group_key": f"{field_name}:{normalized_source}:{dialect}",
                        "field": field_name,
                        "source_value": original_value,
                        "occurrence_count": 0,
                        "suggested_candidate_label": label,
                        "suggested_candidate_value": candidate_value,
                        "target_rows": [],
                    },
                )
                group["occurrence_count"] += 1
                group["target_rows"].append(row_num)
    return [
        dict(group) for group in grouped.values() if int(group.get("occurrence_count", 0) or 0) >= 2
    ]


def bulk_fix_groups_for_row(
    review_row: Mapping[str, Any],
    bulk_fix_groups: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    row_num = int(review_row.get("row", 0) or 0)
    relevant: list[dict[str, Any]] = []
    for group in bulk_fix_groups:
        target_rows = [int(value) for value in list(group.get("target_rows", []) or [])]
        if row_num in target_rows:
            relevant.append(dict(group))
    return relevant


def expand_bulk_operations(
    *,
    review_rows: Iterable[Mapping[str, Any]],
    corrections: Mapping[str, dict[str, Any]] | None,
    bulk_operations: Iterable[Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    expanded = {str(key): dict(value) for key, value in dict(corrections or {}).items()}
    row_lookup: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in review_rows:
        if not isinstance(row, Mapping):
            continue
        row_lookup[int(row.get("row", 0) or 0)].append(dict(row))
    for operation in bulk_operations or []:
        if str(operation.get("operation", "") or "") != "replace_value_in_import":
            continue
        field_name = str(operation.get("field", "") or "").strip()
        replacement_value = operation.get("replacement_value")
        if not field_name or replacement_value in {None, ""}:
            continue
        for row_num in [int(value) for value in list(operation.get("target_rows", []) or [])]:
            for row_entry in row_lookup.get(row_num, []):
                row_key = review_row_key(
                    row_num=row_num,
                    entity_type=str(row_entry.get("entity_type", "") or ""),
                )
                original_payload = dict(
                    row_entry.get("normalized_data") or row_entry.get("data") or {}
                )
                corrected_payload = dict(expanded.get(row_key, original_payload))
                corrected_payload[field_name] = replacement_value
                expanded[row_key] = corrected_payload
    return expanded


def allowed_reclassify_options(
    *,
    bundle_mode: str,
    topology_side: str,
    entity_type: str,
) -> list[str]:
    if bundle_mode == "same_side_bundle":
        if topology_side == "client_side":
            return ["client", "demande"]
        if topology_side == "listing_side":
            return ["listing", "offer"]
    return [entity_type] if entity_type else []


__all__ = [
    "allowed_reclassify_options",
    "build_bulk_fix_groups",
    "build_quick_fix_actions",
    "bulk_fix_groups_for_row",
    "expand_bulk_operations",
]
