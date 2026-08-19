"""
ALE (encryption) maintenance tasks.
"""

from __future__ import annotations

import os
from datetime import UTC

from server.services.ale_maintenance import (
    finalize_ale_search_rotation,
    purge_ale_pii,
    reindex_ale_search,
    rotate_ale_keys,
    start_ale_search_rotation,
)

from .adaptive_batch import adaptive_batch_process
from .tasks_core import iter_active_agency_batches, task_decorator


@task_decorator()
def purge_ale_pii_task(_task: object, retention_days: int = 365) -> dict[str, object]:
    """Purge encrypted PII for soft-deleted rows after retention window."""
    deleted = purge_ale_pii(days=retention_days, dry_run=False)
    return {"deleted": deleted, "retention_days": retention_days}


@task_decorator()
def ale_rotation_alert_task(_task: object) -> dict[str, object]:
    """Alert owners when ALE key or search pepper rotation is overdue."""
    from datetime import datetime

    from core.data import db_schema_meta
    from server.api.notifications import record_and_notify
    from server.pg.uow import admin_transaction, use_security_context

    key_days = int(os.environ.get("ALE_KEY_ROTATION_DAYS", "180"))
    pepper_days = int(os.environ.get("ALE_SEARCH_ROTATION_DAYS", "180"))
    now = datetime.now(UTC)

    with admin_transaction() as session:
        db_schema_meta.ensure_meta_table(session)
        key_ts_raw = db_schema_meta.get_meta(session, "ale_key_rotation_at")
        pepper_ts_raw = db_schema_meta.get_meta(session, "ale_search_rotation_at")
        alert_key_raw = db_schema_meta.get_meta(session, "ale_key_rotation_alert_at")
        alert_pepper_raw = db_schema_meta.get_meta(session, "ale_search_rotation_alert_at")

    def _parse_ts(raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def _days_since(ts: datetime | None) -> int | None:
        if ts is None:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return int((now - ts).total_seconds() // 86400)

    key_age = _days_since(_parse_ts(key_ts_raw))
    pepper_age = _days_since(_parse_ts(pepper_ts_raw))
    key_alert_age = _days_since(_parse_ts(alert_key_raw))
    pepper_alert_age = _days_since(_parse_ts(alert_pepper_raw))

    alerts_sent = 0
    pages_processed = 0
    agencies_processed = 0
    if key_age is not None and key_age > key_days and (key_alert_age is None or key_alert_age > 1):

        def _notify_key_rotation(aid: int) -> None:
            nonlocal alerts_sent
            with use_security_context(agency_id=aid, is_superuser=False):
                record_and_notify(
                    scope="owner",
                    event_type="ale_key_rotation_due",
                    title="Security Key Rotation Required",
                    body=(
                        "ALE encryption key rotation is overdue. "
                        f"Last rotation was {key_age} days ago."
                    ),
                )
                alerts_sent += 1

        with admin_transaction() as session:
            for agency_batch in iter_active_agency_batches(session, batch_size=500):
                pages_processed += 1
                agencies_processed += len(agency_batch)
                adaptive_batch_process(
                    agency_batch,
                    _notify_key_rotation,
                    label="maintenance.ale_key_alert",
                )
        with admin_transaction() as session:
            db_schema_meta.set_meta(session, "ale_key_rotation_alert_at", now.isoformat())

    if (
        pepper_age is not None
        and pepper_age > pepper_days
        and (pepper_alert_age is None or pepper_alert_age > 1)
    ):

        def _notify_search_rotation(aid: int) -> None:
            nonlocal alerts_sent
            with use_security_context(agency_id=aid, is_superuser=False):
                record_and_notify(
                    scope="owner",
                    event_type="ale_search_rotation_due",
                    title="Search Pepper Rotation Required",
                    body=(
                        "ALE search pepper rotation is overdue. "
                        f"Last rotation was {pepper_age} days ago."
                    ),
                )
                alerts_sent += 1

        with admin_transaction() as session:
            for agency_batch in iter_active_agency_batches(session, batch_size=500):
                pages_processed += 1
                agencies_processed += len(agency_batch)
                adaptive_batch_process(
                    agency_batch,
                    _notify_search_rotation,
                    label="maintenance.ale_search_alert",
                )
        with admin_transaction() as session:
            db_schema_meta.set_meta(session, "ale_search_rotation_alert_at", now.isoformat())

    return {
        "key_age_days": key_age,
        "pepper_age_days": pepper_age,
        "alerts_sent": alerts_sent,
        "pages_processed": pages_processed,
        "agencies_processed": agencies_processed,
    }


@task_decorator()
def rotate_ale_keys_task(_task: object, limit: int | None = None) -> dict[str, object]:
    """Optional auto-rotation (guarded by ALE_AUTOROTATE_ENABLED=1)."""
    if os.environ.get("ALE_AUTOROTATE_ENABLED", "0") != "1":
        return {"skipped": True, "reason": "ALE_AUTOROTATE_ENABLED=0"}
    updated = rotate_ale_keys(dry_run=False, limit=limit)
    return {"updated": updated, "skipped": False}


@task_decorator()
def reindex_ale_search_task(
    _task: object, force: bool = False, limit: int | None = None
) -> dict[str, object]:
    """Optional auto-reindex (guarded by ALE_AUTOREINDEX_ENABLED=1)."""
    if os.environ.get("ALE_AUTOREINDEX_ENABLED", "0") != "1":
        return {"skipped": True, "reason": "ALE_AUTOREINDEX_ENABLED=0"}
    updated = reindex_ale_search(dry_run=False, force=force, limit=limit)
    return {"updated": updated, "skipped": False}


@task_decorator()
def rotate_ale_search_keys_task(
    _task: object,
    *,
    mode: str,
    to_version: str | None = None,
) -> dict[str, object]:
    """
    Rotate ALE search-key metadata with explicit mode.

    Modes:
    - start: requires ``to_version`` (e.g. ``v2``)
    - finalize: clears previous version after reindex window
    """
    normalized_mode = (mode or "").strip().lower()
    if normalized_mode not in {"start", "finalize"}:
        raise ValueError("mode must be 'start' or 'finalize'")

    if normalized_mode == "start":
        if not to_version:
            raise ValueError("to_version is required when mode='start'")
        result: dict[str, object] = dict(start_ale_search_rotation(to_version=to_version))
    else:
        result = dict(finalize_ale_search_rotation())
    result["mode"] = normalized_mode
    return result


__all__ = [
    "purge_ale_pii_task",
    "ale_rotation_alert_task",
    "rotate_ale_keys_task",
    "reindex_ale_search_task",
    "rotate_ale_search_keys_task",
]
