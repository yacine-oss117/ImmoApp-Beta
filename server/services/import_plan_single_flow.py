"""Single-entity planning flow."""

from __future__ import annotations

from typing import Any, cast

from server.imports.models import ImportJob
from server.pg.uow import get_uow
from server.services.duplicate_checker import DatabaseDuplicateChecker
from server.services.import_constants import (
    DUPLICATE_STRATEGY_ALLOW_ALL,
    DUPLICATE_STRATEGY_REVIEW,
    ENTITY_TYPE_CLIENT,
    ENTITY_TYPE_LISTING,
)
from server.services.import_executor_helpers import append_db_duplicate_reviews
from server.services.import_progress_runtime import persist_job_progress
from server.services.import_review_runtime import review_overflow_count
from server.services.import_runtime_artifacts import (
    entry_row_num,
    iter_jsonl_entry_batches,
    require_path,
    write_jsonl_entry,
)
from server.services.import_types import ImportResult, PreparedImportArtifact, ReviewRows


def plan_single_entity_import(
    *,
    job: ImportJob,
    entity_type: str,
    duplicate_strategy: str,
    skip_review_rows: bool,
    review_rows: ReviewRows,
    errors: list[dict[str, object]],
    result: ImportResult,
    artifact: PreparedImportArtifact,
) -> PreparedImportArtifact:
    spool_dir = require_path(artifact.spool_dir, field_name="spool_dir")
    planned_entries_path = spool_dir / "planned_root_entries.jsonl"
    prepared_entries_path = require_path(
        artifact.prepared_entries_path,
        field_name="prepared_entries_path",
    )
    agency_id = int(cast(Any, job).agency_id)
    db_checker = (
        DatabaseDuplicateChecker()
        if entity_type in {ENTITY_TYPE_CLIENT, ENTITY_TYPE_LISTING}
        and duplicate_strategy != DUPLICATE_STRATEGY_ALLOW_ALL
        else None
    )
    planned_count = 0
    current_chunk = 0

    with (
        planned_entries_path.open("w", encoding="utf-8") as planned_handle,
        get_uow().session(actor=f"import-plan:{job.id}") as read_session,
    ):
        for entry_batch in iter_jsonl_entry_batches(
            prepared_entries_path, artifact.current_batch_size
        ):
            filtered_batch = list(entry_batch)
            if db_checker is not None:
                duplicate_result = db_checker.check_phones(
                    filtered_batch,
                    entity_type,
                    read_session,
                    agency_id=agency_id,
                )
                if duplicate_result.has_duplicates:
                    if duplicate_strategy == DUPLICATE_STRATEGY_REVIEW and not skip_review_rows:
                        result.skipped_count += len(duplicate_result.matches)
                        append_db_duplicate_reviews(
                            entity_type=entity_type,
                            review_rows=review_rows,
                            db_matches=duplicate_result.matches,
                            rows_by_index={entry_row_num(entry): entry for entry in filtered_batch},
                        )
                    elif duplicate_strategy == DUPLICATE_STRATEGY_REVIEW:
                        result.error_count += len(duplicate_result.matches)
                        errors.extend(
                            {
                                "row": int(match.row_index or 0),
                                "errors": [
                                    "This line matches existing records in your agency and needs review."
                                ],
                            }
                            for match in duplicate_result.matches
                        )
                    else:
                        result.skipped_count += len(duplicate_result.matches)
                    filtered_batch = [
                        entry
                        for entry in filtered_batch
                        if entry_row_num(entry) in duplicate_result.clean_indices
                    ]

            for entry in filtered_batch:
                write_jsonl_entry(planned_handle, entry)
                planned_count += 1

            current_chunk += 1
            persist_job_progress(
                write_session=None,
                job=job,
                rows_total=artifact.total_rows,
                rows_processed=min(
                    artifact.total_rows, current_chunk * artifact.current_batch_size
                ),
                rows_created=0,
                rows_updated=0,
                rows_skipped=result.skipped_count,
                rows_review=len(review_rows),
                current_chunk=current_chunk,
                chunks_total=artifact.chunks_total,
                phase="planning",
                bundle_mode=artifact.bundle_mode,
                progress=min(70, 35 + int((current_chunk / max(1, artifact.chunks_total)) * 35)),
                review_overflow_count_value=review_overflow_count(review_rows),
            )

    artifact.planned_entries_path = planned_entries_path
    artifact.planned_row_count = planned_count
    return artifact


__all__ = ["plan_single_entity_import"]
