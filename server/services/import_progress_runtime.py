"""Progress payload shaping and detached progress persistence for importer execution."""

from __future__ import annotations

import logging
import os
from typing import Any

from psycopg_pool import PoolTimeout

from core.data import import_jobs_write
from server.imports.models import ImportJob
from server.pg.uow import get_uow

logger = logging.getLogger(__name__)


def _progress_pool_timeout_seconds() -> float:
    raw_value = os.environ.get("IMMOAPP_IMPORT_PROGRESS_POOL_TIMEOUT_S", "0.25").strip()
    try:
        timeout_value = float(raw_value)
    except ValueError:
        return 0.25
    return max(0.05, timeout_value)


def build_progress_detail(
    *,
    rows_total: int,
    rows_processed: int,
    rows_created: int,
    rows_updated: int,
    rows_skipped: int,
    rows_review: int,
    current_chunk: int,
    chunks_total: int,
    phase: str,
    bundle_mode: str,
    review_overflow_count_value: int = 0,
) -> dict[str, object]:
    return {
        "rows_total": max(0, int(rows_total)),
        "rows_processed": max(0, int(rows_processed)),
        "rows_created": max(0, int(rows_created)),
        "rows_updated": max(0, int(rows_updated)),
        "rows_skipped": max(0, int(rows_skipped)),
        "rows_review": max(0, int(rows_review)),
        "current_chunk": max(0, int(current_chunk)),
        "chunks_total": max(0, int(chunks_total)),
        "phase": str(phase or "executing"),
        "bundle_mode": str(bundle_mode or "single_entity"),
        "review_overflow_count": max(0, int(review_overflow_count_value)),
    }


def persist_job_progress(
    *,
    write_session: Any | None,
    job: ImportJob,
    rows_total: int,
    rows_processed: int,
    rows_created: int,
    rows_updated: int,
    rows_skipped: int,
    rows_review: int,
    current_chunk: int,
    chunks_total: int,
    phase: str,
    bundle_mode: str,
    progress: int | None = None,
    review_overflow_count_value: int = 0,
) -> dict[str, object]:
    progress_detail = build_progress_detail(
        rows_total=rows_total,
        rows_processed=rows_processed,
        rows_created=rows_created,
        rows_updated=rows_updated,
        rows_skipped=rows_skipped,
        rows_review=rows_review,
        current_chunk=current_chunk,
        chunks_total=chunks_total,
        phase=phase,
        bundle_mode=bundle_mode,
        review_overflow_count_value=review_overflow_count_value,
    )
    effective_progress = progress
    if effective_progress is None:
        if rows_total <= 0:
            effective_progress = 0
        else:
            effective_progress = min(99, int((max(0, rows_processed) / max(1, rows_total)) * 100))
    if write_session is None:
        try:
            with get_uow().transaction(
                actor=f"import-progress:{job.id}",
                timeout=_progress_pool_timeout_seconds(),
            ) as progress_session:
                import_jobs_write.update_import_job_progress(
                    progress_session,
                    job_id=job.id,
                    progress=int(effective_progress),
                    status=str(ImportJob.Status.RUNNING),
                    stage=str(ImportJob.Stage.EXECUTION),
                    progress_detail=progress_detail,
                )
        except PoolTimeout:
            logger.info(
                "Skipping detached import progress update due to pool saturation",
                extra={"job_id": str(job.id), "phase": phase},
            )
    else:
        import_jobs_write.update_import_job_progress(
            write_session,
            job_id=job.id,
            progress=int(effective_progress),
            status=str(ImportJob.Status.RUNNING),
            stage=str(ImportJob.Stage.EXECUTION),
            progress_detail=progress_detail,
        )
    job.progress = int(effective_progress)
    job.progress_detail = dict(progress_detail)
    return progress_detail


__all__ = ["build_progress_detail", "persist_job_progress"]
