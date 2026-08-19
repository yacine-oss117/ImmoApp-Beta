"""
Import job persistence helpers.
"""

from __future__ import annotations

from typing import cast

from server.imports.models import ImportJob
from server.services.import_permissions import UserProtocol


def create_job(
    user: UserProtocol,
    *,
    agency_id: int,
    filename: str,
    file_type: str,
    headers: list[str],
    source_path: str,
) -> ImportJob:
    return cast(
        ImportJob,
        ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=filename,
            file_type=file_type,
            source_path=source_path,
            status=ImportJob.Status.PENDING,
            stage=ImportJob.Stage.UPLOAD,
            detected_columns=headers,
        ),
    )


def get_job_scoped(
    *,
    job_id: str,
    user: UserProtocol,
    agency_id: int,
) -> ImportJob | None:
    """Fetch a job visible to the current caller only.

    Import jobs are user-owned artifacts. We enforce user+agency scoping so
    session IDs cannot be used to access another user's imports.
    """
    try:
        return cast(ImportJob, ImportJob.objects.get(id=job_id, user=user, agency_id=agency_id))
    except ImportJob.DoesNotExist:
        return None


def get_job_by_id(*, job_id: str) -> ImportJob | None:
    try:
        return cast(ImportJob, ImportJob.objects.get(id=job_id))
    except ImportJob.DoesNotExist:
        return None


def get_job_by_task_id(user: UserProtocol, task_id: str) -> ImportJob | None:
    try:
        return cast(
            ImportJob,
            ImportJob.objects.get(task_id=task_id, user=user, agency_id=user.agency_id),
        )
    except ImportJob.DoesNotExist:
        return None


def update_job(job: ImportJob) -> None:
    job.save()
