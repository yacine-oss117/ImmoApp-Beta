"""Importer runtime cleanup and health helpers."""

from __future__ import annotations

import os
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Callable

from django.db import connection
from django.utils import timezone

from server.imports.models import ImportChunkPhase, ImportJob


def _env_hours(name: str, default: int, *, floor: int, ceiling: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(floor, min(value, ceiling))


def importer_temp_ttl_hours() -> int:
    return _env_hours("IMMOAPP_IMPORTER_TEMP_TTL_HOURS", 12, floor=1, ceiling=168)


def importer_failed_job_ttl_hours() -> int:
    return _env_hours("IMMOAPP_IMPORTER_FAILED_JOB_TTL_HOURS", 12, floor=1, ceiling=168)


def _stale_temp_paths(*, temp_ttl_hours: int | None = None) -> list[Path]:
    ttl_hours = importer_temp_ttl_hours() if temp_ttl_hours is None else int(temp_ttl_hours)
    cutoff_epoch = timezone.now().timestamp() - max(1, ttl_hours) * 3600
    temp_root = Path(tempfile.gettempdir())
    stale_paths: list[Path] = []
    for path in temp_root.glob("immoapp-import-*"):
        try:
            if path.stat().st_mtime < cutoff_epoch:
                stale_paths.append(path)
        except OSError:
            continue
    return stale_paths


def count_stale_temp_paths(*, temp_ttl_hours: int | None = None) -> int:
    return len(_stale_temp_paths(temp_ttl_hours=temp_ttl_hours))


def prune_stale_temp_paths(*, temp_ttl_hours: int | None = None) -> int:
    deleted = 0
    for path in _stale_temp_paths(temp_ttl_hours=temp_ttl_hours):
        try:
            if path.is_file():
                path.unlink(missing_ok=True)
            else:
                for child in sorted(path.rglob("*"), reverse=True):
                    if child.is_file():
                        child.unlink(missing_ok=True)
                    else:
                        child.rmdir()
                path.rmdir()
            deleted += 1
        except OSError:
            continue
    return deleted


def stale_artifact_jobs(
    *,
    failed_job_ttl_hours: int | None = None,
    limit: int = 100,
) -> list[ImportJob]:
    ttl_hours = (
        importer_failed_job_ttl_hours()
        if failed_job_ttl_hours is None
        else int(failed_job_ttl_hours)
    )
    cutoff_dt = timezone.now() - timedelta(hours=max(1, ttl_hours))
    return list(
        ImportJob.objects.filter(
            status__in=[ImportJob.Status.FAILED, ImportJob.Status.QUEUED],
            updated_at__lt=cutoff_dt,
            artifact_manifests__isnull=False,
        )
        .order_by("updated_at")
        .distinct()[: max(1, int(limit))]
    )


def count_stale_artifact_jobs(*, failed_job_ttl_hours: int | None = None) -> int:
    return len(stale_artifact_jobs(failed_job_ttl_hours=failed_job_ttl_hours, limit=1000))


def prune_stale_artifact_jobs(
    *,
    failed_job_ttl_hours: int | None = None,
    limit: int = 100,
    clear_workflow_fn: Callable[..., None] | None = None,
) -> int:
    if clear_workflow_fn is None:
        from server.services.import_chunk_workflow import clear_distributed_workflow

        clear_workflow_fn = clear_distributed_workflow
    cleared = 0
    for job in stale_artifact_jobs(
        failed_job_ttl_hours=failed_job_ttl_hours,
        limit=limit,
    ):
        try:
            clear_workflow_fn(job=job, delete_objects=True)
            cleared += 1
        except Exception:
            continue
    return cleared


def count_requeued_expired_phases() -> int:
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) AS count
                FROM imports_importchunkphase
                WHERE COALESCE((metrics_payload->>'requeued_after_lease_expiry')::boolean, FALSE)
                """)
            row = cursor.fetchone()
    except Exception:
        return 0
    return int(row[0] if row else 0)


def runtime_health_snapshot(
    *,
    temp_ttl_hours: int | None = None,
    failed_job_ttl_hours: int | None = None,
) -> dict[str, int]:
    return {
        "stale_temp_dirs": count_stale_temp_paths(temp_ttl_hours=temp_ttl_hours),
        "stale_artifact_jobs": count_stale_artifact_jobs(failed_job_ttl_hours=failed_job_ttl_hours),
        "cancelled_import_phases": int(
            ImportChunkPhase.objects.filter(status=ImportChunkPhase.Status.CANCELLED).count()
        ),
        "requeued_expired_phases": count_requeued_expired_phases(),
    }


__all__ = [
    "count_requeued_expired_phases",
    "count_stale_artifact_jobs",
    "count_stale_temp_paths",
    "importer_failed_job_ttl_hours",
    "importer_temp_ttl_hours",
    "prune_stale_artifact_jobs",
    "prune_stale_temp_paths",
    "runtime_health_snapshot",
    "stale_artifact_jobs",
]
