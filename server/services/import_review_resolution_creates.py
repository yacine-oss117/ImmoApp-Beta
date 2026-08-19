"""Atomic create-batch owner for review-resolution submission."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from core.contracts.import_batch_refs import CreatedRowRef
from core.data.errors import ConflictError
from server.pg.uow import get_uow
from server.services.import_batch_write_refs import insert_batch_refs
from server.services.import_rebuild_handoff import schedule_review_corrections_after_commit
from server.services.import_review_conflicts import (
    RowConflict,
    conflict_detail,
    conflict_type_for_entity,
)
from server.services.import_review_created_rows import (
    InsertReviewCorrectionBatchesCallable,
    ReviewCorrectionCreateBatch,
    call_insert_review_correction_batches,
    require_created_rows_match_pending,
)
from server.services.import_review_resolution_errors import ImportReviewConflictError
from server.services.import_review_row_actions import AppliedReviewRow, ReviewResolutionState
from server.services.import_types import ImportLoadOutcome

InsertReviewCorrectionBatchesFn = InsertReviewCorrectionBatchesCallable
DetectCreateConflictsFn = Callable[..., list[RowConflict]]


def _coerce_int(value: object) -> int:
    return int(value) if isinstance(value, (int, float, str)) and str(value).strip() else 0


def _mapping_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _retry_create_conflicts(
    *,
    entity_type: str,
    agency_id: int,
    pending_rows: Sequence[Mapping[str, object]],
) -> list[RowConflict]:
    from server.services.import_constants import ENTITY_TYPE_CLIENT, ENTITY_TYPE_LISTING

    if entity_type not in {ENTITY_TYPE_CLIENT, ENTITY_TYPE_LISTING} or not pending_rows:
        return []
    phones = sorted(
        {
            str(_mapping_dict(row.get("validated_row", {})).get("phone", "") or "").strip()
            for row in pending_rows
            if str(_mapping_dict(row.get("validated_row", {})).get("phone", "") or "").strip()
        }
    )
    if not phones:
        return []
    table = "clients" if entity_type == ENTITY_TYPE_CLIENT else "listings"
    with get_uow().session(actor=f"import_review_retry_conflict:{agency_id}") as session:
        rows = session.execute(
            f"""
            SELECT id, family_name, phone
            FROM {table}
            WHERE agency_id = %s AND deleted_at IS NULL AND phone = ANY(%s)
            ORDER BY phone, id
            """,
            (agency_id, phones),
        ).fetchall()
    matches: dict[str, dict[str, object]] = {}
    candidate_summaries_by_phone: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        normalized_row = _mapping_dict(row)
        phone = str(normalized_row.get("phone", "") or "").strip()
        if not phone:
            continue
        candidate_summary = {
            "id": _coerce_int(normalized_row.get("id", 0)),
            "family_name": str(normalized_row.get("family_name", "") or ""),
            "phone": phone,
        }
        candidate_summaries = candidate_summaries_by_phone.setdefault(phone, [])
        candidate_summaries.append(candidate_summary)
        if phone not in matches:
            matches[phone] = {
                **normalized_row,
                "match_count": 1,
                "has_more_matches": False,
                "candidate_summaries": candidate_summaries,
            }
        else:
            matches[phone]["match_count"] = _coerce_int(matches[phone].get("match_count", 1)) + 1
            matches[phone]["has_more_matches"] = True
            matches[phone]["candidate_summaries"] = candidate_summaries
    conflict_type = conflict_type_for_entity(entity_type)
    conflicts: list[RowConflict] = []
    for pending_row in pending_rows:
        row_num = _coerce_int(pending_row.get("row_num", 0))
        phone = str(
            _mapping_dict(pending_row.get("validated_row", {})).get("phone", "") or ""
        ).strip()
        match = matches.get(phone)
        if match is None:
            continue
        family_name = str(match.get("family_name", "") or "").strip()
        label = "property" if entity_type == ENTITY_TYPE_LISTING else "record"
        existing_summary = (
            f"{family_name} ({phone}) [{label}]" if family_name and phone else family_name or phone
        )
        raw_candidate_summaries = match.get("candidate_summaries", [])
        conflicts.append(
            RowConflict(
                row=row_num,
                entity_type=entity_type,
                conflict_type=conflict_type,
                field="phone",
                existing_id=_coerce_int(match.get("id", 0)) or None,
                existing_summary=existing_summary,
                suggested_action="use_existing_record",
                match_count=max(1, _coerce_int(match.get("match_count", 1))),
                has_more_matches=bool(match.get("has_more_matches", False)),
                candidate_summaries=(
                    list(raw_candidate_summaries)
                    if isinstance(raw_candidate_summaries, list)
                    else []
                ),
            )
        )
    return conflicts


def _create_result_mismatch_error(
    *,
    create_entity_type: str,
    pending_rows: Sequence[Mapping[str, object]],
    exc: ValueError,
) -> ImportReviewConflictError:
    return ImportReviewConflictError(
        detail="A few created rows need your attention before we continue.",
        row_conflicts=[
            RowConflict(
                row=_coerce_int(row.get("row_num", 0)),
                entity_type=create_entity_type,
                conflict_type="create_result_mismatch",
                field="source_ordinal",
                existing_id=None,
                existing_summary="Created-row result did not match the submitted review rows.",
                suggested_action="review",
            )
            for row in pending_rows
        ],
    )


def apply_pending_creates(
    *,
    state: ReviewResolutionState,
    job_id: str,
    agency_id: int,
    insert_review_correction_batches_fn: InsertReviewCorrectionBatchesFn,
    detect_create_conflicts_fn: DetectCreateConflictsFn,
    user_id: int,
) -> tuple[int, dict[str, int]]:
    from server.services.import_constants import normalize_entity_type
    from server.services.import_review_shapes import build_review_audit_entry

    created_count = 0
    created_entity_counts: dict[str, int] = {}
    row_conflicts: list[RowConflict] = []
    for create_entity_type, pending_rows in state.create_pending_by_entity.items():
        row_conflicts.extend(
            detect_create_conflicts_fn(
                entity_type=create_entity_type,
                agency_id=agency_id,
                pending_rows=pending_rows,
            )
        )
    if row_conflicts:
        raise ImportReviewConflictError(
            detail=conflict_detail(row_conflicts),
            row_conflicts=row_conflicts,
        )

    create_batches = [
        ReviewCorrectionCreateBatch(
            entity_type=create_entity_type,
            corrected_rows=[dict(row.get("validated_row", {}) or {}) for row in pending_rows],
        )
        for create_entity_type, pending_rows in state.create_pending_by_entity.items()
        if pending_rows
    ]
    if not create_batches:
        return 0, {}
    try:
        created_rows_by_entity = call_insert_review_correction_batches(
            insert_review_correction_batches_fn=insert_review_correction_batches_fn,
            job_id=job_id,
            batches=create_batches,
            user_id=user_id,
            agency_id=agency_id,
        )
    except ConflictError as exc:
        for create_entity_type, pending_rows in state.create_pending_by_entity.items():
            row_conflicts.extend(
                _retry_create_conflicts(
                    entity_type=create_entity_type,
                    agency_id=agency_id,
                    pending_rows=pending_rows,
                )
            )
        if not row_conflicts:
            for create_entity_type, pending_rows in state.create_pending_by_entity.items():
                fallback_conflict_type = conflict_type_for_entity(create_entity_type)
                row_conflicts.extend(
                    RowConflict(
                        row=_coerce_int(row.get("row_num", 0)),
                        entity_type=create_entity_type,
                        conflict_type=fallback_conflict_type,
                        field="phone",
                        existing_id=None,
                        existing_summary="Existing record conflict detected.",
                        suggested_action="review",
                    )
                    for row in pending_rows
                )
        raise ImportReviewConflictError(
            detail=conflict_detail(row_conflicts),
            row_conflicts=row_conflicts,
        ) from exc
    except ValueError as exc:
        mismatch_conflicts: list[RowConflict] = []
        for create_entity_type, pending_rows in state.create_pending_by_entity.items():
            mismatch_conflicts.extend(
                _create_result_mismatch_error(
                    create_entity_type=create_entity_type,
                    pending_rows=pending_rows,
                    exc=exc,
                ).row_conflicts
            )
        raise ImportReviewConflictError(
            detail="A few created rows need your attention before we continue.",
            row_conflicts=mismatch_conflicts,
        ) from exc

    for create_entity_type, pending_rows in state.create_pending_by_entity.items():
        if not pending_rows:
            continue
        try:
            created_rows = require_created_rows_match_pending(
                entity_type=create_entity_type,
                pending_count=len(pending_rows),
                created_rows=created_rows_by_entity.get(create_entity_type, []),
            )
        except ValueError as exc:
            raise _create_result_mismatch_error(
                create_entity_type=create_entity_type,
                pending_rows=pending_rows,
                exc=exc,
            ) from exc
        created_for_entity = len(created_rows)
        created_count += created_for_entity
        normalized_create_entity_type = normalize_entity_type(create_entity_type)
        if normalized_create_entity_type:
            created_entity_counts[normalized_create_entity_type] = (
                created_entity_counts.get(normalized_create_entity_type, 0) + created_for_entity
            )
        state.decision_summary["create_new"] += created_for_entity
        for created_row in created_rows:
            pending_row = pending_rows[int(created_row.source_ordinal)]
            state.audit_entries.append(
                build_review_audit_entry(
                    row_num=int(pending_row.get("row_num", 0) or 0),
                    entity_type=str(pending_row.get("entity_type", "") or create_entity_type),
                    action="create",
                    validated_row=dict(pending_row.get("validated_row", {}) or {}),
                    review_entry=pending_row.get("review_entry", {}) or {},
                    correction_payload=dict(pending_row.get("correction_payload", {}) or {}),
                )
            )
            state.applied_rows.append(
                AppliedReviewRow(
                    row_num=int(pending_row.get("row_num", 0) or 0),
                    action="create",
                    entity_type=str(pending_row.get("entity_type", "") or create_entity_type),
                    validated_row=dict(pending_row.get("validated_row", {}) or {}),
                    correction_payload=dict(pending_row.get("correction_payload", {}) or {}),
                    review_entry=pending_row.get("review_entry", {}) or {},
                )
            )
    return created_count, created_entity_counts


def insert_review_corrections_impl(
    *,
    job_id: str,
    entity_type: str,
    corrected_rows: list[dict[str, object]],
    user_id: int,
    agency_id: int,
) -> list[CreatedRowRef]:
    results = insert_review_correction_batches_impl(
        job_id=job_id,
        batches=[
            ReviewCorrectionCreateBatch(
                entity_type=entity_type,
                corrected_rows=list(corrected_rows),
            )
        ],
        user_id=user_id,
        agency_id=agency_id,
    )
    return results.get(entity_type, [])


def insert_review_correction_batches_impl(
    *,
    job_id: str,
    batches: Sequence[ReviewCorrectionCreateBatch],
    user_id: int,
    agency_id: int,
) -> dict[str, list[CreatedRowRef]]:
    from server.services.import_constants import normalize_entity_type

    if not batches:
        return {}

    created_by_entity: dict[str, list[CreatedRowRef]] = {}
    with get_uow().transaction(actor=f"import_review:{user_id}") as write_session:
        for batch in batches:
            if not batch.corrected_rows:
                created_by_entity[str(batch.entity_type)] = []
                continue
            resolved_entity_type = normalize_entity_type(batch.entity_type)
            load_outcome = ImportLoadOutcome()
            created_rows = insert_batch_refs(
                write_session=write_session,
                entity_type=resolved_entity_type,
                batch_rows=list(batch.corrected_rows),
                demande_ids=load_outcome.demande_ids,
                demande_client_ids=load_outcome.demande_client_ids,
                offer_ids=load_outcome.offer_ids,
                listing_wilaya_ids=load_outcome.listing_wilaya_ids,
            )
            created_rows = require_created_rows_match_pending(
                entity_type=str(batch.entity_type),
                pending_count=len(batch.corrected_rows),
                created_rows=created_rows,
            )
            created_by_entity[str(batch.entity_type)] = created_rows
            schedule_review_corrections_after_commit(
                write_session=write_session,
                entity_type=resolved_entity_type,
                job_id=str(job_id or ""),
                agency_id=agency_id,
                load_outcome=load_outcome,
            )
    return created_by_entity


__all__ = [
    "apply_pending_creates",
    "insert_review_correction_batches_impl",
    "insert_review_corrections_impl",
]
