"""Transactional load phase for importer execution."""

from __future__ import annotations

import math
import time
from typing import Any, cast

from core.utils.memory_guard import adaptive_chunk_size
from server.imports.models import ImportJob
from server.pg.uow import get_uow
from server.services.import_constants import ENTITY_TYPE_DEMANDE
from server.services.import_execution_governor import profile_aware_chunk_ceiling
from server.services.import_executor_helpers import insert_batch
from server.services.import_load_accounting import (
    apply_load_count_delta,
    child_anchor_failure_delta,
)
from server.services.import_load_conflict_isolation import (
    _flush_bundle_root_entries_with_conflict_isolation,
)
from server.services.import_load_policy import (
    build_child_anchor_failure_rows,
    classify_child_anchor,
    evaluate_orphan_threshold,
)
from server.services.import_load_shared import (
    ImportLoadProgressSnapshot,
    PlannedInsertEntry,
    finalize_successful_load,
    flush_insert_entries,
    persist_load_progress_snapshot,
)
from server.services.import_progress_runtime import persist_job_progress
from server.services.import_rebuild_handoff import (
    schedule_bundle_after_commit,
    schedule_single_entity_after_commit,
)
from server.services.import_review_runtime import review_overflow_count
from server.services.import_runtime_artifacts import (
    entry_dict,
    entry_int,
    entry_row_num,
    entry_str,
    iter_jsonl_entries,
    iter_jsonl_entry_batches,
    require_path,
)
from server.services.import_types import (
    ImportLoadOutcome,
    ImportResult,
    PreparedImportArtifact,
    ReviewRows,
)


class ImportLoadConsistencyError(ValueError):
    """Raised when planned bundle rows cannot be loaded safely as planned."""

    def __init__(
        self,
        message: str,
        *,
        row_errors: list[dict[str, object]] | None = None,
    ) -> None:
        super().__init__(message)
        self.row_errors = [dict(row) for row in list(row_errors or [])]


def load_child_only_import(
    *,
    job: ImportJob,
    user_id: int,
    entity_type: str,
    review_rows: ReviewRows,
    result: ImportResult,
    artifact: PreparedImportArtifact,
) -> ImportLoadOutcome:
    load_outcome = ImportLoadOutcome()
    planned_entries_path = require_path(
        artifact.planned_entries_path,
        field_name="planned_entries_path",
    )
    agency_id = int(cast(Any, job).agency_id)
    review_overflow_total = review_overflow_count(review_rows)
    with get_uow().transaction(actor=f"import:{user_id}") as write_session:
        imported_ids: list[int] = []
        current_chunk = 0
        for entry_batch in iter_jsonl_entry_batches(
            planned_entries_path,
            artifact.current_batch_size,
        ):
            current_chunk += 1
            _batch_ids, db_duration = flush_insert_entries(
                write_session=write_session,
                entity_type=entity_type,
                batch_entries=cast(list[PlannedInsertEntry], entry_batch),
                imported_ids=imported_ids,
                load_outcome=load_outcome,
                insert_batch_fn=insert_batch,
            )
            load_outcome.total_db_time += db_duration
            persist_load_progress_snapshot(
                write_session=write_session,
                job=job,
                snapshot=ImportLoadProgressSnapshot(
                    rows_total=artifact.total_rows,
                    rows_processed=min(
                        artifact.total_rows, current_chunk * artifact.current_batch_size
                    ),
                    rows_created=len(imported_ids),
                    rows_updated=0,
                    rows_skipped=result.skipped_count,
                    rows_review=len(review_rows),
                    current_chunk=current_chunk,
                    chunks_total=max(1, artifact.chunks_total),
                    phase="executing",
                    bundle_mode=artifact.bundle_mode,
                    review_overflow_count_value=review_overflow_total,
                ),
                persist_job_progress_fn=persist_job_progress,
            )
        persist_load_progress_snapshot(
            write_session=write_session,
            job=job,
            snapshot=ImportLoadProgressSnapshot(
                rows_total=artifact.total_rows,
                rows_processed=artifact.total_rows,
                rows_created=len(imported_ids),
                rows_updated=0,
                rows_skipped=result.skipped_count,
                rows_review=len(review_rows),
                current_chunk=current_chunk,
                chunks_total=max(1, artifact.chunks_total),
                phase="rebuild",
                bundle_mode=artifact.bundle_mode,
                review_overflow_count_value=review_overflow_total,
            ),
            persist_job_progress_fn=persist_job_progress,
        )
        finalize_successful_load(
            result=result,
            load_outcome=load_outcome,
            imported_ids=imported_ids,
            created_entity_counts={str(entity_type): len(imported_ids)},
            committed_entities={str(entity_type)},
            schedule_after_commit=lambda: schedule_single_entity_after_commit(
                write_session=write_session,
                entity_type=entity_type,
                job_id=str(job.id),
                agency_id=agency_id,
                load_outcome=load_outcome,
            ),
        )
    return load_outcome


def load_same_side_bundle_import(
    *,
    job: ImportJob,
    user_id: int,
    review_rows: ReviewRows,
    errors: list[dict[str, object]],
    result: ImportResult,
    artifact: PreparedImportArtifact,
) -> ImportLoadOutcome:
    load_outcome = ImportLoadOutcome()
    planned_root_entries_path = require_path(
        artifact.planned_root_entries_path,
        field_name="planned_root_entries_path",
    )
    planned_child_entries_path = require_path(
        artifact.planned_child_entries_path,
        field_name="planned_child_entries_path",
    )
    agency_id = int(cast(Any, job).agency_id)
    child_parent_field = (
        "client_id" if artifact.child_entity == ENTITY_TYPE_DEMANDE else "listing_id"
    )
    review_overflow_total = review_overflow_count(review_rows)
    with get_uow().transaction(actor=f"import:{user_id}") as write_session:
        imported_ids: list[int] = []
        created_anchor_map: dict[str, int] = {}
        root_created_count = 0
        child_created_count = 0
        root_processed_count = 0
        current_chunk = 0
        root_load_errors: list[dict[str, object]] = []
        child_anchor_errors: list[dict[str, object]] = []
        for entry_batch in iter_jsonl_entry_batches(
            planned_root_entries_path,
            artifact.current_batch_size,
        ):
            current_chunk += 1
            batch_ids, db_duration = _flush_bundle_root_entries_with_conflict_isolation(
                write_session=write_session,
                entity_type=artifact.root_entity,
                batch_entries=cast(list[dict[str, object]], entry_batch),
                imported_ids=imported_ids,
                load_outcome=load_outcome,
                created_anchor_map=created_anchor_map,
                load_errors=root_load_errors,
            )
            load_outcome.total_db_time += db_duration
            root_processed_count += len(entry_batch)
            root_created_count += len(batch_ids)
            persist_load_progress_snapshot(
                write_session=write_session,
                job=job,
                snapshot=ImportLoadProgressSnapshot(
                    rows_total=artifact.total_rows,
                    rows_processed=min(artifact.total_rows, root_processed_count),
                    rows_created=len(imported_ids),
                    rows_updated=0,
                    rows_skipped=result.skipped_count,
                    rows_review=len(review_rows),
                    current_chunk=current_chunk,
                    chunks_total=max(1, artifact.chunks_total),
                    phase="root_load",
                    bundle_mode=artifact.bundle_mode,
                    progress=min(
                        88, 75 + int((current_chunk / max(1, artifact.chunks_total)) * 13)
                    ),
                    review_overflow_count_value=review_overflow_total,
                ),
                persist_job_progress_fn=persist_job_progress,
            )
        child_processed_count = 0
        for entry_batch in iter_jsonl_entry_batches(
            planned_child_entries_path,
            artifact.current_batch_size,
        ):
            current_chunk += 1
            batch_entries: list[PlannedInsertEntry] = []
            for entry in entry_batch:
                row_num = entry_row_num(entry)
                row_data = cast(dict[str, object], entry_dict(entry, "data"))
                original_anchor_id = entry_int(entry, "anchor_id")
                anchor_id = original_anchor_id
                if anchor_id <= 0:
                    anchor_key = entry_str(entry, "anchor_key")
                    anchor_id = int(created_anchor_map.get(anchor_key, 0) or 0)
                anchor_classification = classify_child_anchor(
                    original_anchor_id=original_anchor_id,
                    resolved_anchor_id=anchor_id,
                )
                if not anchor_classification.is_resolved:
                    failure_rows = build_child_anchor_failure_rows(
                        row_num=row_num,
                        row_data=row_data,
                        anchor_classification=anchor_classification,
                    )
                    errors.append(failure_rows.user_row_error)
                    apply_load_count_delta(result, delta=child_anchor_failure_delta())
                    child_anchor_errors.append(
                        cast(dict[str, object], failure_rows.internal_row_error)
                    )
                    continue
                row_data[child_parent_field] = anchor_classification.resolved_anchor_id
                batch_entries.append(
                    PlannedInsertEntry(
                        row=row_num,
                        data=row_data,
                        original=cast(dict[str, object], entry_dict(entry, "original")),
                    )
                )

            if batch_entries:
                batch_ids, db_duration = flush_insert_entries(
                    write_session=write_session,
                    entity_type=artifact.child_entity,
                    batch_entries=batch_entries,
                    imported_ids=imported_ids,
                    load_outcome=load_outcome,
                    insert_batch_fn=insert_batch,
                )
                load_outcome.total_db_time += db_duration
                child_created_count += len(batch_ids)

            child_processed_count += len(entry_batch)
            persist_load_progress_snapshot(
                write_session=write_session,
                job=job,
                snapshot=ImportLoadProgressSnapshot(
                    rows_total=artifact.total_rows,
                    rows_processed=artifact.root_row_count + child_processed_count,
                    rows_created=len(imported_ids),
                    rows_updated=0,
                    rows_skipped=result.skipped_count,
                    rows_review=len(review_rows),
                    current_chunk=current_chunk,
                    chunks_total=max(1, artifact.chunks_total),
                    phase="child_load",
                    bundle_mode=artifact.bundle_mode,
                    progress=min(
                        97, 88 + int((child_processed_count / max(1, artifact.child_row_count)) * 9)
                    ),
                    review_overflow_count_value=review_overflow_total,
                ),
                persist_job_progress_fn=persist_job_progress,
            )

        if root_load_errors:
            raise ImportLoadConsistencyError(
                "A few planned lines changed while the import was loading. Restart the import so those rows can be planned again.",
                row_errors=root_load_errors + child_anchor_errors,
            )
        if child_anchor_errors:
            orphan_decision = evaluate_orphan_threshold(
                orphan_count=len(child_anchor_errors),
                total_count=int(artifact.child_row_count or 0),
            )
            if orphan_decision.hard_fail:
                raise ImportLoadConsistencyError(
                    "A significant number of planned lines lost their parent anchor during load. Restart the import so those rows can be planned again.",
                    row_errors=child_anchor_errors,
                )
        persist_load_progress_snapshot(
            write_session=write_session,
            job=job,
            snapshot=ImportLoadProgressSnapshot(
                rows_total=artifact.total_rows,
                rows_processed=artifact.total_rows,
                rows_created=len(imported_ids),
                rows_updated=0,
                rows_skipped=result.skipped_count,
                rows_review=len(review_rows),
                current_chunk=current_chunk,
                chunks_total=max(1, artifact.chunks_total),
                phase="rebuild",
                bundle_mode=artifact.bundle_mode,
                progress=99,
                review_overflow_count_value=review_overflow_total,
            ),
            persist_job_progress_fn=persist_job_progress,
        )
        finalize_successful_load(
            result=result,
            load_outcome=load_outcome,
            imported_ids=imported_ids,
            created_entity_counts={
                str(artifact.root_entity): root_created_count,
                str(artifact.child_entity): child_created_count,
            },
            committed_entities={
                entity_type
                for entity_type, created_count in (
                    (str(artifact.root_entity), root_created_count),
                    (str(artifact.child_entity), child_created_count),
                )
                if created_count > 0
            },
            schedule_after_commit=lambda: schedule_bundle_after_commit(
                write_session=write_session,
                job_id=str(job.id),
                agency_id=agency_id,
                load_outcome=load_outcome,
            ),
        )
    return load_outcome


def load_single_entity_import(
    *,
    job: ImportJob,
    user_id: int,
    entity_type: str,
    review_rows: ReviewRows,
    result: ImportResult,
    artifact: PreparedImportArtifact,
) -> ImportLoadOutcome:
    from server.api.notifications import notify_only

    load_outcome = ImportLoadOutcome()
    planned_entries_path = require_path(
        artifact.planned_entries_path,
        field_name="planned_entries_path",
    )
    agency_id = int(cast(Any, job).agency_id)
    min_batch = 50
    max_batch = 3000
    current_batch_size = artifact.current_batch_size
    last_progress_update = 0.0
    last_progress_row = 0
    progress_step = 100
    progress_interval = 1.0
    review_overflow_total = review_overflow_count(review_rows)
    with get_uow().transaction(actor=f"import:{user_id}") as write_session:
        imported_ids: list[int] = []
        batch_buffer: list[PlannedInsertEntry] = []
        processed_count = 0
        for entry in iter_jsonl_entries(planned_entries_path):
            row_num = entry_row_num(entry)
            processed_count += 1
            batch_buffer.append(
                PlannedInsertEntry(
                    row=row_num,
                    data=cast(dict[str, object], entry_dict(entry, "data")),
                    original=cast(dict[str, object], entry_dict(entry, "original")),
                )
            )

            if len(batch_buffer) >= current_batch_size:
                _batch_ids, db_duration = flush_insert_entries(
                    write_session=write_session,
                    entity_type=entity_type,
                    batch_entries=batch_buffer,
                    imported_ids=imported_ids,
                    load_outcome=load_outcome,
                    insert_batch_fn=insert_batch,
                )
                load_outcome.total_db_time += db_duration
                adaptive_target = adaptive_chunk_size(
                    floor=min_batch,
                    ceiling=profile_aware_chunk_ceiling(max_batch),
                )
                if db_duration > 1.0:
                    current_batch_size = max(
                        min_batch, min(adaptive_target, current_batch_size // 2)
                    )
                elif db_duration < 0.2:
                    current_batch_size = adaptive_target
                else:
                    current_batch_size = max(min_batch, min(adaptive_target, current_batch_size))
                batch_buffer = []
            current_count = processed_count
            now = time.monotonic()
            should_update_progress = (
                artifact.total_rows > 0 and current_count == artifact.total_rows
            )
            if (current_count - last_progress_row) >= progress_step:
                should_update_progress = True
            if (now - last_progress_update) >= progress_interval:
                should_update_progress = True
            if should_update_progress:
                progress = (
                    100
                    if artifact.total_rows <= 0
                    else min(99, int((current_count / artifact.total_rows) * 100))
                )
                persist_load_progress_snapshot(
                    write_session=write_session,
                    job=job,
                    snapshot=ImportLoadProgressSnapshot(
                        rows_total=artifact.total_rows,
                        rows_processed=current_count,
                        rows_created=len(imported_ids),
                        rows_updated=result.updated_count,
                        rows_skipped=result.skipped_count,
                        rows_review=len(review_rows),
                        current_chunk=max(0, math.ceil(current_count / max(1, current_batch_size))),
                        chunks_total=(
                            max(1, math.ceil(artifact.total_rows / max(1, current_batch_size)))
                            if artifact.total_rows
                            else 0
                        ),
                        phase="executing",
                        bundle_mode="single_entity",
                        progress=progress,
                        review_overflow_count_value=review_overflow_total,
                    ),
                    persist_job_progress_fn=persist_job_progress,
                )
                last_progress_update = now
                last_progress_row = current_count
                notify_only(
                    scope="user",
                    user_id=user_id,
                    event_type="import_progress",
                    title="Importing (processing)",
                    body=(
                        f"Processing {current_count} of {artifact.total_rows or 'unknown'} rows "
                        "(planned and loading)..."
                    ),
                    data={
                        "session_id": str(job.id),
                        "progress": progress,
                        "current": current_count,
                        "total": artifact.total_rows,
                    },
                )
        if batch_buffer:
            _batch_ids, db_duration = flush_insert_entries(
                write_session=write_session,
                entity_type=entity_type,
                batch_entries=batch_buffer,
                imported_ids=imported_ids,
                load_outcome=load_outcome,
                insert_batch_fn=insert_batch,
            )
            load_outcome.total_db_time += db_duration
            persist_load_progress_snapshot(
                write_session=write_session,
                job=job,
                snapshot=ImportLoadProgressSnapshot(
                    rows_total=artifact.total_rows,
                    rows_processed=artifact.total_rows,
                    rows_created=len(imported_ids),
                    rows_updated=result.updated_count,
                    rows_skipped=result.skipped_count,
                    rows_review=len(review_rows),
                    current_chunk=max(
                        0, math.ceil(artifact.total_rows / max(1, current_batch_size))
                    ),
                    chunks_total=(
                        max(1, math.ceil(artifact.total_rows / max(1, current_batch_size)))
                        if artifact.total_rows
                        else 0
                    ),
                    phase="rebuild",
                    bundle_mode="single_entity",
                    progress=99,
                    review_overflow_count_value=review_overflow_total,
                ),
                persist_job_progress_fn=persist_job_progress,
            )
        finalize_successful_load(
            result=result,
            load_outcome=load_outcome,
            imported_ids=imported_ids,
            created_entity_counts={str(entity_type): len(imported_ids)},
            committed_entities={str(entity_type)},
            schedule_after_commit=lambda: schedule_single_entity_after_commit(
                write_session=write_session,
                entity_type=entity_type,
                job_id=str(job.id),
                agency_id=agency_id,
                load_outcome=load_outcome,
            ),
        )
    return load_outcome


__all__ = [
    "ImportLoadConsistencyError",
    "load_child_only_import",
    "load_same_side_bundle_import",
    "load_single_entity_import",
]
