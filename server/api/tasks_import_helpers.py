"""
Shared helpers for import-related Celery tasks.
"""

from __future__ import annotations

from typing import Any, cast

from server.imports.models import ImportJob
from server.services.import_parsers import parser_for_filename
from server.services.import_permissions import UserProtocol
from server.services.import_service import ImportPermissionError, ImportService


def get_import_parser(filename: str) -> tuple[Any, str] | None:
    return parser_for_filename(filename)


def load_import_user(user_id: int) -> UserProtocol | None:
    from server.accounts.models import User

    try:
        return cast(UserProtocol, User.objects.get(id=user_id))
    except User.DoesNotExist:
        return None


def load_import_service(user_id: int) -> ImportService | None:
    user = load_import_user(user_id)
    if user is None:
        return None
    try:
        return ImportService(user)
    except ImportPermissionError:
        return None


def mark_import_failed(service: ImportService, job: ImportJob, message: str) -> dict[str, object]:
    job.status = ImportJob.Status.FAILED
    job.error_message = message
    job.progress = 0
    job.save()
    return {"session_id": str(job.id), "status": "failed", "error": message}


__all__ = [
    "get_import_parser",
    "load_import_service",
    "load_import_user",
    "mark_import_failed",
]
