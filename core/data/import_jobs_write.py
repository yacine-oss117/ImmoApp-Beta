"""
Write helpers for import job progress/state updates.
"""

from __future__ import annotations

from psycopg.types.json import Jsonb

from core.matcher.ports.db import DbSession


def update_import_job_progress(
    session: DbSession,
    *,
    job_id: object,
    progress: int,
    status: str,
    stage: str | None = None,
    progress_detail: dict[str, object] | None = None,
) -> None:
    """Update import job progress within the active SQL transaction."""
    bounded_progress = max(0, min(100, int(progress)))
    if stage is not None or progress_detail is not None:
        progress_detail_value = Jsonb(progress_detail) if progress_detail is not None else None
        session.execute(
            """
            UPDATE imports_importjob
            SET progress = %s,
                status = %s,
                stage = COALESCE(%s, stage),
                progress_detail = COALESCE(%s, progress_detail),
                updated_at = NOW()
            WHERE id = %s
            """,
            [bounded_progress, status, stage, progress_detail_value, str(job_id)],
        )
        return
    session.execute(
        """
        UPDATE imports_importjob
        SET progress = %s,
            status = %s,
            updated_at = NOW()
        WHERE id = %s
        """,
        [bounded_progress, status, str(job_id)],
    )
