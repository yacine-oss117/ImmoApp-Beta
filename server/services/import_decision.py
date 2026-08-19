"""Normalized importer decision engine shared across preview and execute."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from server.services.import_mapping import build_column_types
from server.services.import_mapping_gate import evaluate_manual_mapping_gate
from server.services.import_mapping_palette import derive_mapping_palette
from server.services.import_parsers import normalize_import_entity_type
from server.services.import_type_inference import unsupported_child_only_import_message
from server.services.import_types import ImportDecision


def _normalized_text(value: object) -> str:
    return str(value or "").strip().lower()


def _coerce_float(value: object) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _coerce_summary(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        if isinstance(item, bool):
            result[str(key)] = int(item)
        elif isinstance(item, (int, float)):
            result[str(key)] = int(item)
    return result


def _preview_requires_review(
    *,
    preview_rows: Iterable[Mapping[str, object]] | None,
    recoverability_summary: Mapping[str, object] | None,
    preview_attention_summary: Mapping[str, object] | None,
) -> bool:
    for row in preview_rows or []:
        if bool(row.get("needs_review", False)):
            return True
        blocking_reasons = row.get("blocking_reasons", [])
        if isinstance(blocking_reasons, list) and blocking_reasons:
            return True
    summary = _coerce_summary(recoverability_summary)
    attention = _coerce_summary(preview_attention_summary)
    return (
        int(summary.get("review_recoverable", 0) or 0) > 0
        or int(summary.get("blocking", 0) or 0) > 0
        or int(attention.get("needs_attention", 0) or 0) > 0
        or int(attention.get("blocking", 0) or 0) > 0
    )


def _dedupe_reason_codes(values: Iterable[object]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        code = _normalized_text(item)
        if not code or code in seen:
            continue
        seen.add(code)
        normalized.append(code)
    return normalized


def build_import_decision(
    *,
    final_inference: Mapping[str, object],
    detected_columns: Iterable[Mapping[str, object]],
    column_mapping: Mapping[str, str] | None,
    detected_entity: str = "",
    sheet_profiles: Iterable[Mapping[str, object]] | None = None,
    selected_sheet_name: str = "",
    preview_rows: Iterable[Mapping[str, object]] | None = None,
    recoverability_summary: Mapping[str, object] | None = None,
    preview_attention_summary: Mapping[str, object] | None = None,
) -> ImportDecision:
    normalized_final_inference = dict(final_inference or {})
    resolved_entity = normalize_import_entity_type(
        str(normalized_final_inference.get("detected_entity") or detected_entity or "")
    )
    normalized_final_inference.setdefault("detected_entity", resolved_entity)
    normalized_final_inference.setdefault("selected_sheet_name", str(selected_sheet_name or ""))

    column_types = build_column_types(
        detected_columns=[dict(item) for item in detected_columns],
        column_mapping={str(key): str(value) for key, value in (column_mapping or {}).items()},
    )
    manual_mapping_required, manual_mapping_reasons, gate_metrics = evaluate_manual_mapping_gate(
        detected_columns=detected_columns,
        final_inference=normalized_final_inference,
        column_types=column_types,
        sheet_profiles=sheet_profiles,
    )
    palette = derive_mapping_palette(
        final_inference=normalized_final_inference,
        detected_columns=detected_columns,
        column_mapping=column_mapping,
        manual_mapping_required=manual_mapping_required,
        detected_entity=resolved_entity,
        sheet_profiles=sheet_profiles,
        selected_sheet_name=str(selected_sheet_name or ""),
    )

    bundle_mode = _normalized_text(normalized_final_inference.get("bundle_mode")) or "single_entity"
    topology_side_hint = (
        _normalized_text(normalized_final_inference.get("topology_side_hint")) or "unknown"
    )
    confidence = _coerce_float(normalized_final_inference.get("confidence"))
    raw_reason_codes = gate_metrics.get("reason_codes", [])
    reason_codes = _dedupe_reason_codes(
        raw_reason_codes if isinstance(raw_reason_codes, list) else []
    )
    unsupported_message = unsupported_child_only_import_message(
        {
            **normalized_final_inference,
            "detected_entity": resolved_entity,
        }
    )

    review_required = _preview_requires_review(
        preview_rows=preview_rows,
        recoverability_summary=recoverability_summary,
        preview_attention_summary=preview_attention_summary,
    )
    blocking_message = ""
    outcome = "auto_import"
    if unsupported_message:
        outcome = "block"
        blocking_message = unsupported_message
        reason_codes = _dedupe_reason_codes([*reason_codes, "unsupported_child_only"])
    elif bundle_mode == "mixed_blocked":
        outcome = "block"
        blocking_message = (
            "This file mixes client-side and listing-side rows. Split it before execution."
        )
        reason_codes = _dedupe_reason_codes([*reason_codes, "mixed_side_contamination"])
    elif "workbook_conflict" in reason_codes and not str(selected_sheet_name or "").strip():
        outcome = "block"
        blocking_message = "Workbook sheets conflict and need manual sheet selection."
    elif manual_mapping_required:
        outcome = "manual_mapping"
    elif review_required:
        outcome = "review"
        reason_codes = _dedupe_reason_codes([*reason_codes, "preview_review_required"])

    return ImportDecision(
        outcome=outcome,
        confidence=confidence,
        detected_entity=resolved_entity,
        topology_side_hint=topology_side_hint,
        bundle_mode=bundle_mode,
        mapping_palette_mode=str(
            palette.get("mapping_palette_mode", "entity_only") or "entity_only"
        ),
        reason_codes=reason_codes,
        recoverability_summary=_coerce_summary(recoverability_summary),
        metrics=dict(gate_metrics),
        manual_mapping_required=manual_mapping_required,
        manual_mapping_reasons=[str(value) for value in manual_mapping_reasons],
        review_required=review_required,
        blocking_message=blocking_message,
    )


__all__ = ["build_import_decision"]
