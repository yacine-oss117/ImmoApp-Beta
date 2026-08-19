"""Conflict and preflight owners for importer review resolution."""

from __future__ import annotations

from typing import Any, TypedDict, cast
from uuid import UUID

from server.pg.uow import get_uow
from server.services.import_constants import ENTITY_TYPE_CLIENT, ENTITY_TYPE_LISTING
from server.services.import_price_dialect import build_field_price_metadata
from server.services.import_review_phone_conflicts import (
    ExistingPhoneMatch,
    existing_phone_matches,
    existing_summary,
)
from server.services.import_types import ReviewRowPayload


class PendingCreateRow(TypedDict):
    row_num: int
    entity_type: str
    validated_row: dict[str, object]
    correction_payload: dict[str, object]
    review_entry: ReviewRowPayload


class RowConflict(TypedDict, total=False):
    row: int
    entity_type: str
    conflict_type: str
    field: str
    existing_id: int | None
    existing_summary: str
    suggested_action: str
    match_count: int
    has_more_matches: bool
    candidate_summaries: list[dict[str, object]]


def _parse_job_uuid(job_id: str | None) -> UUID | None:
    if not job_id:
        return None
    try:
        return UUID(str(job_id))
    except (TypeError, ValueError, AttributeError):
        return None


def load_job_field_price_metadata(
    *,
    job_id: str | None,
    agency_id: int,
) -> dict[str, dict[str, object]]:
    parsed_job_id = _parse_job_uuid(job_id)
    if parsed_job_id is None:
        return {}
    with get_uow().session(actor=f"import_review_job_meta:{agency_id}") as session:
        row = session.execute(
            """
            SELECT agency_id, column_mapping, inference_summary
            FROM imports_importjob
            WHERE id = %s
            LIMIT 1
            """,
            (str(parsed_job_id),),
        ).fetchone()
    if not isinstance(row, dict):
        return {}
    raw_agency_id = row.get("agency_id", agency_id)
    resolved_agency_id = (
        int(raw_agency_id)
        if isinstance(raw_agency_id, (int, float, str)) and str(raw_agency_id).strip()
        else agency_id
    )
    raw_column_mapping = row.get("column_mapping", {})
    raw_inference_summary = row.get("inference_summary", {})
    return build_field_price_metadata(
        agency_id=resolved_agency_id,
        column_mapping=cast(
            dict[str, str],
            raw_column_mapping if isinstance(raw_column_mapping, dict) else {},
        ),
        inference_summary=cast(
            dict[str, Any],
            raw_inference_summary if isinstance(raw_inference_summary, dict) else {},
        ),
    )


def conflict_type_for_entity(entity_type: str) -> str:
    return "duplicate_listing_identity" if entity_type == ENTITY_TYPE_LISTING else "duplicate_phone"


def detect_create_conflicts(
    *,
    entity_type: str,
    agency_id: int,
    pending_rows: list[PendingCreateRow],
) -> list[RowConflict]:
    if entity_type not in {ENTITY_TYPE_CLIENT, ENTITY_TYPE_LISTING} or not pending_rows:
        return []
    row_conflicts: list[RowConflict] = []
    first_seen_by_phone: dict[str, int] = {}
    phones_to_query: set[str] = set()
    conflict_type = conflict_type_for_entity(entity_type)
    for pending in pending_rows:
        row_num = int(pending.get("row_num", 0) or 0)
        phone = str(dict(pending.get("validated_row", {}) or {}).get("phone", "") or "").strip()
        if not phone:
            continue
        if phone in first_seen_by_phone:
            row_conflicts.append(
                RowConflict(
                    row=row_num,
                    entity_type=entity_type,
                    conflict_type=conflict_type,
                    field="phone",
                    existing_id=None,
                    existing_summary=f"Line {first_seen_by_phone[phone]} already uses this phone number.",
                    suggested_action="review",
                )
            )
            continue
        first_seen_by_phone[phone] = row_num
        phones_to_query.add(phone)
    existing_matches = existing_phone_matches(
        entity_type=entity_type,
        agency_id=agency_id,
        phones=phones_to_query,
    )
    for pending in pending_rows:
        row_num = int(pending.get("row_num", 0) or 0)
        phone = str(dict(pending.get("validated_row", {}) or {}).get("phone", "") or "").strip()
        if first_seen_by_phone.get(phone) != row_num:
            continue
        existing_match = existing_matches.get(phone)
        if existing_match is None:
            continue
        row_conflicts.append(
            RowConflict(
                row=row_num,
                entity_type=entity_type,
                conflict_type=conflict_type,
                field="phone",
                existing_id=int(existing_match.get("id", 0) or 0) or None,
                existing_summary=existing_summary(entity_type, existing_match),
                suggested_action="use_existing_record",
                match_count=int(existing_match.get("match_count", 1) or 1),
                has_more_matches=bool(existing_match.get("has_more_matches", False)),
                candidate_summaries=list(existing_match.get("candidate_summaries", []) or []),
            )
        )
    return row_conflicts


def conflict_detail(row_conflicts: list[RowConflict]) -> str:
    conflict_types = {str(item.get("conflict_type", "") or "") for item in row_conflicts}
    if conflict_types == {"duplicate_listing_identity"}:
        return (
            "A few lines still need your attention. We found properties in your agency "
            "that already use the same phone number."
        )
    return (
        "A few lines still need your attention. We found records in your agency "
        "that already use the same phone number."
    )


__all__ = [
    "ExistingPhoneMatch",
    "PendingCreateRow",
    "RowConflict",
    "conflict_detail",
    "conflict_type_for_entity",
    "detect_create_conflicts",
    "load_job_field_price_metadata",
]
