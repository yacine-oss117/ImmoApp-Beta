"""Deterministic column semantic profiling for weak-header import files."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from core.importer.detection.column_detector import ColumnDetector
from core.importer.detection.column_detector_rules import normalize_header_phrase, tokenize_header
from core.importer.normalizers.action import ActionNormalizer
from core.importer.normalizers.property_type import PropertyTypeNormalizer
from server.services.import_agency_profile import load_agency_profile_hints
from server.services.import_location_normalizer import shared_location_normalizer
from server.services.import_types import (
    ColumnRoleProfile,
    SemanticEvidenceCell,
    SemanticEvidenceRow,
)

_PHONE_PATTERN = re.compile(r"^\+?[\d\s().-]{8,18}$")
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_REFERENCE_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9/_-]{3,32}$")
_NUMERIC_PATTERN = re.compile(r"^\d+(?:[.,]\d+)?$")
_ROOMS_PATTERN = re.compile(r"^(?:[fFtT]\s*)?\d{1,2}(?:\s*[+/-]\s*\d{1,2})?$")
_SURFACE_HINT_PATTERN = re.compile(r"\b(?:m2|m²|sqm|m)\b", re.IGNORECASE)
_PRICE_HINT_PATTERN = re.compile(r"\b(?:da|dzd|k|m|millions?)\b", re.IGNORECASE)
_ALGERIAN_PHONE_PREFIXES = ("05", "06", "07", "02", "03", "04")

_ACTION_NORMALIZER = ActionNormalizer(entity_type="client")
_PROPERTY_TYPE_NORMALIZER = PropertyTypeNormalizer()
_HEADER_DETECTOR = ColumnDetector()


@dataclass(frozen=True)
class _HeaderRoleRule:
    detected_type: str
    detected_role: str
    side_prior: str
    aliases: tuple[str, ...]


_HEADER_ROLE_RULES: tuple[_HeaderRoleRule, ...] = (
    _HeaderRoleRule(
        "name",
        "root_identity",
        "client_root",
        ("nom complet / client", "nom complet client", "nom complet", "nom du client", "client"),
    ),
    _HeaderRoleRule(
        "name",
        "root_identity",
        "listing_root",
        (
            "owner name",
            "nom proprietaire",
            "nom du proprietaire",
            "proprietaire",
            "proprietaire nom",
        ),
    ),
    _HeaderRoleRule(
        "phone",
        "root_identity",
        "client_root",
        (
            "n telephone",
            "n telephone client",
            "numero telephone",
            "telephone client",
            "telephone",
            "portable",
        ),
    ),
    _HeaderRoleRule(
        "phone",
        "root_identity",
        "listing_root",
        ("telephone proprietaire", "portable proprietaire", "owner phone"),
    ),
    _HeaderRoleRule(
        "notes", "root_tags", "neutral", ("tags / labels", "tags labels", "tags", "labels")
    ),
    _HeaderRoleRule(
        "notes",
        "root_notes",
        "neutral",
        ("remarques additionnelles", "remarques", "notes additionnelles", "notes", "observations"),
    ),
    _HeaderRoleRule(
        "action",
        "child_action",
        "shared_child",
        ("action (vente/loc)", "action vente loc", "vente/loc", "vente loc", "action"),
    ),
    _HeaderRoleRule(
        "type", "child_type", "shared_child", ("type de bien", "type bien", "property type", "type")
    ),
    _HeaderRoleRule(
        "wilaya", "child_geo", "shared_child", ("wilaya/ville", "wilaya ville", "wilaya", "ville")
    ),
    _HeaderRoleRule(
        "location",
        "child_geo_preference",
        "client_root",
        ("locations", "quartiers souhaites", "preferred areas", "zones recherchees"),
    ),
    _HeaderRoleRule(
        "location", "child_geo", "listing_root", ("location", "commune", "quartier", "adresse")
    ),
    _HeaderRoleRule(
        "price", "child_budget_min", "client_root", ("budget_min", "budget min", "minimum budget")
    ),
    _HeaderRoleRule(
        "price",
        "child_budget_max",
        "client_root",
        (
            "budget max/prix",
            "budget max prix",
            "budget_max",
            "budget max",
            "maximum budget",
            "prix max",
        ),
    ),
    _HeaderRoleRule("price", "child_price_scalar", "listing_root", ("budget", "prix", "price")),
    _HeaderRoleRule(
        "surface",
        "child_surface_min",
        "client_root",
        ("surface_min", "surface min", "minimum size"),
    ),
    _HeaderRoleRule(
        "surface",
        "child_surface_max",
        "client_root",
        ("surface_max", "surface max", "maximum size"),
    ),
    _HeaderRoleRule(
        "surface", "child_surface", "shared_child", ("surface (m2)", "surface m2", "surface")
    ),
    _HeaderRoleRule(
        "rooms", "child_beds_min", "client_root", ("beds_min", "minimum bedrooms", "minimum beds")
    ),
    _HeaderRoleRule(
        "rooms",
        "child_beds",
        "shared_child",
        ("chambres (beds)", "chambres beds", "chambres", "beds", "rooms"),
    ),
    _HeaderRoleRule(
        "floor", "child_floor_min", "client_root", ("floor_min", "minimum floor", "etage minimum")
    ),
    _HeaderRoleRule(
        "floor", "child_floor_max", "client_root", ("floor_max", "maximum floor", "etage maximum")
    ),
    _HeaderRoleRule("floor", "child_floor", "shared_child", ("etage/rdc", "etage", "floor")),
    _HeaderRoleRule(
        "furnished",
        "child_furnished",
        "shared_child",
        ("meuble ?", "meuble", "meuble?", "furnished"),
    ),
    _HeaderRoleRule(
        "price_negotiable",
        "child_price",
        "listing_root",
        ("price negotiable", "prix negociable", "negotiable"),
    ),
)

_DEFAULT_ROLE_HINTS: dict[str, tuple[str, str]] = {
    "phone": ("root_identity", "unknown"),
    "name": ("root_identity", "unknown"),
    "email": ("root_identity", "unknown"),
    "notes": ("root_notes", "neutral"),
    "action": ("child_action", "shared_child"),
    "type": ("child_type", "shared_child"),
    "location": ("child_geo", "shared_child"),
    "wilaya": ("child_geo", "shared_child"),
    "price": ("child_price", "shared_child"),
    "surface": ("child_surface", "shared_child"),
    "rooms": ("child_beds", "shared_child"),
    "floor": ("child_floor", "shared_child"),
    "elevator": ("child_access", "shared_child"),
    "parking": ("child_access", "shared_child"),
    "accessibility_required": ("child_access", "shared_child"),
    "accessibility_supported": ("child_access", "shared_child"),
    "price_negotiable": ("child_price", "listing_root"),
}


def _clean_phone_digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _safe_ratio(matched: int, total: int) -> float:
    return round((matched / total), 3) if total else 0.0


def _looks_like_phone(value: str) -> bool:
    if not _PHONE_PATTERN.match(value):
        return False
    digits = _clean_phone_digits(value)
    if len(digits) < 8 or len(digits) > 13:
        return False
    return digits.startswith(_ALGERIAN_PHONE_PREFIXES) or digits.startswith("213")


def _looks_like_price(value: str) -> bool:
    text = value.strip().lower()
    if _looks_like_phone(text):
        return False
    digits = re.sub(r"[^\d.,]", "", text)
    if not digits:
        return False
    if _PRICE_HINT_PATTERN.search(text):
        return True
    try:
        normalized = float(digits.replace(",", "."))
    except ValueError:
        return False
    return normalized >= 1000


def _looks_like_surface(value: str) -> bool:
    text = value.strip().lower()
    if _SURFACE_HINT_PATTERN.search(text):
        return True
    digits = re.sub(r"[^\d.,]", "", text)
    if not digits:
        return False
    try:
        normalized = float(digits.replace(",", "."))
    except ValueError:
        return False
    return 8 <= normalized <= 10000


def _looks_like_rooms(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    return bool(_ROOMS_PATTERN.match(text) or re.match(r"^\d{1,2}$", text))


def _looks_like_reference(value: str) -> bool:
    return bool(_REFERENCE_PATTERN.match(value.strip()))


def _normalize_token(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _language_mix(values: list[str]) -> str:
    has_arabic = any(any("\u0600" <= ch <= "\u06ff" for ch in value) for value in values)
    has_latin = any(any("a" <= ch.lower() <= "z" for ch in value) for value in values)
    if has_arabic and has_latin:
        return "mixed"
    if has_arabic:
        return "ar"
    if has_latin:
        return "latin"
    return "unknown"


def _header_rule_match(
    header: str,
) -> tuple[_HeaderRoleRule | None, float, list[str]]:
    phrase = normalize_header_phrase(header)
    tokens = set(tokenize_header(header))
    if not phrase:
        return None, 0.0, []

    scored: list[tuple[_HeaderRoleRule, float, str]] = []
    for rule in _HEADER_ROLE_RULES:
        best_score = 0.0
        best_reason = ""
        for alias in rule.aliases:
            alias_phrase = normalize_header_phrase(alias)
            alias_tokens = set(tokenize_header(alias))
            score = 0.0
            reason = ""
            if phrase == alias_phrase:
                score = 1.0
                reason = f"header exactly matches '{alias}'"
            elif alias_tokens and alias_tokens.issubset(tokens):
                score = 0.95 if len(alias_tokens) > 1 else 0.9
                reason = f"header tokens match '{alias}'"
            elif tokens and tokens.issubset(alias_tokens) and len(tokens) > 1:
                score = 0.9
                reason = f"header phrase aligns with '{alias}'"
            if score > best_score:
                best_score = score
                best_reason = reason
        if best_score > 0.0:
            scored.append((rule, best_score, best_reason))
    if not scored:
        return None, 0.0, []
    scored.sort(key=lambda item: item[1], reverse=True)
    best_rule, best_score, best_reason = scored[0]
    second_score = scored[1][1] if len(scored) > 1 else 0.0
    if best_score < 0.75:
        return None, 0.0, []
    if second_score and (best_score - second_score) < 0.15:
        return None, 0.0, []
    return best_rule, round(best_score, 3), [best_reason]


def _default_role_profile(
    detected_type: str,
) -> tuple[str, str]:
    return _DEFAULT_ROLE_HINTS.get(
        str(detected_type or "").strip().lower(),
        ("unknown", "unknown"),
    )


def _semantic_signals(values: list[str]) -> dict[str, float]:
    total = len(values)
    if total == 0:
        return {
            "phone_ratio": 0.0,
            "price_ratio": 0.0,
            "location_ratio": 0.0,
            "wilaya_ratio": 0.0,
            "action_ratio": 0.0,
            "property_type_ratio": 0.0,
            "surface_ratio": 0.0,
            "rooms_ratio": 0.0,
            "reference_ratio": 0.0,
            "email_ratio": 0.0,
            "numeric_ratio": 0.0,
            "token_repeat_score": 0.0,
            "normalized_unique_ratio": 0.0,
        }
    tokens = [_normalize_token(value) for value in values if _normalize_token(value)]
    counts = Counter(tokens)
    token_repeat_score = round((max(counts.values()) / len(tokens)), 3) if tokens else 0.0
    normalized_unique_ratio = round((len(counts) / len(tokens)), 3) if tokens else 0.0
    location_hits = 0
    wilaya_hits = 0
    action_hits = 0
    type_hits = 0
    for value in values:
        loc = shared_location_normalizer().normalize(value)
        extras = dict(loc.extracted_extras or {})
        if float(loc.confidence) >= 0.7 and (loc.value or extras.get("matched_name")):
            location_hits += 1
        if extras.get("is_wilaya"):
            wilaya_hits += 1
        if _ACTION_NORMALIZER.normalize(value).confidence >= 0.75:
            action_hits += 1
        if _PROPERTY_TYPE_NORMALIZER.normalize(value).confidence >= 0.75:
            type_hits += 1
    return {
        "phone_ratio": _safe_ratio(sum(1 for value in values if _looks_like_phone(value)), total),
        "price_ratio": _safe_ratio(sum(1 for value in values if _looks_like_price(value)), total),
        "location_ratio": _safe_ratio(location_hits, total),
        "wilaya_ratio": _safe_ratio(wilaya_hits, total),
        "action_ratio": _safe_ratio(action_hits, total),
        "property_type_ratio": _safe_ratio(type_hits, total),
        "surface_ratio": _safe_ratio(
            sum(1 for value in values if _looks_like_surface(value)), total
        ),
        "rooms_ratio": _safe_ratio(sum(1 for value in values if _looks_like_rooms(value)), total),
        "reference_ratio": _safe_ratio(
            sum(1 for value in values if _looks_like_reference(value)), total
        ),
        "email_ratio": _safe_ratio(
            sum(1 for value in values if _EMAIL_PATTERN.match(value.strip())), total
        ),
        "numeric_ratio": _safe_ratio(
            sum(1 for value in values if _NUMERIC_PATTERN.match(value.strip())), total
        ),
        "token_repeat_score": token_repeat_score,
        "normalized_unique_ratio": normalized_unique_ratio,
    }


def _dominant_type(
    signals: dict[str, float], *, header: str, agency_profile_hints: dict[str, Any]
) -> tuple[str, float, str, str, list[str]]:
    header_result = _HEADER_DETECTOR.detect_column_type(header, None)
    header_rule, rule_confidence, header_reasons = _header_rule_match(header)
    scores = {
        "phone": signals["phone_ratio"],
        "price": signals["price_ratio"],
        "location": signals["location_ratio"],
        "wilaya": signals["wilaya_ratio"],
        "action": signals["action_ratio"],
        "type": signals["property_type_ratio"],
        "surface": signals["surface_ratio"],
        "rooms": signals["rooms_ratio"],
        "reference": signals["reference_ratio"],
        "email": signals["email_ratio"],
    }
    if header_result.detected_type != "unknown":
        scores[header_result.detected_type] = max(
            scores.get(header_result.detected_type, 0.0),
            min(1.0, float(header_result.confidence)),
        )
    if header_rule is not None:
        scores[header_rule.detected_type] = max(
            scores.get(header_rule.detected_type, 0.0),
            float(rule_confidence),
        )
    header_vocab = {
        _normalize_token(key): str(value or "")
        for key, value in dict(agency_profile_hints.get("header_vocab") or {}).items()
    }
    hinted_type = header_vocab.get(_normalize_token(header))
    if hinted_type:
        scores[hinted_type] = max(scores.get(hinted_type, 0.0), 0.75)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_type, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    if best_score < 0.65:
        return "unknown", best_score, "unknown", "unknown", []
    if second_score and (best_score - second_score) < 0.15 and header_rule is None:
        return "unknown", best_score, "unknown", "unknown", []

    reasons: list[str] = []
    detected_role = "unknown"
    side_prior = "unknown"
    if header_rule is not None and header_rule.detected_type == best_type:
        detected_role = header_rule.detected_role
        side_prior = header_rule.side_prior
        reasons.extend(header_reasons)
    else:
        detected_role, side_prior = _default_role_profile(best_type)
        if header_result.detected_type == best_type and float(header_result.confidence) >= 0.75:
            reasons.append(f"header detector matched '{best_type}'")
        if hinted_type == best_type:
            reasons.append("agency header memory matched")
    for signal_name, signal_value in signals.items():
        if signal_value >= 0.75 and signal_name.startswith(best_type):
            reasons.append(f"{signal_name} is strong")
    return best_type, min(best_score, 1.0), detected_role, side_prior, reasons


def profile_columns(
    *,
    headers: list[str],
    sample_rows: list[dict[str, Any]],
    agency_profile_hints: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    hints = dict(agency_profile_hints or {})
    profiles: list[dict[str, Any]] = []
    raw_profiles: list[dict[str, Any]] = []
    for header in headers:
        values = [
            str(row.get(header, "") or "").strip()
            for row in sample_rows
            if str(row.get(header, "") or "").strip()
        ][:50]
        signals = _semantic_signals(values)
        detected_type, confidence, detected_role, side_prior, reasons = _dominant_type(
            signals,
            header=header,
            agency_profile_hints=hints,
        )
        raw_profiles.append(
            ColumnRoleProfile(
                header=header,
                detected_type=detected_type,
                detected_role=detected_role,
                side_prior=side_prior,
                confidence=round(confidence, 3),
                reasons=reasons,
                semantic_signals=signals,
                neighbor_hints=[],
            ).as_dict()
        )
        raw_profiles[-1]["language_mix"] = _language_mix(values)
        raw_profiles[-1]["sample_count"] = len(values)
    for index, profile in enumerate(raw_profiles):
        neighbors: list[str] = []
        for offset in (-1, 1):
            neighbor_index = index + offset
            if 0 <= neighbor_index < len(raw_profiles):
                neighbor_type = str(raw_profiles[neighbor_index]["detected_type"] or "unknown")
                if neighbor_type != "unknown":
                    neighbors.append(neighbor_type)
        if str(profile["detected_type"]) == "phone" and any(
            neighbor in {"name", "unknown"} for neighbor in neighbors
        ):
            neighbors.append("root_identity_block")
        if (
            str(profile["detected_type"]) in {"action", "type", "price", "surface", "rooms"}
            and "location" in neighbors
        ):
            neighbors.append("child_intent_block")
        profile["neighbor_hints"] = neighbors
        profiles.append(profile)
    return profiles


def detected_columns_with_semantics(
    *,
    headers: list[str],
    sample_rows: list[dict[str, Any]],
    agency_id: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    hints = load_agency_profile_hints(agency_id)
    semantic_profiles = profile_columns(
        headers=headers,
        sample_rows=sample_rows,
        agency_profile_hints=hints,
    )
    detected_columns: list[dict[str, Any]] = []
    for index, profile in enumerate(semantic_profiles):
        header = str(profile.get("header", "") or "")
        values = [
            str(row.get(header, "") or "").strip()
            for row in sample_rows
            if str(row.get(header, "") or "").strip()
        ][:10]
        detected_columns.append(
            {
                "index": index,
                "header": header,
                "detected_type": str(profile.get("detected_type", "unknown") or "unknown"),
                "detected_role": str(profile.get("detected_role", "unknown") or "unknown"),
                "side_prior": str(profile.get("side_prior", "unknown") or "unknown"),
                "confidence": float(profile.get("confidence", 0.0) or 0.0),
                "sample_values": values[:3],
                "reasons": list(profile.get("reasons") or []),
                "semantic_signals": dict(profile.get("semantic_signals") or {}),
                "neighbor_hints": list(profile.get("neighbor_hints") or []),
            }
        )
    return detected_columns, hints


def build_semantic_evidence_rows(
    *,
    detected_columns: list[dict[str, Any]],
    sample_rows: list[dict[str, Any]],
) -> tuple[list[SemanticEvidenceRow], list[str]]:
    headers_by_domain: dict[str, list[str]] = {}
    for column in detected_columns:
        detected_type = str(column.get("detected_type", "unknown") or "unknown")
        header = str(column.get("header", "") or "")
        if not header or detected_type == "unknown":
            continue
        headers_by_domain.setdefault(detected_type, []).append(header)
    projection_conflicts = [
        f"{detected_type}: {', '.join(headers)}"
        for detected_type, headers in sorted(headers_by_domain.items())
        if len(headers) > 1
    ]

    evidence_rows: list[SemanticEvidenceRow] = []
    for row in sample_rows:
        cells: list[SemanticEvidenceCell] = []
        for column in detected_columns:
            header = str(column.get("header", "") or "")
            raw_value = str(row.get(header, "") or "").strip()
            if not header or not raw_value:
                continue
            detected_type = str(column.get("detected_type", "unknown") or "unknown")
            if detected_type == "unknown":
                continue
            cells.append(
                SemanticEvidenceCell(
                    header=header,
                    detected_type=detected_type,
                    detected_role=str(column.get("detected_role", "unknown") or "unknown"),
                    side_prior=str(column.get("side_prior", "unknown") or "unknown"),
                    value=raw_value,
                    confidence=float(column.get("confidence", 0.0) or 0.0),
                )
            )
        evidence_rows.append(SemanticEvidenceRow(cells=cells))
    return evidence_rows, projection_conflicts


__all__ = ["build_semantic_evidence_rows", "detected_columns_with_semantics", "profile_columns"]
