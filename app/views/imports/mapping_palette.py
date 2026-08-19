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


def _candidate_entities(*, topology_side_hint: str, detected_entity: str) -> list[str]:
    if topology_side_hint == "client_side" or detected_entity in {"client", "demande"}:
        return ["client", "demande"]
    if topology_side_hint == "listing_side" or detected_entity in {"listing", "offer"}:
        return ["listing", "offer"]
    if detected_entity:
        return [detected_entity]
    return []


def _field_signals(
    *,
    detected_columns: Iterable[Mapping[str, object]],
    column_mapping: Mapping[str, str],
) -> set[str]:
    signals: set[str] = set()
    for item in detected_columns:
        detected_type = _normalized_text(item.get("detected_type"))
        header = _normalized_text(item.get("header"))
        if detected_type and detected_type != "unknown":
            signals.add(_ALIASES.get(detected_type, detected_type))
        if header:
            signals.add(_ALIASES.get(header, header))
    for field_name in column_mapping:
        normalized = _normalized_text(field_name)
        if normalized:
            signals.add(_ALIASES.get(normalized, normalized))
    return signals


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
    selected_sheet_name: object,
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


def derive_mapping_palette_state(
    *,
    bundle_mode: object,
    topology_side_hint: object,
    detected_entity: object,
    manual_mapping_required: bool,
    detected_columns: Iterable[Mapping[str, object]],
    column_mapping: Mapping[str, str],
    sheet_profiles: Iterable[Mapping[str, object]] | None = None,
    selected_sheet_name: object = "",
) -> tuple[str, list[str]]:
    normalized_bundle_mode = _normalized_text(bundle_mode) or "single_entity"
    normalized_side = _normalized_text(topology_side_hint) or "unknown"
    normalized_entity = _normalized_text(detected_entity)
    candidates = _candidate_entities(
        topology_side_hint=normalized_side,
        detected_entity=normalized_entity,
    )
    signals = _field_signals(
        detected_columns=detected_columns,
        column_mapping=column_mapping,
    )
    if _has_conflicting_sheet_profiles(
        sheet_profiles=sheet_profiles,
        selected_sheet_name=selected_sheet_name,
    ):
        return "entity_only", candidates
    if normalized_bundle_mode == "same_side_bundle" and len(candidates) == 2:
        return "same_side_union", candidates
    if (
        manual_mapping_required
        and normalized_bundle_mode != "mixed_blocked"
        and len(candidates) == 2
        and (
            bool(signals.intersection(_CLIENT_CHILD_SIGNALS))
            or bool(signals.intersection(_LISTING_CHILD_SIGNALS))
        )
    ):
        return "recovery_union", candidates
    return "entity_only", candidates


__all__ = ["derive_mapping_palette_state"]
