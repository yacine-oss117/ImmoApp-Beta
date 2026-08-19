"""Manual-mapping gate for highly chaotic imports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

_CONFIDENT_MAPPING_THRESHOLD = 0.8
_CONFIDENT_MAPPING_RATIO_MIN = 0.40
_INFERENCE_CONFIDENCE_MIN = 0.55

_BUNDLE_IDENTITY_TYPES = {"phone", "name"}
_BUNDLE_CHILD_TYPES_BY_SIDE: dict[str, set[str]] = {
    "client_side": {
        "action",
        "type",
        "location",
        "wilaya",
        "price",
        "surface",
        "beds_min",
        "floor_min",
        "floor_max",
        "furnished",
        "elevator",
        "accessibility_required",
    },
    "listing_side": {
        "action",
        "type",
        "location",
        "wilaya",
        "price",
        "surface",
        "beds",
        "floor",
        "furnished",
        "elevator",
        "accessibility_supported",
        "price_negotiable",
        "link",
        "latitude",
        "longitude",
    },
}


def _normalized_detected_columns(
    detected_columns: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in detected_columns:
        rows.append(dict(item))
    return rows


def _column_detected_type(column: Mapping[str, object]) -> str:
    return str(column.get("detected_type", "unknown") or "unknown").strip().lower()


def _column_confidence(column: Mapping[str, object]) -> float:
    raw_value = column.get("confidence", 0.0)
    if isinstance(raw_value, bool):
        return float(int(raw_value))
    if isinstance(raw_value, (int, float)):
        return float(raw_value)
    if isinstance(raw_value, str):
        try:
            return float(raw_value)
        except ValueError:
            return 0.0
    return 0.0


def _bundle_child_types(topology_side: str) -> set[str]:
    return set(_BUNDLE_CHILD_TYPES_BY_SIDE.get(str(topology_side or "").strip().lower(), set()))


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


def _normalized_mapping_types(column_types: Mapping[str, str] | None) -> set[str]:
    return {
        str(item).strip().lower()
        for item in (column_types or {}).values()
        if str(item or "").strip()
    }


def _append_reason(
    reasons: list[str],
    reason_codes: list[str],
    *,
    message: str,
    code: str,
) -> None:
    reasons.append(message)
    if code not in reason_codes:
        reason_codes.append(code)


def _explicit_same_side_recovery_confirmed(
    *,
    explicit_mapping_confirmed: bool,
    topology_side: str,
    inferred_types: set[str],
    conflicting_sheet_profiles: bool,
    bundle_mode: str,
) -> bool:
    if not explicit_mapping_confirmed:
        return False
    if conflicting_sheet_profiles or bundle_mode == "mixed_blocked":
        return False
    if topology_side not in {"client_side", "listing_side"}:
        return False
    return bool(
        inferred_types.intersection(_BUNDLE_IDENTITY_TYPES)
        and inferred_types.intersection(_bundle_child_types(topology_side))
    )


def evaluate_manual_mapping_gate(
    *,
    detected_columns: Iterable[Mapping[str, object]],
    final_inference: Mapping[str, object],
    column_types: Mapping[str, str] | None = None,
    sheet_profiles: Iterable[Mapping[str, object]] | None = None,
) -> tuple[bool, list[str], dict[str, object]]:
    columns = _normalized_detected_columns(detected_columns)
    mapped_types = _normalized_mapping_types(column_types)
    meaningful_mapped_types = {item for item in mapped_types if item != "unknown"}
    explicit_mapping_confirmed = len(meaningful_mapped_types) >= 2
    if mapped_types:
        # Column mapping exists; treat mapped fields as detected.
        inferred_types = meaningful_mapped_types
        confident_count = len(meaningful_mapped_types)
        total_count = max(len(columns), len(mapped_types))
    else:
        inferred_types = {_column_detected_type(column) for column in columns}
        confident_count = sum(
            1
            for column in columns
            if _column_detected_type(column) != "unknown"
            and _column_confidence(column) >= _CONFIDENT_MAPPING_THRESHOLD
        )
        total_count = len(columns)

    final_confidence_raw = final_inference.get("confidence", 0.0)
    if isinstance(final_confidence_raw, bool):
        final_confidence = float(int(final_confidence_raw))
    elif isinstance(final_confidence_raw, (int, float)):
        final_confidence = float(final_confidence_raw)
    elif isinstance(final_confidence_raw, str):
        try:
            final_confidence = float(final_confidence_raw)
        except ValueError:
            final_confidence = 0.0
    else:
        final_confidence = 0.0
    topology_side = str(final_inference.get("topology_side_hint", "unknown") or "unknown")
    bundle_mode = str(final_inference.get("bundle_mode", "single_entity") or "single_entity")
    confident_ratio = (confident_count / max(1, total_count)) if total_count else 0.0
    detected_types = {_column_detected_type(column) for column in columns}
    child_signal_detected = bool(
        detected_types.intersection(_bundle_child_types(topology_side))
        or inferred_types.intersection(_bundle_child_types(topology_side))
    )
    bundle_identity_present = bool(inferred_types.intersection(_BUNDLE_IDENTITY_TYPES))
    bundle_child_signal_present = bool(
        inferred_types.intersection(_bundle_child_types(topology_side))
    )
    if bundle_mode == "same_side_bundle":
        unknown_required_ratio = (
            1.0 if not bundle_child_signal_present or not bundle_identity_present else 0.0
        )
    else:
        unknown_required_ratio = 0.0
    normalized_sheet_profiles = [dict(item) for item in (sheet_profiles or [])]
    conflicting_sheet_profiles = False
    if len(normalized_sheet_profiles) > 1:
        confident_profiles = [
            item
            for item in normalized_sheet_profiles
            if _profile_confidence(item.get("confidence", 0.0)) >= _INFERENCE_CONFIDENCE_MIN
        ]
        dominant_sides = {
            str(item.get("dominant_topology_side", "unknown") or "unknown")
            for item in confident_profiles
            if str(item.get("dominant_topology_side", "unknown") or "unknown") != "unknown"
        }
        dominant_modes = {
            str(item.get("dominant_bundle_mode", "single_entity") or "single_entity")
            for item in confident_profiles
        }
        conflicting_sheet_profiles = len(dominant_sides) > 1 or len(dominant_modes) > 1

    reasons: list[str] = []
    reason_codes: list[str] = []
    if confident_ratio < _CONFIDENT_MAPPING_RATIO_MIN:
        _append_reason(
            reasons,
            reason_codes,
            message="Too few columns have strong semantic confidence.",
            code="low_mapping_confidence",
        )
    if bundle_mode == "same_side_bundle":
        if not bundle_identity_present:
            _append_reason(
                reasons,
                reason_codes,
                message=(
                    "Too few root identity columns are mapped for the inferred same-side bundle."
                ),
                code="missing_bundle_root_identity",
            )
        if not bundle_child_signal_present:
            _append_reason(
                reasons,
                reason_codes,
                message=(
                    "Too few child-side columns are mapped for the inferred same-side bundle."
                ),
                code="missing_bundle_child_signal",
            )
    if final_confidence < _INFERENCE_CONFIDENCE_MIN:
        _append_reason(
            reasons,
            reason_codes,
            message="File type inference confidence is too low for safe auto-execution.",
            code="low_inference_confidence",
        )
    if bundle_mode == "mixed_blocked":
        _append_reason(
            reasons,
            reason_codes,
            message="File mixes client-side and listing-side semantics.",
            code="mixed_side_contamination",
        )
    if conflicting_sheet_profiles and not str(final_inference.get("selected_sheet_name", "") or ""):
        _append_reason(
            reasons,
            reason_codes,
            message="Workbook sheets conflict and need manual sheet selection.",
            code="workbook_conflict",
        )
    allow_explicit_override = (
        explicit_mapping_confirmed
        and bundle_mode == "single_entity"
        and confident_ratio >= 0.75
        and not child_signal_detected
        and not conflicting_sheet_profiles
    )
    same_side_recovery_confirmed = _explicit_same_side_recovery_confirmed(
        explicit_mapping_confirmed=explicit_mapping_confirmed,
        topology_side=topology_side,
        inferred_types=inferred_types,
        conflicting_sheet_profiles=conflicting_sheet_profiles,
        bundle_mode=bundle_mode,
    )
    if final_confidence < _INFERENCE_CONFIDENCE_MIN and allow_explicit_override:
        reasons = [
            reason
            for reason in reasons
            if reason != "File type inference confidence is too low for safe auto-execution."
        ]
        reason_codes = [code for code in reason_codes if code != "low_inference_confidence"]
    if final_confidence < _INFERENCE_CONFIDENCE_MIN and same_side_recovery_confirmed:
        reasons = [
            reason
            for reason in reasons
            if reason != "File type inference confidence is too low for safe auto-execution."
        ]
        reason_codes = [code for code in reason_codes if code != "low_inference_confidence"]

    return (
        bool(reasons),
        reasons,
        {
            "mapping_confident_ratio": round(confident_ratio, 3),
            "unknown_required_ratio": round(unknown_required_ratio, 3),
            "inference_confidence": round(final_confidence, 3),
            "conflicting_sheet_profiles": 1.0 if conflicting_sheet_profiles else 0.0,
            "same_side_recovery_confirmed": 1.0 if same_side_recovery_confirmed else 0.0,
            "reason_codes": list(reason_codes),
        },
    )


__all__ = ["evaluate_manual_mapping_gate"]
