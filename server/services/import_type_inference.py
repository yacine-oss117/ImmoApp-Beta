"""Deterministic import entity and topology inference."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from server.services.import_constants import (
    ENTITY_TYPE_CLIENT,
    ENTITY_TYPE_DEMANDE,
    ENTITY_TYPE_LISTING,
    ENTITY_TYPE_OFFER,
)

ImportEntityType = str
TopologySide = str
ImportBundleMode = str

_UNSUPPORTED_CHILD_ONLY_MESSAGES: dict[str, str] = {
    ENTITY_TYPE_DEMANDE: (
        "Requests-only files aren't supported. Import clients with their requests in the same file."
    ),
    ENTITY_TYPE_OFFER: (
        "Offers-only files aren't supported. Import properties with their offers in the same file."
    ),
}

_ROOT_IDENTITY_FIELDS = {"family_name", "phone", "email", "name"}
_ROOT_METADATA_FIELDS = {"remarks", "tags", "status", "is_vip"}
_ROOT_FIELDS = _ROOT_IDENTITY_FIELDS.union(_ROOT_METADATA_FIELDS)
_DEMANDE_FIELDS = {
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
}
_OFFER_FIELDS = {
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
}
_SHARED_CHILD_FIELDS = _DEMANDE_FIELDS.intersection(_OFFER_FIELDS)
_DEMANDE_EXCLUSIVE_FIELDS = _DEMANDE_FIELDS.difference(_SHARED_CHILD_FIELDS)
_OFFER_EXCLUSIVE_FIELDS = _OFFER_FIELDS.difference(_SHARED_CHILD_FIELDS)


@dataclass(frozen=True)
class RowInferenceResult:
    entity_type: str | None
    topology_side: TopologySide
    confidence: float
    reasons: list[str]
    reason_codes: list[str] = dataclass_field(default_factory=list)


@dataclass(frozen=True)
class SemanticEvidenceCell:
    header: str
    detected_type: str
    detected_role: str
    side_prior: str
    value: str
    confidence: float


@dataclass(frozen=True)
class SemanticEvidenceRow:
    cells: list[SemanticEvidenceCell] = dataclass_field(default_factory=list)


def _normalize_key(value: object) -> str:
    return str(value or "").strip().lower()


def _non_empty(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _action_side(value: object) -> str | None:
    action = _normalize_key(value)
    if action in {"buy", "achat", "acheter", "buy/rent"}:
        return "client_side"
    if action in {"sell", "vente", "vendre"}:
        return "listing_side"
    if action in {"rent", "location", "louer"}:
        return None
    return None


def _score_row(row: dict[str, Any]) -> tuple[float, float, list[str], list[str]]:
    client_child = 0.0
    listing_child = 0.0
    client_reasons: list[str] = []
    listing_reasons: list[str] = []
    for field in _DEMANDE_FIELDS:
        if _non_empty(row.get(field)):
            client_child += 0.08
            client_reasons.append(f"{field} suggests demande")
    for field in _OFFER_FIELDS:
        if _non_empty(row.get(field)):
            listing_child += 0.08
            listing_reasons.append(f"{field} suggests offer")

    action_side = _action_side(row.get("action"))
    if action_side == "client_side":
        client_child += 0.2
        client_reasons.append("buy-style action")
    elif action_side == "listing_side":
        listing_child += 0.2
        listing_reasons.append("sell-style action")
    elif _non_empty(row.get("action")):
        client_child += 0.08
        listing_child += 0.08

    if _non_empty(row.get("budget_min")) or _non_empty(row.get("budget_max")):
        client_child += 0.18
        client_reasons.append("budget band fields")
    if _non_empty(row.get("surface_min")) or _non_empty(row.get("surface_max")):
        client_child += 0.12
        client_reasons.append("surface band fields")
    if _non_empty(row.get("locations")):
        client_child += 0.12
        client_reasons.append("multi-location preference field")

    if _non_empty(row.get("budget")):
        listing_child += 0.16
        listing_reasons.append("single price field")
    if _non_empty(row.get("surface")):
        listing_child += 0.12
        listing_reasons.append("single surface field")
    if _non_empty(row.get("location")):
        listing_child += 0.12
        listing_reasons.append("single location field")

    return min(client_child, 1.0), min(listing_child, 1.0), client_reasons, listing_reasons


def _has_root_identity(row: dict[str, Any]) -> bool:
    return any(_non_empty(row.get(field)) for field in _ROOT_IDENTITY_FIELDS)


def _has_same_row_bundle_identity(
    row: dict[str, Any],
    *,
    entity_type: str,
) -> bool:
    if not _has_root_identity(row):
        return False
    normalized_entity = str(entity_type or "").strip().lower()
    if normalized_entity == ENTITY_TYPE_DEMANDE:
        return any(_non_empty(row.get(field)) for field in _DEMANDE_EXCLUSIVE_FIELDS)
    if normalized_entity == ENTITY_TYPE_OFFER:
        return any(_non_empty(row.get(field)) for field in _OFFER_EXCLUSIVE_FIELDS)
    return False


def _has_child_field_signal(
    row: dict[str, Any],
    *,
    entity_type: str,
) -> bool:
    normalized_entity = str(entity_type or "").strip().lower()
    if normalized_entity == ENTITY_TYPE_DEMANDE:
        return any(_non_empty(row.get(field)) for field in _DEMANDE_EXCLUSIVE_FIELDS)
    if normalized_entity == ENTITY_TYPE_OFFER:
        return any(_non_empty(row.get(field)) for field in _OFFER_EXCLUSIVE_FIELDS)
    return False


def _same_side_contradiction(
    *,
    topology_side_hint: TopologySide,
    client_score: float,
    listing_score: float,
) -> bool:
    if topology_side_hint == "client_side":
        return listing_score >= 0.28 and listing_score >= (client_score + 0.12)
    if topology_side_hint == "listing_side":
        return client_score >= 0.28 and client_score >= (listing_score + 0.12)
    return False


def _is_root_like_row(row: dict[str, Any]) -> bool:
    if not _has_root_identity(row):
        return False
    client_score, listing_score, _client_reasons, _listing_reasons = _score_row(row)
    return client_score < 0.2 and listing_score < 0.2


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


def _coerce_evidence_rows(sample_rows: list[dict[str, Any]]) -> list[SemanticEvidenceRow]:
    evidence_rows: list[SemanticEvidenceRow] = []
    for item in sample_rows:
        raw_cells = item.get("cells") if isinstance(item, dict) else None
        if not isinstance(raw_cells, list):
            return []
        cells: list[SemanticEvidenceCell] = []
        for raw_cell in raw_cells:
            if not isinstance(raw_cell, dict):
                continue
            cells.append(
                SemanticEvidenceCell(
                    header=str(raw_cell.get("header", "") or ""),
                    detected_type=str(raw_cell.get("detected_type", "unknown") or "unknown"),
                    detected_role=str(raw_cell.get("detected_role", "unknown") or "unknown"),
                    side_prior=str(raw_cell.get("side_prior", "unknown") or "unknown"),
                    value=str(raw_cell.get("value", "") or ""),
                    confidence=_coerce_float(raw_cell.get("confidence", 0.0)),
                )
            )
        evidence_rows.append(SemanticEvidenceRow(cells=cells))
    return evidence_rows


def _looks_like_range_or_approximate(value: str) -> bool:
    text = _normalize_key(value)
    if not text:
        return False
    return any(
        token in text for token in {"-", "/", " a ", " to ", "entre", "environ", "~", "circa"}
    )


def _score_evidence_row(row: SemanticEvidenceRow) -> tuple[float, float, bool]:
    client_score = 0.0
    listing_score = 0.0
    has_root_identity = False
    for cell in row.cells:
        confidence = max(0.2, min(float(cell.confidence or 0.0), 1.0))
        side_prior = str(cell.side_prior or "unknown")
        detected_type = str(cell.detected_type or "unknown")
        detected_role = str(cell.detected_role or "unknown")
        value = str(cell.value or "")

        if detected_role == "root_identity":
            has_root_identity = True
        if side_prior == "client_root":
            client_score += 0.28 * confidence
        elif side_prior == "listing_root":
            listing_score += 0.28 * confidence

        if detected_role in {
            "child_budget_min",
            "child_budget_max",
            "child_surface_min",
            "child_surface_max",
            "child_beds_min",
            "child_floor_min",
            "child_floor_max",
            "child_geo_preference",
        }:
            client_score += 0.22 * confidence
        elif detected_role in {"child_price_scalar"}:
            listing_score += 0.22 * confidence
        elif side_prior == "shared_child":
            client_score += 0.06 * confidence
            listing_score += 0.06 * confidence

        if detected_type == "action":
            action_side = _action_side(value)
            if action_side == "client_side":
                client_score += 0.32 * confidence
            elif action_side == "listing_side":
                listing_score += 0.32 * confidence
            elif value.strip():
                client_score += 0.08 * confidence
                listing_score += 0.08 * confidence

        if detected_role == "child_budget_max" and _looks_like_range_or_approximate(value):
            client_score += 0.08 * confidence
        if detected_type == "location" and side_prior == "listing_root":
            listing_score += 0.08 * confidence
        if detected_type == "location" and side_prior == "client_root":
            client_score += 0.08 * confidence

    if has_root_identity:
        client_score += 0.06
        listing_score += 0.06
    mixed = (
        client_score >= 0.35 and listing_score >= 0.35 and abs(client_score - listing_score) < 0.15
    )
    return min(client_score, 1.0), min(listing_score, 1.0), mixed


def _file_model_from_evidence(
    evidence_rows: list[SemanticEvidenceRow],
    *,
    ui_hint: str | None,
) -> dict[str, Any]:
    client_root_score = 0.0
    listing_root_score = 0.0
    shared_child_score = 0.0
    row_client_votes = 0
    row_listing_votes = 0
    row_mixed_review_count = 0
    projection_conflicts: set[str] = set()
    root_identity_seen = False

    for row in evidence_rows:
        row_client, row_listing, row_mixed = _score_evidence_row(row)
        if row_mixed:
            row_mixed_review_count += 1
        elif row_client > row_listing and row_client >= 0.28:
            row_client_votes += 1
        elif row_listing > row_client and row_listing >= 0.28:
            row_listing_votes += 1
        domain_headers: dict[str, set[str]] = {}
        for cell in row.cells:
            if cell.detected_role == "root_identity":
                root_identity_seen = True
            if cell.side_prior == "client_root":
                client_root_score += 0.18 * max(cell.confidence, 0.3)
            elif cell.side_prior == "listing_root":
                listing_root_score += 0.18 * max(cell.confidence, 0.3)
            if cell.side_prior == "shared_child" or cell.detected_role.startswith("child_"):
                shared_child_score += 0.08 * max(cell.confidence, 0.3)
            if cell.detected_type != "unknown":
                domain_headers.setdefault(cell.detected_type, set()).add(cell.header)
        for detected_type, headers in domain_headers.items():
            if len(headers) > 1:
                projection_conflicts.add(f"{detected_type}: {', '.join(sorted(headers))}")

    total_rows = max(1, len(evidence_rows))
    client_row_ratio = row_client_votes / total_rows
    listing_row_ratio = row_listing_votes / total_rows
    mixed_ratio = row_mixed_review_count / total_rows
    dominant_side = "unknown"
    dominant_confidence = 0.0
    file_model_hint = "unknown"
    bundle_mode: ImportBundleMode = "single_entity"
    detected_entity: str | None = None
    reason_codes: list[str] = []
    ui_hint_used = False

    if mixed_ratio >= 0.2 or (client_row_ratio >= 0.2 and listing_row_ratio >= 0.2):
        dominant_side = "mixed"
        dominant_confidence = round(max(mixed_ratio, client_row_ratio, listing_row_ratio), 3)
        file_model_hint = "mixed"
        bundle_mode = "mixed_blocked"
        reason_codes.append("mixed_side_contamination")
    else:
        client_total = client_root_score + shared_child_score + (client_row_ratio * 0.8)
        listing_total = listing_root_score + shared_child_score + (listing_row_ratio * 0.8)
        if client_total >= 0.7 and client_total >= (listing_total + 0.15):
            dominant_side = "client_side"
            dominant_confidence = round(min(0.98, client_total), 3)
        elif listing_total >= 0.7 and listing_total >= (client_total + 0.15):
            dominant_side = "listing_side"
            dominant_confidence = round(min(0.98, listing_total), 3)
        if dominant_side == "client_side":
            if root_identity_seen and shared_child_score >= 0.12:
                file_model_hint = "client_lead_sheet"
                bundle_mode = "same_side_bundle"
                detected_entity = ENTITY_TYPE_CLIENT
                reason_codes.append("client_root_plus_preferences")
            else:
                detected_entity = (
                    ENTITY_TYPE_DEMANDE if client_row_ratio >= 0.35 else ENTITY_TYPE_CLIENT
                )
        elif dominant_side == "listing_side":
            if listing_root_score >= 0.18 and shared_child_score >= 0.12:
                file_model_hint = "listing_inventory"
                bundle_mode = "same_side_bundle"
                detected_entity = ENTITY_TYPE_LISTING
                reason_codes.append("listing_root_plus_offer_signals")
            elif root_identity_seen and shared_child_score >= 0.12:
                file_model_hint = "listing_inventory"
                bundle_mode = "same_side_bundle"
                detected_entity = ENTITY_TYPE_LISTING
                reason_codes.append("owner_rows_with_offer_signals")
            else:
                detected_entity = (
                    ENTITY_TYPE_OFFER if listing_row_ratio >= 0.35 else ENTITY_TYPE_LISTING
                )
        elif ui_hint:
            detected_entity = ui_hint
            dominant_side = (
                "client_side"
                if ui_hint in {ENTITY_TYPE_CLIENT, ENTITY_TYPE_DEMANDE}
                else "listing_side"
            )
            dominant_confidence = 0.51
            ui_hint_used = True

    reasons: list[str] = []
    if file_model_hint == "client_lead_sheet":
        reasons.append(
            "client identity columns and property-preference columns co-exist in the same file"
        )
    elif file_model_hint == "listing_inventory":
        reasons.append("owner/property signals dominate the workbook")
    elif file_model_hint == "mixed":
        reasons.append("opposite-side contamination affects too many sampled rows")
    elif ui_hint_used:
        reasons.append("ui hint broke an inference tie")
    else:
        reasons.append("no dominant file model was strong enough")
    final_payload = {
        "file_model_hint": file_model_hint,
        "dominant_side": dominant_side,
        "dominant_side_confidence": dominant_confidence,
        "bundle_mode": bundle_mode,
        "detected_entity": detected_entity,
        "reason_codes": list(reason_codes),
        "row_mixed_review_count": row_mixed_review_count,
        "semantic_projection_conflicts": sorted(projection_conflicts),
    }
    final_payload["ui_hint_used"] = ui_hint_used
    final_payload["reasons"] = reasons
    final_payload["topology_side_hint"] = "mixed" if dominant_side == "mixed" else dominant_side
    final_payload["confidence"] = dominant_confidence
    final_payload["entity_type_hint"] = (
        None if bundle_mode == "same_side_bundle" else detected_entity
    )
    return {
        "auto_inference": {
            "entity_type": detected_entity,
            "entity_type_hint": final_payload["entity_type_hint"],
            "topology_side_hint": final_payload["topology_side_hint"],
            "bundle_mode": bundle_mode,
            "confidence": dominant_confidence,
            "reasons": list(reasons),
            "reason_codes": list(reason_codes),
            "file_model_hint": file_model_hint,
            "dominant_side": dominant_side,
            "dominant_side_confidence": dominant_confidence,
            "row_mixed_review_count": row_mixed_review_count,
            "semantic_projection_conflicts": sorted(projection_conflicts),
        },
        "final_inference": final_payload,
    }


def infer_row_entity(
    row: dict[str, Any],
    *,
    bundle_mode: ImportBundleMode = "single_entity",
    default_entity_type: str | None = None,
    topology_side_hint: TopologySide = "unknown",
) -> RowInferenceResult:
    client_score, listing_score, client_reasons, listing_reasons = _score_row(row)
    has_root_fields = any(_non_empty(row.get(field)) for field in _ROOT_FIELDS)
    has_root_identity = _has_root_identity(row)

    if bundle_mode == "same_side_bundle":
        if topology_side_hint == "client_side":
            if _same_side_contradiction(
                topology_side_hint=topology_side_hint,
                client_score=client_score,
                listing_score=listing_score,
            ):
                return RowInferenceResult(
                    entity_type=None,
                    topology_side="unknown",
                    confidence=0.0,
                    reasons=["row carries listing-side signals inside a client-side bundle"],
                    reason_codes=["cross_side_contamination"],
                )
            if not has_root_identity and has_root_fields and client_score <= 0.2:
                return RowInferenceResult(
                    entity_type=None,
                    topology_side="unknown",
                    confidence=client_score,
                    reasons=[
                        "same-side bundle row has root metadata but not enough root identity to classify safely"
                    ],
                    reason_codes=["weak_root_evidence"],
                )
            if not has_root_identity and not has_root_fields and client_score <= 0.2:
                return RowInferenceResult(
                    entity_type=None,
                    topology_side="unknown",
                    confidence=client_score,
                    reasons=[
                        "same-side bundle row has only weak demande signals and no stable root identity"
                    ],
                    reason_codes=["ambiguous_same_side_shape"],
                )
            if _has_child_field_signal(row, entity_type=ENTITY_TYPE_DEMANDE):
                return RowInferenceResult(
                    entity_type=ENTITY_TYPE_DEMANDE,
                    topology_side="client_side",
                    confidence=max(0.55, client_score),
                    reasons=client_reasons
                    or ["same-row demande fields were detected inside the bundle"],
                )
            if client_score >= 0.2:
                return RowInferenceResult(
                    entity_type=ENTITY_TYPE_DEMANDE,
                    topology_side="client_side",
                    confidence=max(0.65, client_score),
                    reasons=client_reasons,
                )
            if has_root_identity:
                return RowInferenceResult(
                    entity_type=ENTITY_TYPE_CLIENT,
                    topology_side="client_side",
                    confidence=0.72,
                    reasons=["root identity fields without demande semantics"],
                    reason_codes=["weak_child_evidence"] if client_score > 0 else [],
                )
            if has_root_fields or client_score > 0 or listing_score > 0:
                return RowInferenceResult(
                    entity_type=None,
                    topology_side="unknown",
                    confidence=max(client_score, listing_score),
                    reasons=[
                        "same-side bundle row does not have enough stable client or demande evidence"
                    ],
                    reason_codes=[
                        "weak_root_evidence" if has_root_fields else "ambiguous_same_side_shape"
                    ],
                )
        if topology_side_hint == "listing_side":
            if _same_side_contradiction(
                topology_side_hint=topology_side_hint,
                client_score=client_score,
                listing_score=listing_score,
            ):
                return RowInferenceResult(
                    entity_type=None,
                    topology_side="unknown",
                    confidence=0.0,
                    reasons=["row carries client-side signals inside a listing-side bundle"],
                    reason_codes=["cross_side_contamination"],
                )
            if not has_root_identity and has_root_fields and listing_score <= 0.2:
                return RowInferenceResult(
                    entity_type=None,
                    topology_side="unknown",
                    confidence=listing_score,
                    reasons=[
                        "same-side bundle row has root metadata but not enough root identity to classify safely"
                    ],
                    reason_codes=["weak_root_evidence"],
                )
            if not has_root_identity and not has_root_fields and listing_score <= 0.2:
                return RowInferenceResult(
                    entity_type=None,
                    topology_side="unknown",
                    confidence=listing_score,
                    reasons=[
                        "same-side bundle row has only weak offer signals and no stable root identity"
                    ],
                    reason_codes=["ambiguous_same_side_shape"],
                )
            if _has_child_field_signal(row, entity_type=ENTITY_TYPE_OFFER):
                return RowInferenceResult(
                    entity_type=ENTITY_TYPE_OFFER,
                    topology_side="listing_side",
                    confidence=max(0.55, listing_score),
                    reasons=listing_reasons
                    or ["same-row offer fields were detected inside the bundle"],
                )
            if listing_score >= 0.2:
                return RowInferenceResult(
                    entity_type=ENTITY_TYPE_OFFER,
                    topology_side="listing_side",
                    confidence=max(0.65, listing_score),
                    reasons=listing_reasons,
                )
            if has_root_identity:
                return RowInferenceResult(
                    entity_type=ENTITY_TYPE_LISTING,
                    topology_side="listing_side",
                    confidence=0.72,
                    reasons=["root identity fields without offer semantics"],
                    reason_codes=["weak_child_evidence"] if listing_score > 0 else [],
                )
            if has_root_fields or client_score > 0 or listing_score > 0:
                return RowInferenceResult(
                    entity_type=None,
                    topology_side="unknown",
                    confidence=max(client_score, listing_score),
                    reasons=[
                        "same-side bundle row does not have enough stable property or offer evidence"
                    ],
                    reason_codes=[
                        "weak_root_evidence" if has_root_fields else "ambiguous_same_side_shape"
                    ],
                )

    if default_entity_type:
        return RowInferenceResult(
            entity_type=default_entity_type,
            topology_side=(
                "client_side"
                if default_entity_type in {ENTITY_TYPE_CLIENT, ENTITY_TYPE_DEMANDE}
                else "listing_side"
            ),
            confidence=0.7,
            reasons=["defaulted from file inference"],
        )

    if client_score > listing_score and client_score >= 0.2:
        return RowInferenceResult(
            entity_type=ENTITY_TYPE_DEMANDE,
            topology_side="client_side",
            confidence=client_score,
            reasons=client_reasons,
        )
    if listing_score > client_score and listing_score >= 0.2:
        return RowInferenceResult(
            entity_type=ENTITY_TYPE_OFFER,
            topology_side="listing_side",
            confidence=listing_score,
            reasons=listing_reasons,
        )
    if has_root_fields:
        entity_type = default_entity_type or ENTITY_TYPE_CLIENT
        topology_side = "client_side" if entity_type == ENTITY_TYPE_CLIENT else "listing_side"
        return RowInferenceResult(
            entity_type=entity_type,
            topology_side=topology_side,
            confidence=0.51,
            reasons=["root-only row shape"],
        )
    return RowInferenceResult(
        entity_type=None,
        topology_side="unknown",
        confidence=0.0,
        reasons=["no stable import signals"],
    )


def infer_file_type(
    *,
    headers: list[str],
    sample_rows: list[dict[str, Any]],
    ui_hint: str | None,
) -> dict[str, Any]:
    evidence_rows = _coerce_evidence_rows(sample_rows)
    if evidence_rows:
        return _file_model_from_evidence(
            evidence_rows,
            ui_hint=ui_hint,
        )

    normalized_headers = {_normalize_key(header) for header in headers if _normalize_key(header)}
    has_root_identity_headers = bool(normalized_headers.intersection(_ROOT_IDENTITY_FIELDS))
    client_header_hits = len(normalized_headers.intersection(_DEMANDE_EXCLUSIVE_FIELDS))
    listing_header_hits = len(normalized_headers.intersection(_OFFER_EXCLUSIVE_FIELDS))
    mixed_header_hits = client_header_hits > 0 and listing_header_hits > 0

    row_results = [
        infer_row_entity(dict(row), default_entity_type=None) for row in sample_rows[:25]
    ]
    demande_rows = sum(1 for result in row_results if result.entity_type == ENTITY_TYPE_DEMANDE)
    offer_rows = sum(1 for result in row_results if result.entity_type == ENTITY_TYPE_OFFER)
    root_like_rows = sum(1 for row in sample_rows[:25] if _is_root_like_row(dict(row)))
    combined_demande_rows = sum(
        1
        for row, result in zip(sample_rows[:25], row_results, strict=False)
        if result.entity_type == ENTITY_TYPE_DEMANDE
        and _has_same_row_bundle_identity(dict(row), entity_type=ENTITY_TYPE_DEMANDE)
    )
    combined_offer_rows = sum(
        1
        for row, result in zip(sample_rows[:25], row_results, strict=False)
        if result.entity_type == ENTITY_TYPE_OFFER
        and _has_same_row_bundle_identity(dict(row), entity_type=ENTITY_TYPE_OFFER)
    )

    reasons: list[str] = []
    auto_entity_type: str | None = None
    topology_side_hint: TopologySide = "unknown"
    bundle_mode: ImportBundleMode = "single_entity"
    entity_type_hint: str | None = None
    confidence = 0.0
    ui_hint_used = False

    if mixed_header_hits or (demande_rows > 0 and offer_rows > 0):
        bundle_mode = "mixed_blocked"
        topology_side_hint = "mixed"
        reasons.append("file mixes client-side and listing-side signals")
    elif (
        has_root_identity_headers
        and demande_rows > 0
        and (root_like_rows > 0 or combined_demande_rows > 0)
    ):
        bundle_mode = "same_side_bundle"
        topology_side_hint = "client_side"
        auto_entity_type = ENTITY_TYPE_CLIENT
        confidence = 0.82
        reasons.append("client identity and demande signals co-exist in the same file")
    elif (
        has_root_identity_headers
        and offer_rows > 0
        and (root_like_rows > 0 or combined_offer_rows > 0)
    ):
        bundle_mode = "same_side_bundle"
        topology_side_hint = "listing_side"
        auto_entity_type = ENTITY_TYPE_LISTING
        confidence = 0.82
        reasons.append("listing identity and offer signals co-exist in the same file")
    elif client_header_hits > 0 or demande_rows > offer_rows:
        topology_side_hint = "client_side"
        entity_type_hint = ENTITY_TYPE_DEMANDE if demande_rows > 0 else ENTITY_TYPE_CLIENT
        auto_entity_type = (
            ENTITY_TYPE_CLIENT if entity_type_hint == ENTITY_TYPE_CLIENT else ENTITY_TYPE_DEMANDE
        )
        confidence = 0.76 if entity_type_hint == ENTITY_TYPE_DEMANDE else 0.68
        reasons.append("client-side semantic signals dominate")
    elif listing_header_hits > 0 or offer_rows > demande_rows:
        topology_side_hint = "listing_side"
        entity_type_hint = ENTITY_TYPE_OFFER if offer_rows > 0 else ENTITY_TYPE_LISTING
        auto_entity_type = (
            ENTITY_TYPE_LISTING if entity_type_hint == ENTITY_TYPE_LISTING else ENTITY_TYPE_OFFER
        )
        confidence = 0.76 if entity_type_hint == ENTITY_TYPE_OFFER else 0.68
        reasons.append("listing-side semantic signals dominate")

    final_entity = auto_entity_type
    if bundle_mode == "same_side_bundle":
        entity_type_hint = None
    elif bundle_mode == "mixed_blocked":
        final_entity = None
        entity_type_hint = None
        confidence = max(confidence, 0.4)
    else:
        if entity_type_hint is None:
            entity_type_hint = final_entity

    if final_entity is None and ui_hint and bundle_mode != "mixed_blocked":
        final_entity = ui_hint
        entity_type_hint = ui_hint
        confidence = max(confidence, 0.51)
        ui_hint_used = True
        reasons.append("ui hint broke an inference tie")

    if not reasons:
        reasons.append("no strong header or semantic signal found")

    return {
        "auto_inference": {
            "entity_type": auto_entity_type,
            "entity_type_hint": entity_type_hint,
            "topology_side_hint": topology_side_hint,
            "bundle_mode": bundle_mode,
            "confidence": round(confidence, 3),
            "reasons": reasons,
            "reason_codes": [],
            "file_model_hint": "unknown",
            "dominant_side": topology_side_hint if topology_side_hint != "unknown" else "unknown",
            "dominant_side_confidence": round(confidence, 3),
            "row_mixed_review_count": 0,
            "semantic_projection_conflicts": [],
        },
        "final_inference": {
            "detected_entity": final_entity,
            "entity_type_hint": entity_type_hint,
            "topology_side_hint": topology_side_hint,
            "bundle_mode": bundle_mode,
            "confidence": round(confidence, 3),
            "reasons": reasons,
            "ui_hint_used": ui_hint_used,
            "reason_codes": [],
            "file_model_hint": "unknown",
            "dominant_side": topology_side_hint if topology_side_hint != "unknown" else "unknown",
            "dominant_side_confidence": round(confidence, 3),
            "row_mixed_review_count": 0,
            "semantic_projection_conflicts": [],
        },
    }


def unsupported_child_only_import_message(final_inference: dict[str, Any] | Any) -> str | None:
    normalized = dict(final_inference or {})
    bundle_mode = str(normalized.get("bundle_mode", "single_entity") or "single_entity")
    if bundle_mode != "single_entity":
        return None
    detected_entity = str(
        normalized.get("detected_entity")
        or normalized.get("entity_type_hint")
        or normalized.get("entity_type")
        or ""
    ).strip()
    return _UNSUPPORTED_CHILD_ONLY_MESSAGES.get(detected_entity)


__all__ = [
    "ImportBundleMode",
    "ImportEntityType",
    "RowInferenceResult",
    "TopologySide",
    "infer_file_type",
    "infer_row_entity",
    "unsupported_child_only_import_message",
]
