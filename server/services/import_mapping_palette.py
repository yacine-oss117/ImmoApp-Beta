"""Mapping-palette diagnostics for importer recovery flows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

_CLIENT_CHILD_SIGNALS = {
    "action",
    "type",
    "wilaya",
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
    "client_id",
}
_LISTING_CHILD_SIGNALS = {
    "action",
    "type",
    "wilaya",
    "location",
    "budget",
    "price",
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
    "listing_id",
}
_ALIASES = {
    "name": "family_name",
    "notes": "remarks",
    "price": "budget",
    "city": "wilaya",
}


def _normalized_text(value: object) -> str:
    return str(value or "").strip().lower()


def _field_signals(
    *,
    detected_columns: Iterable[Mapping[str, object]],
    column_mapping: Mapping[str, str] | None,
) -> set[str]:
    signals: set[str] = set()
    for item in detected_columns:
        detected_type = _normalized_text(item.get("detected_type"))
        header = _normalized_text(item.get("header"))
        if detected_type and detected_type != "unknown":
            signals.add(_ALIASES.get(detected_type, detected_type))
        if header:
            signals.add(_ALIASES.get(header, header))
    for field_name in (column_mapping or {}).keys():
        normalized = _normalized_text(field_name)
        if normalized:
            signals.add(_ALIASES.get(normalized, normalized))
    return signals


def _candidate_entities(
    *,
    topology_side_hint: str,
    detected_entity: str,
) -> list[str]:
    if topology_side_hint == "client_side" or detected_entity in {"client", "demande"}:
        return ["client", "demande"]
    if topology_side_hint == "listing_side" or detected_entity in {"listing", "offer"}:
        return ["listing", "offer"]
    if detected_entity:
        return [detected_entity]
    return []


def _profile_confidence(value: object) -> float:
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


def _has_conflicting_sheet_profiles(
    *,
    sheet_profiles: Iterable[Mapping[str, object]] | None,
    selected_sheet_name: str,
) -> bool:
    if str(selected_sheet_name or "").strip():
        return False
    normalized_sheet_profiles = [dict(item) for item in (sheet_profiles or [])]
    if len(normalized_sheet_profiles) <= 1:
        return False
    confident_profiles = [
        item
        for item in normalized_sheet_profiles
        if _profile_confidence(item.get("confidence", 0.0)) >= 0.55
    ]
    if len(confident_profiles) <= 1:
        return False
    dominant_sides = {
        _normalized_text(item.get("dominant_topology_side"))
        for item in confident_profiles
        if _normalized_text(item.get("dominant_topology_side")) != "unknown"
    }
    dominant_modes = {
        _normalized_text(item.get("dominant_bundle_mode")) or "single_entity"
        for item in confident_profiles
    }
    return len(dominant_sides) > 1 or len(dominant_modes) > 1


def derive_mapping_palette(
    *,
    final_inference: Mapping[str, object],
    detected_columns: Iterable[Mapping[str, object]],
    column_mapping: Mapping[str, str] | None = None,
    manual_mapping_required: bool = False,
    detected_entity: str = "",
    sheet_profiles: Iterable[Mapping[str, object]] | None = None,
    selected_sheet_name: str = "",
) -> dict[str, object]:
    bundle_mode = _normalized_text(final_inference.get("bundle_mode")) or "single_entity"
    topology_side_hint = _normalized_text(final_inference.get("topology_side_hint")) or "unknown"
    resolved_entity = _normalized_text(final_inference.get("detected_entity")) or _normalized_text(
        detected_entity
    )
    candidate_entities = _candidate_entities(
        topology_side_hint=topology_side_hint,
        detected_entity=resolved_entity,
    )
    signals = _field_signals(detected_columns=detected_columns, column_mapping=column_mapping)

    mode = "entity_only"
    reason = "Only the inferred entity fields are available for this file."
    if _has_conflicting_sheet_profiles(
        sheet_profiles=sheet_profiles,
        selected_sheet_name=str(selected_sheet_name or ""),
    ):
        reason = "Workbook sheets conflict, so manual sheet selection is required before recovery fields can open."
    elif bundle_mode == "same_side_bundle" and len(candidate_entities) == 2:
        mode = "same_side_union"
        reason = "This file is already classified as a same-side bundle."
    elif (
        manual_mapping_required
        and bundle_mode != "mixed_blocked"
        and len(candidate_entities) == 2
        and (
            bool(signals.intersection(_CLIENT_CHILD_SIGNALS))
            or bool(signals.intersection(_LISTING_CHILD_SIGNALS))
        )
    ):
        mode = "recovery_union"
        reason = "This file may include both root and child rows on the same side, so extra field choices are available for manual recovery."

    return {
        "mapping_palette_mode": mode,
        "mapping_palette_reason": reason,
        "mapping_candidate_entities": candidate_entities,
    }


__all__ = ["derive_mapping_palette"]
