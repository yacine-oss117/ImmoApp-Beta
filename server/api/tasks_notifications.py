"""
Notification maintenance tasks.
"""

from __future__ import annotations

from .adaptive_batch import adaptive_batch_process
from .tasks_core import iter_active_agency_batches, logger, task_decorator


@task_decorator()
def purge_notifications_task(_task: object, retention_days: int = 60) -> dict[str, object]:
    """Purge old notifications across all agencies (RLS-scoped)."""
    from server.pg.uow import admin_transaction, get_uow, use_security_context
    from server.services.notifications import purge_notifications_older_than

    total_deleted = 0
    agencies_processed = 0
    pages_processed = 0

    def _purge_for_agency(aid: int) -> None:
        nonlocal total_deleted, agencies_processed
        with use_security_context(agency_id=aid, is_superuser=False):
            with get_uow().transaction() as session:
                deleted = purge_notifications_older_than(days=retention_days, session=session)
                total_deleted += int(deleted or 0)
                agencies_processed += 1

    with admin_transaction() as session:
        for agency_batch in iter_active_agency_batches(session, batch_size=500):
            pages_processed += 1
            adaptive_batch_process(
                agency_batch,
                _purge_for_agency,
                label="maintenance.notifications",
            )

    logger.info(
        "Notification purge complete: %s deleted across %s agencies (%s pages)",
        total_deleted,
        agencies_processed,
        pages_processed,
    )
    return {
        "deleted": total_deleted,
        "agencies": agencies_processed,
        "pages": pages_processed,
        "retention_days": retention_days,
    }


__all__ = ["purge_notifications_task"]
