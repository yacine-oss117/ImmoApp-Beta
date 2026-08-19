"""Workbook/sheet-level semantic profiling for import files."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from core.importer.parsers import CsvParser, ExcelParser, OdsParser
from server.services.import_column_semantics import profile_columns
from server.services.import_type_inference import infer_row_entity


def _parser_for_sheet(file_type: str, *, sheet_name: str | None, max_rows: int) -> Any:
    kind = str(file_type or "").strip().lower()
    if kind == "excel":
        return ExcelParser(sheet_name=sheet_name, max_rows=max_rows)
    if kind == "ods":
        return OdsParser(sheet_name=sheet_name, max_rows=max_rows)
    return CsvParser(max_rows=max_rows)


def _shape_key_for_row(row: dict[str, Any], semantic_profiles: list[dict[str, Any]]) -> str:
    field_presence: list[str] = []
    for profile in semantic_profiles:
        header = str(profile.get("header", "") or "")
        detected_type = str(profile.get("detected_type", "unknown") or "unknown")
        if detected_type == "unknown":
            continue
        if str(row.get(header, "") or "").strip():
            field_presence.append(detected_type)
    if not field_presence:
        return "unknown"
    counts = Counter(field_presence)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    top = [name for name, _count in ordered[:5]]
    return "+".join(top)


def _mapped_row_for_inference(
    row: dict[str, Any], semantic_profiles: list[dict[str, Any]]
) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    location_values: list[str] = []
    for profile in semantic_profiles:
        header = str(profile.get("header", "") or "")
        detected_type = str(profile.get("detected_type", "unknown") or "unknown")
        if detected_type == "unknown":
            continue
        raw_value = row.get(header)
        if raw_value in {None, ""}:
            continue
        if detected_type == "location":
            location_values.append(str(raw_value))
            if "location" not in mapped:
                mapped["location"] = raw_value
            continue
        if detected_type not in mapped:
            mapped[detected_type] = raw_value
    if len(location_values) > 1:
        mapped["locations"] = location_values
    return mapped


def _bundle_mode_from_counts(
    *, root_rows: int, child_rows: int, sides: Counter[str]
) -> tuple[str, str, float]:
    dominant_side = "unknown"
    if sides:
        dominant_side = sides.most_common(1)[0][0]
    confidence = 0.0
    if root_rows and child_rows and dominant_side in {"client_side", "listing_side"}:
        confidence = min(
            0.95, 0.6 + ((root_rows + child_rows) / max(1, root_rows + child_rows)) * 0.2
        )
        return dominant_side, "same_side_bundle", round(confidence, 3)
    if child_rows and dominant_side in {"client_side", "listing_side"}:
        confidence = min(0.9, 0.55 + (child_rows / max(1, child_rows + root_rows)) * 0.25)
        return dominant_side, "single_entity", round(confidence, 3)
    if root_rows:
        confidence = 0.7
        return (
            dominant_side if dominant_side != "unknown" else "client_side",
            "single_entity",
            confidence,
        )
    return "unknown", "mixed_blocked", 0.0


def profile_import_sheets(
    *,
    path: Path,
    file_type: str,
    agency_profile_hints: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    kind = str(file_type or "").strip().lower()
    if kind == "csv":
        parser = CsvParser(max_rows=25)
        parsed = parser.parse(path)
        headers = list(parsed.headers or [])
        rows = list(parsed.rows or [])[:25]
        semantics = profile_columns(
            headers=headers,
            sample_rows=rows,
            agency_profile_hints=agency_profile_hints or {},
        )
        return [_build_sheet_profile(sheet_name="CSV", rows=rows, semantic_profiles=semantics)]

    parser = _parser_for_sheet(kind, sheet_name=None, max_rows=25)
    sheet_names = list(parser.get_sheet_names(path))
    profiles: list[dict[str, Any]] = []
    for sheet_name in sheet_names[:10]:
        sheet_parser = _parser_for_sheet(kind, sheet_name=sheet_name, max_rows=25)
        parsed = sheet_parser.parse(path)
        rows = list(parsed.rows or [])[:25]
        semantics = profile_columns(
            headers=list(parsed.headers or []),
            sample_rows=rows,
            agency_profile_hints=agency_profile_hints or {},
        )
        profiles.append(
            _build_sheet_profile(sheet_name=sheet_name, rows=rows, semantic_profiles=semantics)
        )
    return profiles


def _build_sheet_profile(
    *,
    sheet_name: str,
    rows: list[dict[str, Any]],
    semantic_profiles: list[dict[str, Any]],
) -> dict[str, Any]:
    shape_counts: Counter[str] = Counter()
    shape_entity_counts: dict[str, Counter[str]] = defaultdict(Counter)
    side_counts: Counter[str] = Counter()
    root_rows = 0
    child_rows = 0
    for row in rows:
        mapped_row = _mapped_row_for_inference(row, semantic_profiles)
        shape_key = _shape_key_for_row(row, semantic_profiles)
        shape_counts[shape_key] += 1
        inference = infer_row_entity(mapped_row, default_entity_type=None)
        if inference.entity_type:
            shape_entity_counts[shape_key][inference.entity_type] += 1
        if inference.topology_side != "unknown":
            side_counts[inference.topology_side] += 1
        if inference.entity_type in {"client", "listing"}:
            root_rows += 1
        elif inference.entity_type in {"demande", "offer"}:
            child_rows += 1
    topology_side, bundle_mode, confidence = _bundle_mode_from_counts(
        root_rows=root_rows,
        child_rows=child_rows,
        sides=side_counts,
    )
    groups = []
    for shape_key, count in shape_counts.most_common(6):
        dominant_entity = ""
        if shape_entity_counts[shape_key]:
            dominant_entity = shape_entity_counts[shape_key].most_common(1)[0][0]
        groups.append(
            {
                "shape_key": shape_key,
                "count": count,
                "dominant_entity_type": dominant_entity,
            }
        )
    return {
        "sheet_name": sheet_name,
        "row_sample_count": len(rows),
        "dominant_topology_side": topology_side,
        "dominant_bundle_mode": bundle_mode,
        "confidence": confidence,
        "row_shape_groups": groups,
    }


def choose_dominant_sheet(sheet_profiles: list[dict[str, Any]]) -> str:
    if not sheet_profiles:
        return ""
    ordered = sorted(
        sheet_profiles,
        key=lambda item: (
            float(item.get("confidence", 0.0) or 0.0),
            int(item.get("row_sample_count", 0) or 0),
        ),
        reverse=True,
    )
    if len(ordered) == 1:
        return str(ordered[0].get("sheet_name", "") or "")
    top = ordered[0]
    runner_up = ordered[1]
    top_confidence = float(top.get("confidence", 0.0) or 0.0)
    runner_up_confidence = float(runner_up.get("confidence", 0.0) or 0.0)
    if top_confidence >= 0.75 and (top_confidence - runner_up_confidence) >= 0.08:
        return str(top.get("sheet_name", "") or "")
    return ""


__all__ = ["choose_dominant_sheet", "profile_import_sheets"]
