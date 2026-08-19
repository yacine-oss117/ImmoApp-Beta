"""Phone-match lookup helpers for import review create-conflict detection."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypedDict

from server.pg.uow import get_uow
from server.services.import_constants import ENTITY_TYPE_CLIENT, ENTITY_TYPE_LISTING


class ExistingPhoneMatch(TypedDict, total=False):
    id: int
    family_name: str
    phone: str
    match_count: int
    has_more_matches: bool
    candidate_summaries: list[dict[str, object]]


def _coerce_id(value: object) -> int:
    return int(value) if isinstance(value, (int, float, str)) and str(value).strip() else 0


def existing_summary(entity_type: str, row: ExistingPhoneMatch | None) -> str:
    if not row:
        return ""
    name = str(row.get("family_name", "") or "").strip()
    phone = str(row.get("phone", "") or "").strip()
    if name and phone:
        label = "property" if entity_type == ENTITY_TYPE_LISTING else "record"
        return f"{name} ({phone}) [{label}]"
    return name or phone


def existing_phone_matches(
    *,
    entity_type: str,
    agency_id: int,
    phones: Iterable[str],
) -> dict[str, ExistingPhoneMatch]:
    if entity_type not in {ENTITY_TYPE_CLIENT, ENTITY_TYPE_LISTING}:
        return {}
    unique_phones = sorted(
        {str(phone or "").strip() for phone in phones if str(phone or "").strip()}
    )
    if not unique_phones:
        return {}
    table = "clients" if entity_type == ENTITY_TYPE_CLIENT else "listings"
    with get_uow().session(actor=f"import_review_preflight:{agency_id}") as session:
        rows = session.execute(
            f"""
            SELECT id, family_name, phone
            FROM {table}
            WHERE agency_id = %s AND deleted_at IS NULL AND phone = ANY(%s)
            ORDER BY phone, id
            """,
            (agency_id, unique_phones),
        ).fetchall()
    matches: dict[str, ExistingPhoneMatch] = {}
    candidate_summaries_by_phone: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        phone = str(row.get("phone", "") or "").strip()
        if not phone:
            continue
        candidate_summary = {
            "id": _coerce_id(row.get("id", 0)),
            "family_name": str(row.get("family_name", "") or ""),
            "phone": phone,
        }
        candidate_summaries = candidate_summaries_by_phone.setdefault(phone, [])
        candidate_summaries.append(candidate_summary)
        if phone in matches:
            match = matches[phone]
            match["match_count"] = int(match.get("match_count", 1) or 1) + 1
            match["has_more_matches"] = True
            match["candidate_summaries"] = candidate_summaries
            continue
        matches[phone] = ExistingPhoneMatch(
            id=_coerce_id(row.get("id", 0)),
            family_name=str(row.get("family_name", "") or ""),
            phone=phone,
            match_count=1,
            has_more_matches=False,
            candidate_summaries=candidate_summaries,
        )
    return matches


__all__ = ["ExistingPhoneMatch", "existing_phone_matches", "existing_summary"]
