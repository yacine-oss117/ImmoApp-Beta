"""Maintenance operations for storage."""

from __future__ import annotations

import logging

from core.data import storage_events as storage_events_data
from core.data import storage_objects as storage_data
from server.immoapp_server.observability import business_span
from server.pg.uow import get_uow

from .storage_client import BotoCoreError, ClientError, get_storage_client
from .storage_errors import StorageError

logger = logging.getLogger(__name__)


def purge_deleted_objects(*, older_than_days: int, limit: int = 100) -> int:
    with business_span(
        "storage.purge_deleted_objects",
        attributes={"storage.older_than_days": older_than_days, "storage.limit": limit},
    ) as span:
        deleted = 0
        with get_uow().session() as session:
            rows = storage_data.list_deleted_storage_objects(
                session, older_than_days=older_than_days, limit=limit
            )
        span.set_attribute("storage.candidates", len(rows))

        for row in rows:
            try:
                get_storage_client().delete_object(Bucket=row["bucket"], Key=row["object_key"])
            except (BotoCoreError, ClientError):
                logger.warning("Failed to delete storage object %s", row.get("id"))
                continue
            with get_uow().transaction() as session:
                storage_data.mark_storage_purged(session, storage_id=str(row["id"]))
                storage_events_data.insert_storage_event(
                    session,
                    storage_id=str(row["id"]),
                    event_type="purged",
                    user_id=row.get("user_id"),
                    role=row.get("role"),
                    created_ip=row.get("created_ip"),
                    details=None,
                )
            deleted += 1
        span.set_attribute("storage.purged", deleted)
        return deleted


def purge_pending_objects(*, older_than_hours: int, limit: int = 100) -> int:
    """Expire stale pending uploads that never completed."""
    deleted = 0
    with get_uow().session() as session:
        rows = storage_data.list_pending_storage_objects(
            session, older_than_hours=older_than_hours, limit=limit
        )

    for row in rows:
        try:
            get_storage_client().delete_object(Bucket=row["bucket"], Key=row["object_key"])
        except (BotoCoreError, ClientError):
            logger.info("Pending storage object missing in bucket: %s", row.get("id"))
        with get_uow().transaction() as session:
            storage_data.mark_storage_failed(
                session, storage_id=str(row["id"]), message="pending_timeout"
            )
            storage_events_data.insert_storage_event(
                session,
                storage_id=str(row["id"]),
                event_type="expired",
                user_id=row.get("user_id"),
                role=row.get("role"),
                created_ip=row.get("created_ip"),
                details=None,
            )
        deleted += 1

    return deleted


def mark_storage_deleted(
    *,
    storage_id: str,
    user_id: int | None,
    role: str | None,
    created_ip: str | None,
) -> int:
    """Soft-delete a storage object and adjust usage counters."""
    with business_span(
        "storage.mark_deleted",
        attributes={"storage.storage_id": storage_id},
    ) as span:
        with get_uow().transaction() as session:
            record = storage_data.get_storage_object(session, storage_id)
            if not record:
                span.set_attribute("storage.record_exists", False)
                raise StorageError("Object not found.")
            span.set_attribute("storage.record_exists", True)
            agency_id = record.get("agency_id")
            if isinstance(agency_id, int):
                span.set_attribute("storage.agency_id", agency_id)
            if record.get("status") == "deleted":
                span.set_attribute("storage.already_deleted", True)
                return 0
            span.set_attribute("storage.already_deleted", False)
            size_bytes = storage_data.mark_storage_deleted(session, storage_id=storage_id)
            span.set_attribute("storage.size_bytes", size_bytes)
            if size_bytes:
                storage_data.bump_storage_usage(
                    session, agency_id=record["agency_id"], delta_bytes=-size_bytes
                )
            storage_events_data.insert_storage_event(
                session,
                storage_id=storage_id,
                event_type="deleted",
                user_id=user_id,
                role=role,
                created_ip=created_ip,
                details={"size_bytes": size_bytes},
            )
            return size_bytes


def restore_deleted_storage(
    *,
    storage_id: str,
    user_id: int | None,
    role: str | None,
    created_ip: str | None,
) -> int:
    """Restore a soft-deleted, non-purged storage object and usage counters."""
    with business_span(
        "storage.restore_deleted",
        attributes={"storage.storage_id": storage_id},
    ) as span:
        with get_uow().transaction() as session:
            record = storage_data.get_storage_object(session, storage_id)
            if not record:
                span.set_attribute("storage.record_exists", False)
                raise StorageError("Object not found.")
            span.set_attribute("storage.record_exists", True)
            if record.get("status") != "deleted":
                span.set_attribute("storage.was_deleted", False)
                return 0
            span.set_attribute("storage.was_deleted", True)
            size_bytes = storage_data.restore_deleted_storage(session, storage_id=storage_id)
            span.set_attribute("storage.size_bytes", size_bytes)
            if size_bytes:
                storage_data.bump_storage_usage(
                    session, agency_id=record["agency_id"], delta_bytes=size_bytes
                )
            storage_events_data.insert_storage_event(
                session,
                storage_id=storage_id,
                event_type="restored",
                user_id=user_id,
                role=role,
                created_ip=created_ip,
                details={"size_bytes": size_bytes},
            )
            return size_bytes


def purge_storage_object_now(*, storage_id: str) -> int:
    """Immediately purge an internal storage object record and bucket object."""
    with business_span(
        "storage.purge_object_now",
        attributes={"storage.storage_id": storage_id},
    ) as span:
        with get_uow().session() as session:
            record = storage_data.get_storage_object(session, storage_id)
        if not record:
            span.set_attribute("storage.record_exists", False)
            return 0

        span.set_attribute("storage.record_exists", True)
        if record.get("purpose") is not None:
            span.set_attribute("storage.purpose", str(record["purpose"]))

        try:
            get_storage_client().delete_object(Bucket=record["bucket"], Key=record["object_key"])
        except (BotoCoreError, ClientError):
            logger.warning(
                "Failed to delete storage object %s from bucket during immediate purge",
                storage_id,
                exc_info=True,
            )

        with get_uow().transaction() as session:
            deleted_bytes = storage_data.delete_storage_object(session, storage_id=storage_id)
            if record.get("status") == "ready" and deleted_bytes:
                storage_data.bump_storage_usage(
                    session,
                    agency_id=record["agency_id"],
                    delta_bytes=-deleted_bytes,
                )
        span.set_attribute("storage.deleted_bytes", deleted_bytes)
        return deleted_bytes
