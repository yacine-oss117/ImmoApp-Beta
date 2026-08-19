"""Column/file-level price dialect resolution for Algerian imports."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from core.importer.normalizers.price import PriceNormalizer
from server.services.import_agency_memory import load_agency_alias_memory, normalize_alias_value
from server.services.import_types import ALIAS_DOMAIN_PRICE

_PRICE_FIELDS = {"budget", "budget_min", "budget_max", "price"}
_PRICE_DIALECTS = {
    "raw_dzd",
    "dzd_thousands",
    "dzd_millions",
    "centime_scalar",
    "centime_millions",
    "centime_milliards",
}


def _normalized_header(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _header_unit_hint(header: str) -> str:
    normalized = _normalized_header(header)
    if any(
        token in normalized for token in ("dzd", " da", "prix (dzd)", "budget (da)", "budget da")
    ):
        return "dzd"
    if any(token in normalized for token in ("centime", "cts")):
        return "centime"
    return ""


def _safe_float(value: object) -> float:
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


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _header_explicit_dialect(header: str) -> tuple[str, str] | None:
    unit_hint = _header_unit_hint(header)
    if unit_hint == "dzd":
        return "dzd_millions", "header_explicit_dzd"
    if unit_hint == "centime":
        return "centime_scalar", "header_explicit_centime"
    return None


def _action_values(
    *,
    detected_columns: list[dict[str, object]],
    sample_rows: list[dict[str, object]],
) -> dict[str, list[str]]:
    action_headers = [
        str(column.get("header", "") or "")
        for column in detected_columns
        if str(column.get("detected_type", "unknown") or "unknown") == "action"
    ]
    if not action_headers:
        return {}
    per_row: dict[str, list[str]] = {}
    for row in sample_rows:
        for header in row.keys():
            value = ""
            for action_header in action_headers:
                candidate = str(row.get(action_header, "") or "").strip().lower()
                if candidate:
                    value = candidate
                    break
            if value:
                per_row.setdefault(header, []).append(value)
    return per_row


def build_price_dialect_profiles(
    *,
    detected_columns: list[dict[str, object]],
    sample_rows: list[dict[str, object]],
    final_inference: dict[str, Any] | None = None,
    agency_id: int = 0,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    normalizer = PriceNormalizer()
    final_payload = dict(final_inference or {})
    price_columns = [
        column
        for column in detected_columns
        if str(column.get("detected_type", "unknown") or "unknown") == "price"
    ]
    action_by_header = _action_values(detected_columns=detected_columns, sample_rows=sample_rows)
    memory = (
        load_agency_alias_memory(agency_id, domains=[ALIAS_DOMAIN_PRICE]) if agency_id > 0 else None
    )
    trusted_aliases = dict((memory.trusted.get(ALIAS_DOMAIN_PRICE, {}) if memory else {}) or {})

    profiles: list[dict[str, object]] = []
    sample_candidate_examples: list[dict[str, object]] = []
    file_dialect_counts: Counter[str] = Counter()
    ambiguous_column_count = 0
    ambiguous_row_count = 0
    review_reason_codes: set[str] = set()

    for column in price_columns:
        header = str(column.get("header", "") or "")
        if not header:
            continue
        scores: defaultdict[str, float] = defaultdict(float)
        reason_codes: list[str] = []
        anchored_example_count = 0
        ambiguous_example_count = 0
        scalar_dzd_anchors: list[float] = []
        values = [
            str(row.get(header, "") or "").strip()
            for row in sample_rows
            if str(row.get(header, "") or "").strip()
        ]
        header_hint = _header_explicit_dialect(header)
        header_unit_hint = _header_unit_hint(header)
        if header_hint is not None:
            hinted_dialect, hinted_reason = header_hint
            scores[hinted_dialect] += 1.0
            reason_codes.append(hinted_reason)

        rent_bias = 0
        for raw_value in values:
            alias_key = normalize_alias_value(ALIAS_DOMAIN_PRICE, raw_value)
            alias_entry = trusted_aliases.get(alias_key)
            if alias_entry is not None:
                alias_dialect = str(alias_entry.metadata.get("dialect", "") or "").strip()
                if alias_dialect:
                    scores[alias_dialect] += 1.2
                    reason_codes.append("trusted_agency_price_alias")
            candidate_payloads = normalizer.candidate_records(raw_value)
            candidate_dialects = {
                str(candidate.get("dialect", "") or "")
                for candidate in candidate_payloads
                if isinstance(candidate, dict)
            }
            if len(candidate_payloads) == 1:
                candidate = dict(candidate_payloads[0])
                normalized_dzd = candidate.get("normalized_dzd")
                if isinstance(normalized_dzd, (int, float)):
                    anchored_example_count += 1
                    dialect = str(candidate.get("dialect", "unknown") or "unknown")
                    scores[dialect] += _safe_float(candidate.get("confidence", 0.0))
                    if dialect == "raw_dzd":
                        scalar_dzd_anchors.append(float(normalized_dzd))
            elif {"dzd_millions", "centime_millions"} == candidate_dialects:
                if header_unit_hint == "dzd":
                    anchored_example_count += 1
                    scores["dzd_millions"] += 0.95
                    reason_codes.append("header_explicit_dzd")
                    continue
                if header_unit_hint == "centime":
                    anchored_example_count += 1
                    scores["centime_millions"] += 0.95
                    reason_codes.append("header_explicit_centime")
                    continue
                ambiguous_example_count += 1
                ambiguous_row_count += 1
                review_reason_codes.add("ambiguous_million_token")
                if len(sample_candidate_examples) < 5:
                    sample_candidate_examples.append(
                        {
                            "header": header,
                            "raw_value": raw_value,
                            "candidates": [
                                {
                                    "normalized_dzd": candidate.get("normalized_dzd"),
                                    "dialect": str(candidate.get("dialect", "") or ""),
                                    "expression_kind": str(
                                        candidate.get("expression_kind", "") or ""
                                    ),
                                    "confidence": _safe_float(candidate.get("confidence", 0.0)),
                                }
                                for candidate in candidate_payloads
                                if isinstance(candidate, dict)
                            ],
                        }
                    )
            elif (
                len(candidate_payloads) == 1 and candidate_payloads[0].get("normalized_dzd") is None
            ):
                ambiguous_example_count += 1
                ambiguous_row_count += 1
                reason_codes_raw = candidate_payloads[0].get("reason_codes", [])
                for code in (reason_codes_raw if isinstance(reason_codes_raw, list) else []):
                    review_reason_codes.add(str(code))

        if ambiguous_example_count > 0 and scalar_dzd_anchors:
            median_value = _median(scalar_dzd_anchors)
            if 0 < median_value <= 500_000:
                scores["centime_millions"] += 1.0
                reason_codes.append("column_low_scalar_consensus")
            elif median_value >= 1_000_000:
                scores["dzd_millions"] += 1.0
                reason_codes.append("column_high_scalar_consensus")

        for action in action_by_header.get(header, []):
            if action in {"rent", "location", "louer", "cherche location", "كراء"}:
                rent_bias += 1
        if ambiguous_example_count > 0 and rent_bias >= 2:
            scores["centime_millions"] += 0.25
            reason_codes.append("rent_action_bias")

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_dialect = ranked[0][0] if ranked else "unknown"
        top_score = ranked[0][1] if ranked else 0.0
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        total_score = sum(scores.values())
        confidence = 0.0
        if ranked and top_score >= 0.8 and (top_score - second_score) >= 0.15:
            confidence = min(0.98, top_score / max(1.0, total_score))
        else:
            top_dialect = "ambiguous" if ambiguous_example_count > 0 else "unknown"
            ambiguous_column_count += 1 if ambiguous_example_count > 0 else 0
            if ambiguous_example_count > 0:
                reason_codes.append("ambiguous_price_scale")

        profile = {
            "header": header,
            "dominant_dialect": top_dialect,
            "confidence": round(confidence, 3),
            "sample_count": len(values),
            "anchored_example_count": anchored_example_count,
            "ambiguous_example_count": ambiguous_example_count,
            "reason_codes": sorted({code for code in reason_codes if str(code).strip()}),
        }
        if top_dialect in _PRICE_DIALECTS:
            file_dialect_counts[top_dialect] += 1
        profiles.append(profile)

    summary_dialect = "unknown"
    summary_confidence = 0.0
    if file_dialect_counts:
        ranked_file = file_dialect_counts.most_common()
        summary_dialect, top_count = ranked_file[0]
        second_count = ranked_file[1][1] if len(ranked_file) > 1 else 0
        total = sum(file_dialect_counts.values())
        if total > 0:
            summary_confidence = round(top_count / total, 3)
        if second_count and (top_count - second_count) < 1:
            summary_dialect = "ambiguous"

    if any(str(profile.get("dominant_dialect", "")) == "ambiguous" for profile in profiles):
        summary_dialect = "ambiguous" if summary_dialect == "unknown" else summary_dialect

    summary = {
        "dominant_dialect": summary_dialect,
        "confidence": summary_confidence,
        "ambiguous_price_column_count": ambiguous_column_count,
        "ambiguous_price_row_count": ambiguous_row_count,
        "price_review_reason_codes": sorted(review_reason_codes),
        "sample_candidate_examples": sample_candidate_examples,
        "file_model_hint": str(final_payload.get("file_model_hint", "unknown") or "unknown"),
        "dominant_side": str(final_payload.get("dominant_side", "unknown") or "unknown"),
    }
    return profiles, summary


def build_field_price_metadata(
    *,
    agency_id: int,
    column_mapping: dict[str, str],
    inference_summary: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    profiles = list(inference_summary.get("price_dialect_profiles", []) or [])
    profiles_by_header = {
        str(profile.get("header", "") or ""): dict(profile)
        for profile in profiles
        if isinstance(profile, dict)
    }
    memory = load_agency_alias_memory(agency_id, domains=[ALIAS_DOMAIN_PRICE])
    trusted_aliases = dict(memory.trusted.get(ALIAS_DOMAIN_PRICE, {}) or {})

    result: dict[str, dict[str, Any]] = {}
    for field_name, header_name in dict(column_mapping or {}).items():
        if str(field_name or "").strip().lower() not in _PRICE_FIELDS:
            continue
        header = str(header_name or "")
        profile = dict(profiles_by_header.get(header, {}) or {})
        header_key = _normalized_header(header)
        filtered_aliases: dict[str, dict[str, object]] = {}
        for alias_key, entry in trusted_aliases.items():
            header_context = _normalized_header(entry.metadata.get("header_context", ""))
            if header_context and header_context != header_key:
                continue
            dialect = str(entry.metadata.get("dialect", "") or "").strip()
            expression_kind = str(entry.metadata.get("expression_kind", "") or "").strip()
            if not dialect:
                continue
            filtered_aliases[alias_key] = {
                "dialect": dialect,
                "expression_kind": expression_kind,
                "header_context": str(entry.metadata.get("header_context", "") or ""),
            }
        result[str(field_name)] = {
            "source_header": header,
            "price_unit_hint": _header_unit_hint(header),
            "price_dialect_hint": str(profile.get("dominant_dialect", "") or ""),
            "price_dialect_confidence": _safe_float(profile.get("confidence", 0.0)),
            "price_aliases": filtered_aliases,
        }
    return result


__all__ = ["build_field_price_metadata", "build_price_dialect_profiles"]
