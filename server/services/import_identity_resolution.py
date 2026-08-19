"""Deterministic identity resolution for import review and execution."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, TypeVar, cast

from server.services.duplicate_checker import (
    DatabaseDuplicateChecker,
    DbDuplicateCandidate,
    _normalize_name_for_match,
    _normalize_phone_for_dedup,
    _score_candidates_for_row,
)
from server.services.import_constants import (
    ENTITY_TYPE_CLIENT,
    ENTITY_TYPE_DEMANDE,
    ENTITY_TYPE_LISTING,
    ENTITY_TYPE_OFFER,
)
from server.services.import_diff_builder import build_field_diff, flatten_field_diffs
from server.services.import_review_policy import (
    CREATE_NEW,
    REVIEW_AMBIGUOUS,
    UPDATE_EXISTING,
    decision_policy_for_entity,
)


@dataclass
class ResolutionResult:
    candidate_matches: list[dict[str, Any]] = field(default_factory=list)
    suggested_action: str = CREATE_NEW
    suggested_existing_id: int = 0
    suggested_confidence: float = 0.0
    suggested_reasons: list[str] = field(default_factory=list)
    anchor_id: int = 0


_CacheKey = TypeVar("_CacheKey")
_CacheValue = TypeVar("_CacheValue")


@dataclass
class IdentityResolutionCache:
    max_entries: int = 4096
    root_phone_candidates: dict[tuple[str, int, str], list[DbDuplicateCandidate]] = field(
        default_factory=OrderedDict
    )
    child_candidates: dict[tuple[str, int, int], list[dict[str, Any]]] = field(
        default_factory=OrderedDict
    )
    child_anchor_ids: dict[tuple[str, int, tuple[str, ...]], int] = field(
        default_factory=OrderedDict
    )

    def _remember(
        self,
        cache_map: dict[_CacheKey, _CacheValue],
        key: _CacheKey,
        value: _CacheValue,
    ) -> None:
        if key in cache_map:
            del cache_map[key]
        cache_map[key] = value
        while len(cache_map) > max(1, int(self.max_entries or 4096)):
            cast(OrderedDict[_CacheKey, _CacheValue], cache_map).popitem(last=False)

    def _recall(
        self,
        cache_map: dict[_CacheKey, _CacheValue],
        key: _CacheKey,
    ) -> _CacheValue | None:
        if key not in cache_map:
            return None
        value = cache_map[key]
        del cache_map[key]
        cache_map[key] = value
        return value

    def get_root_phone_candidates(
        self,
        key: tuple[str, int, str],
    ) -> list[DbDuplicateCandidate] | None:
        cached = self._recall(self.root_phone_candidates, key)
        if cached is None:
            return None
        return _clone_duplicate_candidates(cast(list[DbDuplicateCandidate], cached))

    def set_root_phone_candidates(
        self,
        key: tuple[str, int, str],
        value: list[DbDuplicateCandidate],
    ) -> None:
        self._remember(self.root_phone_candidates, key, _clone_duplicate_candidates(value))

    def has_root_phone_candidates(self, key: tuple[str, int, str]) -> bool:
        return key in self.root_phone_candidates

    def get_child_candidates(
        self,
        key: tuple[str, int, int],
    ) -> list[dict[str, Any]] | None:
        cached = self._recall(self.child_candidates, key)
        if cached is None:
            return None
        return [dict(row) for row in cast(list[dict[str, Any]], cached)]

    def set_child_candidates(
        self,
        key: tuple[str, int, int],
        value: list[dict[str, Any]],
    ) -> None:
        self._remember(self.child_candidates, key, [dict(row) for row in value])

    def has_child_candidates(self, key: tuple[str, int, int]) -> bool:
        return key in self.child_candidates

    def get_child_anchor_id(
        self,
        key: tuple[str, int, tuple[str, ...]],
    ) -> int | None:
        cached = self._recall(self.child_anchor_ids, key)
        return cached if cached is not None else None

    def set_child_anchor_id(
        self,
        key: tuple[str, int, tuple[str, ...]],
        value: int,
    ) -> None:
        self._remember(self.child_anchor_ids, key, int(value))


def _clone_duplicate_candidates(
    candidates: list[DbDuplicateCandidate],
) -> list[DbDuplicateCandidate]:
    return [
        DbDuplicateCandidate(
            existing_id=int(candidate.existing_id),
            row_version=int(candidate.row_version),
            family_name=str(candidate.family_name),
            phone=str(candidate.phone),
            status=str(candidate.status),
            remarks=str(candidate.remarks),
            match_confidence=float(getattr(candidate, "match_confidence", 0.0) or 0.0),
            match_reasons=list(getattr(candidate, "match_reasons", []) or []),
        )
        for candidate in candidates
    ]


def prefetch_root_match_cache(
    *,
    entity_type: str,
    rows: list[dict[str, Any]],
    session: Any,
    agency_id: int,
    cache: IdentityResolutionCache,
) -> None:
    checker = DatabaseDuplicateChecker()
    missing_phones: list[str] = []
    seen_phones: set[str] = set()
    normalized_agency_id = int(agency_id)

    for row_data in rows:
        normalized_phone = _normalize_phone_for_dedup(str(row_data.get("phone", "") or ""))
        if not normalized_phone or normalized_phone in seen_phones:
            continue
        seen_phones.add(normalized_phone)
        cache_key = (entity_type, normalized_agency_id, normalized_phone)
        if cache.has_root_phone_candidates(cache_key):
            continue
        missing_phones.append(normalized_phone)

    if not missing_phones:
        return

    raw_candidates = checker._lookup_phones(
        missing_phones,
        entity_type,
        session,
        agency_id=normalized_agency_id,
    )
    for normalized_phone in missing_phones:
        candidates = list(raw_candidates.get(normalized_phone, []))
        cache.set_root_phone_candidates(
            (entity_type, normalized_agency_id, normalized_phone),
            candidates,
        )


def prefetch_child_match_cache(
    *,
    entity_type: str,
    anchor_ids: set[int],
    session: Any,
    agency_id: int,
    cache: IdentityResolutionCache,
) -> None:
    normalized_agency_id = int(agency_id)
    missing_anchor_ids = sorted(
        {
            int(anchor_id)
            for anchor_id in anchor_ids
            if int(anchor_id) > 0
            and not cache.has_child_candidates((entity_type, normalized_agency_id, int(anchor_id)))
        }
    )
    if not missing_anchor_ids:
        return

    if entity_type == ENTITY_TYPE_DEMANDE:
        rows = session.execute(
            """
            SELECT id, client_id, type, type_id, action, action_id, wilaya, wilaya_id, locations,
                   beds_min, surface_min, surface_max, budget_min, budget_max, furnished,
                   floor_min, floor_max, elevator, accessibility_required, tags, remarks, row_version
            FROM demandes
            WHERE client_id = ANY(%s) AND agency_id = %s AND deleted_at IS NULL
            ORDER BY client_id, id
            """,
            (missing_anchor_ids, normalized_agency_id),
        ).fetchall()
        anchor_field = "client_id"
    elif entity_type == ENTITY_TYPE_OFFER:
        rows = session.execute(
            """
            SELECT id, listing_id, type, type_id, action, action_id, wilaya, wilaya_id, location,
                   beds, surface, budget, furnished, floor, elevator, accessibility_supported,
                   price_negotiable, price_flex_pct, link, latitude, longitude, remarks, status,
                   row_version
            FROM offers
            WHERE listing_id = ANY(%s) AND agency_id = %s AND deleted_at IS NULL
            ORDER BY listing_id, id
            """,
            (missing_anchor_ids, normalized_agency_id),
        ).fetchall()
        anchor_field = "listing_id"
    else:
        return

    grouped_rows: dict[int, list[dict[str, Any]]] = {
        anchor_id: [] for anchor_id in missing_anchor_ids
    }
    for row in rows:
        normalized_row = dict(row)
        grouped_rows.setdefault(int(normalized_row.get(anchor_field, 0) or 0), []).append(
            normalized_row
        )

    for anchor_id in missing_anchor_ids:
        cache.set_child_candidates(
            (entity_type, normalized_agency_id, anchor_id),
            [dict(row) for row in grouped_rows.get(anchor_id, [])],
        )


def _overlap_score(
    incoming_min: float | int | None,
    incoming_max: float | int | None,
    existing_min: float | int | None,
    existing_max: float | int | None,
) -> float:
    if incoming_min is None or incoming_max is None or existing_min is None or existing_max is None:
        return 0.0
    left = max(float(incoming_min), float(existing_min))
    right = min(float(incoming_max), float(existing_max))
    if right < left:
        return 0.0
    incoming_span = max(1.0, float(incoming_max) - float(incoming_min))
    existing_span = max(1.0, float(existing_max) - float(existing_min))
    overlap = right - left
    return max(0.0, min(1.0, overlap / min(incoming_span, existing_span)))


def _scalar_similarity(left: object, right: object) -> float:
    left_text = _normalize_name_for_match(left)
    right_text = _normalize_name_for_match(right)
    if not left_text or not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    return max(0.0, min(1.0, SequenceMatcher(None, left_text, right_text).ratio()))


def _candidate_payload_from_row(entity_type: str, row: dict[str, Any]) -> dict[str, Any]:
    policy = decision_policy_for_entity(entity_type)
    fields = list(policy.mutable_fields) + list(policy.immutable_fields)
    return {field: row.get(field) for field in fields if field in row}


def _finalize_result(
    *,
    entity_type: str,
    candidates: list[dict[str, Any]],
    suggested_action: str,
    suggested_existing_id: int,
) -> ResolutionResult:
    suggested_confidence = 0.0
    suggested_reasons: list[str] = []
    for candidate in candidates:
        if int(candidate.get("id", 0) or 0) == suggested_existing_id:
            suggested_confidence = float(candidate.get("match_confidence", 0.0) or 0.0)
            suggested_reasons = list(candidate.get("match_reasons", []) or [])
            break
    return ResolutionResult(
        candidate_matches=candidates,
        suggested_action=suggested_action,
        suggested_existing_id=suggested_existing_id,
        suggested_confidence=round(suggested_confidence, 3),
        suggested_reasons=suggested_reasons,
        anchor_id=(
            suggested_existing_id if entity_type in {ENTITY_TYPE_CLIENT, ENTITY_TYPE_LISTING} else 0
        ),
    )


def resolve_root_matches(
    *,
    entity_type: str,
    row_data: dict[str, Any],
    session: Any,
    agency_id: int,
    cache: IdentityResolutionCache | None = None,
) -> ResolutionResult:
    checker = DatabaseDuplicateChecker()
    normalized_phone = _normalize_phone_for_dedup(str(row_data.get("phone", "") or ""))
    if not normalized_phone:
        return ResolutionResult()
    cache_key = (entity_type, int(agency_id), normalized_phone)
    cached_candidates = cache.get_root_phone_candidates(cache_key) if cache is not None else None
    if cached_candidates is not None:
        candidates = cached_candidates
    else:
        raw_candidates = checker._lookup_phones(
            [normalized_phone], entity_type, session, agency_id=agency_id
        )
        candidates = list(raw_candidates.get(normalized_phone, []))
        if cache is not None:
            cache.set_root_phone_candidates(cache_key, candidates)
    if not candidates:
        return ResolutionResult()
    scored, suggested_action, suggested_existing_id = _score_candidates_for_row(
        row_data, candidates
    )
    matched_rows: list[dict[str, Any]] = []
    for candidate in scored:
        candidate_payload = {
            "id": int(candidate.existing_id),
            "row_version": int(candidate.row_version),
            "family_name": str(candidate.family_name),
            "phone": str(candidate.phone),
            "remarks": str(candidate.remarks),
            "status": str(candidate.status),
        }
        field_diff = build_field_diff(
            entity_type=entity_type,
            incoming=row_data,
            existing=candidate_payload,
        )
        matched_rows.append(
            {
                **candidate_payload,
                "match_confidence": round(candidate.match_confidence, 3),
                "match_reasons": list(candidate.match_reasons),
                "field_diff": field_diff,
                "field_diffs": flatten_field_diffs(field_diff),
                "snapshot": candidate_payload,
            }
        )
    return _finalize_result(
        entity_type=entity_type,
        candidates=matched_rows,
        suggested_action=suggested_action,
        suggested_existing_id=suggested_existing_id,
    )


def _query_child_candidates(
    *,
    entity_type: str,
    anchor_id: int,
    session: Any,
    agency_id: int,
    cache: IdentityResolutionCache | None = None,
) -> list[dict[str, Any]]:
    cache_key = (entity_type, int(agency_id), int(anchor_id))
    cached_rows = cache.get_child_candidates(cache_key) if cache is not None else None
    if cached_rows is not None:
        return cached_rows
    if entity_type == ENTITY_TYPE_DEMANDE:
        rows = session.execute(
            """
            SELECT id, client_id, type, type_id, action, action_id, wilaya, wilaya_id, locations,
                   beds_min, surface_min, surface_max, budget_min, budget_max, furnished,
                   floor_min, floor_max, elevator, accessibility_required, tags, remarks, row_version
            FROM demandes
            WHERE client_id = %s AND agency_id = %s AND deleted_at IS NULL
            ORDER BY id
            """,
            (anchor_id, agency_id),
        ).fetchall()
    elif entity_type == ENTITY_TYPE_OFFER:
        rows = session.execute(
            """
            SELECT id, listing_id, type, type_id, action, action_id, wilaya, wilaya_id, location,
                   beds, surface, budget, furnished, floor, elevator, accessibility_supported,
                   price_negotiable, price_flex_pct, link, latitude, longitude, remarks, status,
                   row_version
            FROM offers
            WHERE listing_id = %s AND agency_id = %s AND deleted_at IS NULL
            ORDER BY id
            """,
            (anchor_id, agency_id),
        ).fetchall()
    else:
        return []
    normalized_rows = [dict(row) for row in rows]
    if cache is not None:
        cache.set_child_candidates(cache_key, normalized_rows)
    return normalized_rows


def _score_demande(row_data: dict[str, Any], candidate: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.2
    reasons: list[str] = ["same client anchor"]
    if str(row_data.get("action", "")) == str(candidate.get("action", "")):
        score += 0.2
        reasons.append("same action")
    if str(row_data.get("type", "")) == str(candidate.get("type", "")) or (
        row_data.get("type_id") and row_data.get("type_id") == candidate.get("type_id")
    ):
        score += 0.18
        reasons.append("same property type")
    if str(row_data.get("wilaya", "")) == str(candidate.get("wilaya", "")) or (
        row_data.get("wilaya_id") and row_data.get("wilaya_id") == candidate.get("wilaya_id")
    ):
        score += 0.12
        reasons.append("same wilaya")
    if _scalar_similarity(row_data.get("locations"), candidate.get("locations")) >= 0.8:
        score += 0.1
        reasons.append("similar locations")
    if (
        _overlap_score(
            row_data.get("budget_min"),
            row_data.get("budget_max"),
            candidate.get("budget_min"),
            candidate.get("budget_max"),
        )
        > 0.4
    ):
        score += 0.12
        reasons.append("budget bands overlap")
    if (
        _overlap_score(
            row_data.get("surface_min"),
            row_data.get("surface_max"),
            candidate.get("surface_min"),
            candidate.get("surface_max"),
        )
        > 0.4
    ):
        score += 0.11
        reasons.append("surface bands overlap")
    if row_data.get("beds_min") == candidate.get("beds_min"):
        score += 0.07
        reasons.append("same minimum beds")
    return round(min(1.0, score), 3), reasons


def _score_offer(row_data: dict[str, Any], candidate: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.2
    reasons: list[str] = ["same listing anchor"]
    if str(row_data.get("action", "")) == str(candidate.get("action", "")):
        score += 0.2
        reasons.append("same action")
    if str(row_data.get("type", "")) == str(candidate.get("type", "")) or (
        row_data.get("type_id") and row_data.get("type_id") == candidate.get("type_id")
    ):
        score += 0.18
        reasons.append("same property type")
    if str(row_data.get("wilaya", "")) == str(candidate.get("wilaya", "")) or (
        row_data.get("wilaya_id") and row_data.get("wilaya_id") == candidate.get("wilaya_id")
    ):
        score += 0.12
        reasons.append("same wilaya")
    if _scalar_similarity(row_data.get("location"), candidate.get("location")) >= 0.84:
        score += 0.1
        reasons.append("similar location")
    budget = row_data.get("budget")
    existing_budget = candidate.get("budget")
    if budget is not None and existing_budget is not None:
        diff_ratio = abs(float(budget) - float(existing_budget)) / max(1.0, float(existing_budget))
        if diff_ratio <= 0.1:
            score += 0.12
            reasons.append("price within band")
    surface = row_data.get("surface")
    existing_surface = candidate.get("surface")
    if surface is not None and existing_surface is not None:
        diff_ratio = abs(float(surface) - float(existing_surface)) / max(
            1.0, float(existing_surface)
        )
        if diff_ratio <= 0.1:
            score += 0.1
            reasons.append("surface within band")
    if row_data.get("beds") == candidate.get("beds"):
        score += 0.08
        reasons.append("same beds")
    return round(min(1.0, score), 3), reasons


def resolve_child_matches(
    *,
    entity_type: str,
    row_data: dict[str, Any],
    session: Any,
    agency_id: int,
    anchor_id: int,
    cache: IdentityResolutionCache | None = None,
) -> ResolutionResult:
    if anchor_id <= 0:
        return ResolutionResult(suggested_action=REVIEW_AMBIGUOUS)
    candidates = _query_child_candidates(
        entity_type=entity_type,
        anchor_id=anchor_id,
        session=session,
        agency_id=agency_id,
        cache=cache,
    )
    if not candidates:
        return ResolutionResult(suggested_action=CREATE_NEW, anchor_id=anchor_id)

    scored_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        if entity_type == ENTITY_TYPE_DEMANDE:
            confidence, reasons = _score_demande(row_data, candidate)
        else:
            confidence, reasons = _score_offer(row_data, candidate)
        field_diff = build_field_diff(
            entity_type=entity_type, incoming=row_data, existing=candidate
        )
        scored_candidates.append(
            {
                "id": int(candidate.get("id", 0) or 0),
                "row_version": int(candidate.get("row_version", 0) or 0),
                "match_confidence": confidence,
                "match_reasons": reasons,
                "field_diff": field_diff,
                "field_diffs": flatten_field_diffs(field_diff),
                "snapshot": _candidate_payload_from_row(entity_type, candidate),
                **_candidate_payload_from_row(entity_type, candidate),
            }
        )
    scored_candidates.sort(key=lambda item: (-float(item["match_confidence"]), int(item["id"])))
    top = scored_candidates[0]
    runner_up = (
        float(scored_candidates[1]["match_confidence"]) if len(scored_candidates) > 1 else 0.0
    )
    top_score = float(top["match_confidence"])
    if top_score >= 0.93 and (len(scored_candidates) == 1 or top_score - runner_up >= 0.12):
        action = UPDATE_EXISTING
    elif top_score >= 0.65:
        action = REVIEW_AMBIGUOUS
    else:
        action = CREATE_NEW
    return ResolutionResult(
        candidate_matches=scored_candidates[:5],
        suggested_action=action,
        suggested_existing_id=int(top["id"] if action != CREATE_NEW else 0),
        suggested_confidence=top_score,
        suggested_reasons=list(top.get("match_reasons", []) or []),
        anchor_id=anchor_id,
    )


def resolve_existing_matches(
    *,
    entity_type: str,
    row_data: dict[str, Any],
    session: Any,
    agency_id: int,
    anchor_id: int = 0,
    cache: IdentityResolutionCache | None = None,
) -> ResolutionResult:
    if entity_type in {ENTITY_TYPE_CLIENT, ENTITY_TYPE_LISTING}:
        return resolve_root_matches(
            entity_type=entity_type,
            row_data=row_data,
            session=session,
            agency_id=agency_id,
            cache=cache,
        )
    if entity_type in {ENTITY_TYPE_DEMANDE, ENTITY_TYPE_OFFER}:
        return resolve_child_matches(
            entity_type=entity_type,
            row_data=row_data,
            session=session,
            agency_id=agency_id,
            anchor_id=anchor_id,
            cache=cache,
        )
    return ResolutionResult()


def resolve_child_anchor(
    *,
    topology_side: str,
    row_data: dict[str, Any],
    session: Any,
    agency_id: int,
    local_anchor_map: dict[str, int] | None = None,
    cache: IdentityResolutionCache | None = None,
) -> int:
    def _candidate_anchor_keys() -> list[str]:
        keys: list[str] = []
        phone = _normalize_phone_for_dedup(str(row_data.get("phone", "") or ""))
        if phone:
            keys.append(f"phone:{phone}")
            keys.append(phone)
        family_name = _normalize_name_for_match(
            row_data.get("family_name", row_data.get("name", ""))
        )
        if family_name:
            keys.append(f"name:{family_name}")
            keys.append(family_name)
        return keys

    candidate_keys = tuple(_candidate_anchor_keys())
    cache_key = (topology_side, int(agency_id), candidate_keys)

    if topology_side == "client_side":
        explicit_id = int(row_data.get("client_id", 0) or 0)
        if explicit_id > 0:
            return explicit_id
        if local_anchor_map:
            for key in candidate_keys:
                if key in local_anchor_map:
                    return int(local_anchor_map[key])
        cached_anchor_id = cache.get_child_anchor_id(cache_key) if cache is not None else None
        if cached_anchor_id is not None:
            return cached_anchor_id
        result = resolve_root_matches(
            entity_type=ENTITY_TYPE_CLIENT,
            row_data=row_data,
            session=session,
            agency_id=agency_id,
            cache=cache,
        )
        if result.suggested_action == UPDATE_EXISTING and result.suggested_existing_id > 0:
            resolved_anchor = int(result.suggested_existing_id)
            if cache is not None:
                cache.set_child_anchor_id(cache_key, resolved_anchor)
            return resolved_anchor
        if result.candidate_matches:
            if cache is not None:
                cache.set_child_anchor_id(cache_key, -1)
            return -1
        if cache is not None:
            cache.set_child_anchor_id(cache_key, 0)
        return 0
    explicit_id = int(row_data.get("listing_id", 0) or 0)
    if explicit_id > 0:
        return explicit_id
    if local_anchor_map:
        for key in candidate_keys:
            if key in local_anchor_map:
                return int(local_anchor_map[key])
    cached_anchor_id = cache.get_child_anchor_id(cache_key) if cache is not None else None
    if cached_anchor_id is not None:
        return cached_anchor_id
    result = resolve_root_matches(
        entity_type=ENTITY_TYPE_LISTING,
        row_data=row_data,
        session=session,
        agency_id=agency_id,
        cache=cache,
    )
    if result.suggested_action == UPDATE_EXISTING and result.suggested_existing_id > 0:
        resolved_anchor = int(result.suggested_existing_id)
        if cache is not None:
            cache.set_child_anchor_id(cache_key, resolved_anchor)
        return resolved_anchor
    if result.candidate_matches:
        if cache is not None:
            cache.set_child_anchor_id(cache_key, -1)
        return -1
    if cache is not None:
        cache.set_child_anchor_id(cache_key, 0)
    return 0


__all__ = [
    "IdentityResolutionCache",
    "ResolutionResult",
    "prefetch_child_match_cache",
    "prefetch_root_match_cache",
    "resolve_child_anchor",
    "resolve_existing_matches",
]
