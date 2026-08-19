"""Execution orchestrator for importer review resolution."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping

from core.importer.security import import_security_limits
from server.services.import_review_conflicts import RowConflict
from server.services.import_review_created_rows import InsertReviewCorrectionBatchesCallable
from server.services.import_review_resolution_creates import apply_pending_creates
from server.services.import_review_resolution_errors import ImportReviewConflictError
from server.services.import_review_row_actions import (
    AppliedReviewRow,
    ReviewResolutionState,
    collect_review_actions,
    normalize_resolution_inputs,
)
from server.services.import_types import ReviewRowPayload

logger = logging.getLogger(__name__)

InsertReviewCorrectionBatchesFn = InsertReviewCorrectionBatchesCallable
DetectCreateConflictsFn = Callable[..., list[RowConflict]]


def _apply_pending_updates(*, state: ReviewResolutionState, user_id: int) -> int:
    """Apply update-existing decisions one row at a time under each entity service's OCC contract.

    These updates intentionally stay per-row because each decision carries its own row_version,
    routes through a different entity service, and preserves fail-fast first-conflict semantics
    so later rows are not applied against a diverged review decision set.
    """
    from core.data.errors import ConflictError
    from server.services import clients as clients_service
    from server.services import demandes as demandes_service
    from server.services import listings as listings_service
    from server.services import offers as offers_service
    from server.services.import_constants import (
        ENTITY_TYPE_CLIENT,
        ENTITY_TYPE_DEMANDE,
        ENTITY_TYPE_LISTING,
        ENTITY_TYPE_OFFER,
    )
    from server.services.import_review_shapes import build_review_audit_entry

    def _update_client(
        *, validated_row: dict[str, object], existing_id: int, row_version: int, actor: str
    ) -> None:
        clients_service.upsert_client(
            {**validated_row, "id": existing_id, "row_version": row_version},
            actor=actor,
        )

    def _update_listing(
        *, validated_row: dict[str, object], existing_id: int, row_version: int, actor: str
    ) -> None:
        listings_service.upsert_listing(
            {**validated_row, "id": existing_id, "row_version": row_version},
            actor=actor,
        )

    def _update_demande(
        *, validated_row: dict[str, object], existing_id: int, row_version: int, actor: str
    ) -> None:
        demandes_service.update_demande(
            existing_id,
            {**validated_row, "row_version": row_version},
            actor=actor,
        )

    def _update_offer(
        *, validated_row: dict[str, object], existing_id: int, row_version: int, actor: str
    ) -> None:
        offers_service.update_offer(
            existing_id,
            {**validated_row, "row_version": row_version},
            actor=actor,
        )

    update_dispatchers = {
        ENTITY_TYPE_CLIENT: _update_client,
        ENTITY_TYPE_LISTING: _update_listing,
        ENTITY_TYPE_DEMANDE: _update_demande,
        ENTITY_TYPE_OFFER: _update_offer,
    }
    actor = f"import_review:{user_id}"
    updated_count = 0
    started = time.perf_counter()
    max_pending_updates = max(1, int(import_security_limits().max_review_rows or 1))
    if len(state.pending_updates) > max_pending_updates:
        raise ValueError(
            f"Review update batch contains {len(state.pending_updates)} rows, exceeding "
            f"the bounded OCC update limit of {max_pending_updates}."
        )
    for pending_update in state.pending_updates:
        update_entity_type = str(pending_update.get("entity_type", "") or "")
        validated_row = dict(pending_update.get("validated_row", {}) or {})
        existing_id = int(pending_update.get("existing_id", 0) or 0)
        row_version = int(pending_update.get("row_version", 0) or 0)
        dispatcher = update_dispatchers.get(update_entity_type)
        if dispatcher is None:
            raise ValueError(f"Unsupported entity type for update: {update_entity_type}")
        try:
            dispatcher(
                validated_row=validated_row,
                existing_id=existing_id,
                row_version=row_version,
                actor=actor,
            )
        except ConflictError as exc:
            conflict_type = "row_version_conflict" if exc.current_version is not None else "other"
            raise ImportReviewConflictError(
                detail="A few lines still need your attention before we continue.",
                row_conflicts=[
                    RowConflict(
                        row=int(pending_update.get("row_num", 0) or 0),
                        entity_type=update_entity_type,
                        conflict_type=conflict_type,
                        field=("row_version" if conflict_type == "row_version_conflict" else ""),
                        existing_id=existing_id or None,
                        existing_summary=str(exc.current_record or exc),
                        suggested_action="review",
                    )
                ],
            ) from exc
        state.audit_entries.append(
            build_review_audit_entry(
                row_num=int(pending_update.get("row_num", 0) or 0),
                entity_type=update_entity_type,
                action="update",
                validated_row=validated_row,
                review_entry=pending_update.get("review_entry", {}) or {},
                existing_id=existing_id,
                row_version=row_version,
                before_payload=dict(pending_update.get("before_payload", {}) or {}),
                diff_payload=dict(pending_update.get("diff_payload", {}) or {}),
                correction_payload=dict(pending_update.get("correction_payload", {}) or {}),
            )
        )
        updated_count += 1
        state.decision_summary["update_existing"] += 1
        state.applied_rows.append(
            AppliedReviewRow(
                row_num=int(pending_update.get("row_num", 0) or 0),
                action="update",
                entity_type=update_entity_type,
                validated_row=validated_row,
                correction_payload=dict(pending_update.get("correction_payload", {}) or {}),
                review_entry=pending_update.get("review_entry", {}) or {},
            )
        )
    if state.pending_updates:
        logger.debug(
            "Applied %s review OCC updates in %.3f seconds for review job actor=%s",
            updated_count,
            time.perf_counter() - started,
            user_id,
        )
    return updated_count


def _bundle_shape_hint(applied_rows: list[AppliedReviewRow]) -> str:
    return (
        "same_side_bundle"
        if any(
            str((row.get("review_entry") or {}).get("topology_side", "") or "")
            in {"client_side", "listing_side"}
            for row in applied_rows
        )
        else ""
    )


def apply_review_resolutions_impl(
    *,
    job_id: str = "",
    entity_type: str,
    review_rows: list[ReviewRowPayload],
    corrections: Mapping[str, Mapping[str, object]] | None,
    decisions: Mapping[str, Mapping[str, object]] | None,
    skip_rows: list[int | str] | None,
    user_id: int,
    agency_id: int,
    normalization_pipeline_cls: Callable[..., object],
    validate_row_fn: Callable[[dict[str, object], str], tuple[dict[str, object], list[str]]],
    insert_review_correction_batches_fn: InsertReviewCorrectionBatchesFn,
    detect_create_conflicts_fn: DetectCreateConflictsFn,
    record_learning_signals_fn: Callable[..., object],
    record_dead_letter_rows_fn: Callable[..., object],
    refresh_agency_profile_fn: Callable[..., object],
) -> dict[str, object]:
    inputs = normalize_resolution_inputs(
        corrections=corrections,
        decisions=decisions,
        skip_rows=skip_rows,
        review_rows=review_rows,
        job_id=job_id,
        agency_id=agency_id,
    )
    state = collect_review_actions(
        job_id=job_id,
        agency_id=agency_id,
        user_id=user_id,
        entity_type=entity_type,
        review_rows=review_rows,
        inputs=inputs,
        normalization_pipeline_cls=normalization_pipeline_cls,
        validate_row_fn=validate_row_fn,
    )
    created_count, created_entity_counts = apply_pending_creates(
        state=state,
        job_id=job_id,
        agency_id=agency_id,
        insert_review_correction_batches_fn=insert_review_correction_batches_fn,
        detect_create_conflicts_fn=detect_create_conflicts_fn,
        user_id=user_id,
    )
    updated_count = _apply_pending_updates(state=state, user_id=user_id)

    learning_summary = record_learning_signals_fn(
        agency_id=agency_id,
        job_id=job_id,
        actor_id=user_id,
        applied_rows=state.applied_rows,
    )
    dead_letter_summary = record_dead_letter_rows_fn(state.dead_letter_rows)
    refresh_agency_profile_fn(
        agency_id=agency_id,
        bundle_shape_hint=_bundle_shape_hint(state.applied_rows),
    )
    return {
        "created_count": created_count,
        "created_entity_counts": created_entity_counts,
        "updated_count": updated_count,
        "still_review": state.still_review,
        "errors": state.errors_list,
        "audit_entries": state.audit_entries,
        "decision_summary": state.decision_summary,
        "learning_summary": learning_summary,
        "dead_letter_summary": dead_letter_summary,
    }


__all__ = [
    "ImportReviewConflictError",
    "apply_review_resolutions_impl",
]
