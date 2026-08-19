"""Durable audit helpers for import review and execution."""

from __future__ import annotations

from typing import Any, cast

from django.db import connection
from psycopg.types.json import Jsonb

from server.imports.models import ImportJob

_INSERT_SQL = """
INSERT INTO imports_importrowaudit (
    job_id,
    agency_id,
    actor_id,
    row_ordinal,
    entity_type,
    action,
    target_table,
    target_id,
    target_row_version,
    before_payload,
    after_payload,
    diff_payload,
    reasons,
    correction_payload,
    created_at
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
"""


def _job_agency_id(job: ImportJob) -> int:
    agency_id = getattr(job, "agency_id", None)
    if agency_id is not None:
        return int(agency_id)
    agency = getattr(job, "agency", None)
    resolved = getattr(agency, "id", None)
    if resolved is None:
        raise ValueError("Import job agency is required for audit writes.")
    return int(resolved)


def record_row_audits(
    *,
    job: ImportJob,
    actor_user_id: int,
    audit_entries: list[dict[str, Any]],
) -> None:
    """Persist row audits in the caller's ambient Django transaction."""
    if not audit_entries:
        return
    job_agency_id = _job_agency_id(job)

    params = [
        (
            str(job.id),
            job_agency_id,
            int(actor_user_id),
            int(entry.get("row", 0) or 0),
            str(entry.get("entity_type", job.detected_entity or "") or ""),
            str(entry.get("action", "") or ""),
            str(entry.get("target_table", "") or ""),
            int(entry.get("existing_id", 0) or 0),
            int(entry.get("row_version", 0) or 0),
            Jsonb(dict(entry.get("before_payload", {}) or {})),
            Jsonb(dict(entry.get("payload", {}) or {})),
            Jsonb(dict(entry.get("diff_payload", {}) or {})),
            Jsonb(list(entry.get("suggested_reasons", []) or [])),
            Jsonb(dict(entry.get("correction_payload", {}) or {})),
        )
        for entry in audit_entries
    ]

    with connection.cursor() as cursor:
        cursor.executemany(_INSERT_SQL, cast(Any, params))


__all__ = ["record_row_audits"]
