"""
Shared import metadata mapping helpers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from server.imports.models import ImportJob

_FIELD_TO_TYPE: dict[str, str] = {
    "family_name": "name",
    "email": "email",
    "status": "unknown",
    "remarks": "notes",
    "tags": "notes",
    "phone": "phone",
    "budget": "price",
    "budget_min": "price",
    "budget_max": "price",
    "price": "price",
    "surface": "surface",
    "surface_min": "surface",
    "surface_max": "surface",
    "wilaya": "wilaya",
    "wilaya_id": "unknown",
    "location": "location",
    "locations": "location",
    "action": "action",
    "action_id": "unknown",
    "type": "type",
    "type_id": "unknown",
    "beds": "beds",
    "beds_min": "beds_min",
    "floor": "floor",
    "floor_min": "floor_min",
    "floor_max": "floor_max",
    "furnished": "furnished",
    "elevator": "elevator",
    "parking": "parking",
    "accessibility_required": "accessibility_required",
    "accessibility_supported": "accessibility_supported",
    "price_negotiable": "price_negotiable",
    "price_flex_pct": "unknown",
    "client_id": "unknown",
    "listing_id": "unknown",
}
_CANONICAL_FIELDS = set(_FIELD_TO_TYPE)
_CONTEXTUAL_CANONICAL_FIELDS = {"price", "surface", "floor", "location"}
_ROLE_SCORE_BONUS: dict[str, float] = {
    "root_identity": 0.15,
    "root_tags": 0.2,
    "root_notes": 0.2,
    "child_budget_min": 0.2,
    "child_budget_max": 0.2,
    "child_price_scalar": 0.15,
    "child_surface_min": 0.2,
    "child_surface_max": 0.2,
    "child_surface": 0.1,
    "child_beds_min": 0.2,
    "child_beds": 0.1,
    "child_floor_min": 0.2,
    "child_floor_max": 0.2,
    "child_floor": 0.1,
}


def _normalized_text(value: object) -> str:
    return str(value or "").strip().lower()


def _normalized_final_inference(final_inference: Mapping[str, object] | None) -> dict[str, object]:
    return {str(key): value for key, value in dict(final_inference or {}).items()}


def _mapping_side(final_inference: Mapping[str, object] | None) -> str:
    normalized = _normalized_final_inference(final_inference)
    topology_side = _normalized_text(normalized.get("topology_side_hint"))
    if topology_side in {"client_side", "listing_side"}:
        return topology_side
    file_model_hint = _normalized_text(normalized.get("file_model_hint"))
    if file_model_hint == "client_lead_sheet":
        return "client_side"
    if file_model_hint == "listing_inventory":
        return "listing_side"
    detected_entity = _normalized_text(normalized.get("detected_entity"))
    if detected_entity in {"client", "demande"}:
        return "client_side"
    if detected_entity in {"listing", "offer"}:
        return "listing_side"
    return "unknown"


def _profile_by_header(
    detected_columns: list[dict[str, object]] | None,
) -> dict[str, dict[str, object]]:
    return {
        str(col.get("header", "")).strip(): dict(col)
        for col in (detected_columns or [])
        if str(col.get("header", "")).strip()
    }


def _canonical_field_from_profile(
    *,
    profile: Mapping[str, object],
    side: str,
) -> str:
    detected_type = _normalized_text(profile.get("detected_type"))
    detected_role = _normalized_text(profile.get("detected_role"))

    if side == "client_side":
        if detected_role == "root_identity":
            if detected_type == "name":
                return "family_name"
            if detected_type in {"phone", "email"}:
                return detected_type
        if detected_role == "root_tags":
            return "tags"
        if detected_role == "root_notes":
            return "remarks"
        if detected_role == "child_action":
            return "action"
        if detected_role == "child_type":
            return "type"
        if detected_role == "child_geo_preference":
            return "locations"
        if detected_role == "child_geo":
            return "wilaya" if detected_type == "wilaya" else "locations"
        if detected_role == "child_budget_min":
            return "budget_min"
        if detected_role in {"child_budget_max", "child_price", "child_price_scalar"}:
            return "budget_max"
        if detected_role == "child_surface_min":
            return "surface_min"
        if detected_role == "child_surface_max":
            return "surface_max"
        if detected_role == "child_surface":
            return "surface_min"
        if detected_role in {"child_beds_min", "child_beds"}:
            return "beds_min"
        if detected_role == "child_floor_min":
            return "floor_min"
        if detected_role == "child_floor_max":
            return "floor_max"
        if detected_role == "child_floor":
            return "floor_min"
        if detected_type == "furnished":
            return "furnished"
        if detected_type == "elevator":
            return "elevator"
        if detected_type == "accessibility_required":
            return "accessibility_required"
        if detected_type == "wilaya":
            return "wilaya"
        if detected_type == "location":
            return "locations"
        if detected_type == "price":
            return "budget_max"
        if detected_type == "surface":
            return "surface_min"
        if detected_type == "rooms":
            return "beds_min"
        if detected_type == "floor":
            return "floor_min"
    if side == "listing_side":
        if detected_role == "root_identity":
            if detected_type == "name":
                return "family_name"
            if detected_type in {"phone", "email"}:
                return detected_type
        if detected_role in {"root_tags", "root_notes"}:
            return "remarks"
        if detected_role == "child_action":
            return "action"
        if detected_role == "child_type":
            return "type"
        if detected_role == "child_geo":
            return "wilaya" if detected_type == "wilaya" else "location"
        if detected_role in {
            "child_budget_min",
            "child_budget_max",
            "child_price",
            "child_price_scalar",
        }:
            return "budget"
        if detected_role in {"child_surface_min", "child_surface_max", "child_surface"}:
            return "surface"
        if detected_role in {"child_beds_min", "child_beds"}:
            return "beds"
        if detected_role in {"child_floor_min", "child_floor_max", "child_floor"}:
            return "floor"
        if detected_type == "furnished":
            return "furnished"
        if detected_type == "elevator":
            return "elevator"
        if detected_type == "accessibility_supported":
            return "accessibility_supported"
        if detected_type == "price_negotiable":
            return "price_negotiable"
        if detected_type == "wilaya":
            return "wilaya"
        if detected_type == "location":
            return "location"
        if detected_type == "price":
            return "budget"
        if detected_type == "surface":
            return "surface"
        if detected_type == "rooms":
            return "beds"
        if detected_type == "floor":
            return "floor"
    return ""


def _normalize_mapping_field(
    *,
    field_name: str,
    header_name: str,
    detected_columns: list[dict[str, object]] | None,
    final_inference: Mapping[str, object] | None,
) -> str:
    normalized_field = _normalized_text(field_name)
    profile = _profile_by_header(detected_columns).get(header_name, {})
    side = _mapping_side(final_inference)
    profiled = _canonical_field_from_profile(profile=profile, side=side)
    if profiled:
        return profiled
    if (
        normalized_field in _CANONICAL_FIELDS
        and normalized_field not in _CONTEXTUAL_CANONICAL_FIELDS
    ):
        return normalized_field

    if side == "client_side":
        generic_aliases = {
            "name": "family_name",
            "notes": "remarks",
            "price": "budget_max",
            "surface": "surface_min",
            "rooms": "beds_min",
            "beds": "beds_min",
            "floor": "floor_min",
            "location": "locations",
            "city": "wilaya",
        }
        return generic_aliases.get(normalized_field, normalized_field)
    if side == "listing_side":
        generic_aliases = {
            "name": "family_name",
            "notes": "remarks",
            "price": "budget",
            "surface": "surface",
            "rooms": "beds",
            "location": "location",
            "city": "wilaya",
        }
        return generic_aliases.get(normalized_field, normalized_field)
    generic_aliases = {
        "name": "family_name",
        "notes": "remarks",
        "city": "wilaya",
    }
    return generic_aliases.get(normalized_field, normalized_field)


def _mapping_score(
    *,
    profile: Mapping[str, object],
    target_field: str,
) -> float:
    confidence_raw = profile.get("confidence", 0.0)
    confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.0
    detected_role = _normalized_text(profile.get("detected_role"))
    score = confidence + _ROLE_SCORE_BONUS.get(detected_role, 0.0)
    if target_field in {"tags", "remarks", "budget_max", "surface_min", "beds_min", "floor_min"}:
        score += 0.01
    return score


def suggest_column_mapping(
    *,
    detected_columns: list[dict[str, object]] | None,
    final_inference: Mapping[str, object] | None = None,
) -> dict[str, str]:
    profiles = list(detected_columns or [])
    side = _mapping_side(final_inference)
    mapping: dict[str, str] = {}
    scores: dict[str, float] = {}
    for profile in profiles:
        header_name = str(profile.get("header", "")).strip()
        if not header_name:
            continue
        target_field = _canonical_field_from_profile(profile=profile, side=side)
        if not target_field:
            continue
        score = _mapping_score(profile=profile, target_field=target_field)
        if target_field in scores and scores[target_field] >= score:
            continue
        mapping[target_field] = header_name
        scores[target_field] = score
    return mapping


def extract_detected_headers(detected_columns: list[dict[str, object]] | None) -> set[str]:
    """Extract normalized header names from detected column metadata."""
    headers: set[str] = set()
    for col in detected_columns or []:
        header = str(col.get("header", "")).strip()
        if header:
            headers.add(header)
    return headers


def canonicalize_column_mapping(
    *,
    column_mapping: dict[str, str] | None,
    detected_columns: list[dict[str, object]] | None,
    final_inference: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Return canonical mapping shape: ``field_name -> source_header``.

    Legacy callers may send ``header -> field``. We detect and invert safely
    using detected headers from the parse stage.
    """
    clean: dict[str, str] = {}
    for raw_k, raw_v in (column_mapping or {}).items():
        key = str(raw_k).strip()
        val = str(raw_v).strip()
        if key and val:
            clean[key] = val
    if not clean:
        return {}

    detected_headers = extract_detected_headers(detected_columns)
    if not detected_headers:
        return clean

    key_is_header = sum(1 for k in clean if k in detected_headers)
    value_is_header = sum(1 for v in clean.values() if v in detected_headers)

    if key_is_header > value_is_header:
        canonical = {field: header for header, field in clean.items()}
    else:
        canonical = dict(clean)

    # Keep only mappings that reference real headers from the uploaded file.
    normalized: dict[str, str] = {}
    scores: dict[str, float] = {}
    profiles = _profile_by_header(detected_columns)
    for field, header in canonical.items():
        if header not in detected_headers:
            continue
        normalized_field = _normalize_mapping_field(
            field_name=field,
            header_name=header,
            detected_columns=detected_columns,
            final_inference=final_inference,
        )
        if not normalized_field:
            continue
        profile = profiles.get(header, {})
        score = _mapping_score(profile=profile, target_field=normalized_field)
        if normalized_field in scores and scores[normalized_field] >= score:
            continue
        normalized[normalized_field] = header
        scores[normalized_field] = score
    return normalized


def build_column_types(
    *,
    detected_columns: list[dict[str, object]] | None,
    column_mapping: dict[str, str] | None,
) -> dict[str, str]:
    """Build field_name -> detected_type mapping from job metadata."""
    header_to_type: dict[str, str] = {}
    for col in detected_columns or []:
        header = str(col.get("header", ""))
        detected = str(col.get("detected_type", "unknown"))
        if header:
            header_to_type[header] = detected

    result: dict[str, str] = {}
    for field_name, header_name in (column_mapping or {}).items():
        canonical_type = _FIELD_TO_TYPE.get(field_name)
        if canonical_type is not None:
            result[field_name] = canonical_type
            continue
        result[field_name] = header_to_type.get(header_name, "unknown")
    return result


def build_column_types_from_job(job: ImportJob) -> dict[str, str]:
    canonical_mapping = canonicalize_column_mapping(
        column_mapping=job.column_mapping or {},
        detected_columns=job.detected_columns or [],
        final_inference=(job.inference_summary or {}).get("final_inference", {}),
    )
    return build_column_types(
        detected_columns=job.detected_columns or [],
        column_mapping=canonical_mapping,
    )


def merge_row_corrections(
    *,
    raw_row: dict[str, Any],
    row_index: int,
    corrections: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    if not corrections:
        return raw_row
    row_key = str(row_index)
    legacy_key = str(row_index - 1)
    if row_key not in corrections and legacy_key not in corrections:
        return raw_row
    merged = dict(raw_row)
    if row_key in corrections:
        merged.update(corrections[row_key])
    else:
        merged.update(corrections[legacy_key])
    return merged


__all__ = [
    "build_column_types",
    "build_column_types_from_job",
    "canonicalize_column_mapping",
    "extract_detected_headers",
    "merge_row_corrections",
    "suggest_column_mapping",
]
