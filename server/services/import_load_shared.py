"""Shared transactional load helpers for importer mode orchestrators."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypedDict

from server.imports.models import ImportJob
from server.pg.uow import PgSession
from server.services.import_executor_helpers import insert_batch
from server.services.import_load_policy import timed_insert_batch_rows
from server.services.import_progress_runtime import persist_job_progress
from server.services.import_types import ImportLoadOutcome, ImportResult


class PlannedInsertEntry(TypedDict):
    row: int
    data: dict[str, object]
    original: dict[str, object]


class ChildAnchorErrorRow(TypedDict):
    row: int
    errors: list[str]
    data: dict[str, object]


@dataclass(frozen=True)
class ImportLoadProgressSnapshot:
    rows_total: int
    rows_processed: int
    rows_created: int
    rows_updated: int
    rows_skipped: int
    rows_review: int
    current_chunk: int
    chunks_total: int
    phase: str
    bundle_mode: str
    progress: int | None = None
    review_overflow_count_value: int = 0


InsertBatchFn = Callable[..., list[int]]
PersistJobProgressFn = Callable[..., object]


def flush_insert_entries(
    *,
    write_session: PgSession,
    entity_type: str,
    batch_entries: list[PlannedInsertEntry],
    imported_ids: list[int],
    load_outcome: ImportLoadOutcome,
    insert_batch_fn: InsertBatchFn = insert_batch,
) -> tuple[list[int], float]:
    result = timed_insert_batch_rows(
        write_session=write_session,
        entity_type=entity_type,
        batch_rows=[entry["data"] for entry in batch_entries],
        load_outcome=load_outcome,
        insert_batch_fn=insert_batch_fn,
    )
    imported_ids.extend(result.created_ids)
    return result.created_ids, result.db_duration


def persist_load_progress_snapshot(
    *,
    write_session: PgSession | None,
    job: ImportJob,
    snapshot: ImportLoadProgressSnapshot,
    persist_job_progress_fn: PersistJobProgressFn = persist_job_progress,
) -> None:
    persist_job_progress_fn(
        write_session=write_session,
        job=job,
        rows_total=snapshot.rows_total,
        rows_processed=snapshot.rows_processed,
        rows_created=snapshot.rows_created,
        rows_updated=snapshot.rows_updated,
        rows_skipped=snapshot.rows_skipped,
        rows_review=snapshot.rows_review,
        current_chunk=snapshot.current_chunk,
        chunks_total=snapshot.chunks_total,
        phase=snapshot.phase,
        bundle_mode=snapshot.bundle_mode,
        progress=snapshot.progress,
        review_overflow_count_value=snapshot.review_overflow_count_value,
    )


def finalize_successful_load(
    *,
    result: ImportResult,
    load_outcome: ImportLoadOutcome,
    imported_ids: list[int],
    created_entity_counts: dict[str, int],
    committed_entities: set[str],
    schedule_after_commit: Callable[[], None],
) -> None:
    result.created_count = len(imported_ids)
    result.created_entity_counts = {
        str(entity_type): int(created_count)
        for entity_type, created_count in created_entity_counts.items()
        if int(created_count) > 0
    }
    result.created_ids = list(imported_ids)
    result.success = True
    load_outcome.committed_entities.update(
        str(entity_type) for entity_type in committed_entities if str(entity_type or "").strip()
    )
    schedule_after_commit()


__all__ = [
    "ChildAnchorErrorRow",
    "ImportLoadProgressSnapshot",
    "PlannedInsertEntry",
    "finalize_successful_load",
    "flush_insert_entries",
    "persist_load_progress_snapshot",
]
