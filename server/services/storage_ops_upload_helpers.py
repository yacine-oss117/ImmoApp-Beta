"""Shared helpers for storage uploads."""

from __future__ import annotations

from core.data import storage_events as storage_events_data
from core.data import storage_objects as storage_data
from server.pg.tenant_context import require_agency_id as require_tenant_agency_id
from server.pg.uow import get_uow

from .storage_errors import StorageError
from .storage_validation import enforce_limits

_STORAGE_QUOTA_LOCK_NS = 53_201


def require_agency_id() -> int:
    return require_tenant_agency_id(error_message="agency_id is required for storage.")


def create_storage_record(
    *,
    bucket: str,
    object_key: str,
    user_id: int | None,
    role: str | None,
    purpose: str,
    content_type: str | None,
    size_bytes: int,
    checksum: str | None,
    created_ip: str | None,
) -> str:
    agency_id = require_agency_id()
    if user_id is None:
        raise StorageError("user_id is required for storage ownership.")
    if not role:
        raise StorageError("role is required for storage ownership.")
    with get_uow().transaction() as session:
        # Serialize quota checks + pending reservation per agency to prevent
        # parallel-upload quota bypass.
        session.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            (_STORAGE_QUOTA_LOCK_NS, agency_id),
        )
        enforce_limits(
            size_bytes,
            agency_id,
            user_id=user_id,
            purpose=purpose,
            session=session,
        )
        storage_id = storage_data.create_storage_object(
            session,
            bucket=bucket,
            object_key=object_key,
            user_id=user_id,
            role=role,
            purpose=purpose,
            content_type=content_type,
            size_bytes=size_bytes,
            checksum=checksum,
            created_ip=created_ip,
        )
        if purpose != "import_artifact":
            storage_events_data.insert_storage_event(
                session,
                storage_id=storage_id,
                event_type="created",
                user_id=user_id,
                role=role,
                created_ip=created_ip,
                details={"purpose": purpose, "object_key": object_key},
            )
    return storage_id


def mark_storage_failed(
    *,
    storage_id: str,
    message: str,
    user_id: int | None,
    role: str | None,
    created_ip: str | None,
    purpose: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    with get_uow().transaction() as session:
        storage_data.mark_storage_failed(session, storage_id=storage_id, message=message)
        if purpose != "import_artifact":
            storage_events_data.insert_storage_event(
                session,
                storage_id=storage_id,
                event_type="failed",
                user_id=user_id,
                role=role,
                created_ip=created_ip,
                details=details or {"error": message},
            )


def mark_storage_ready(
    *,
    storage_id: str,
    content_type: str | None,
    size_bytes: int,
    checksum: str | None,
    agency_id: int,
    user_id: int | None,
    role: str | None,
    created_ip: str | None,
    purpose: str | None = None,
) -> None:
    with get_uow().transaction() as session:
        storage_data.mark_storage_ready(
            session,
            storage_id=storage_id,
            content_type=content_type,
            size_bytes=size_bytes,
            checksum=checksum,
        )
        storage_data.bump_storage_usage(session, agency_id=agency_id, delta_bytes=size_bytes)
        if purpose != "import_artifact":
            storage_events_data.insert_storage_event(
                session,
                storage_id=storage_id,
                event_type="ready",
                user_id=user_id,
                role=role,
                created_ip=created_ip,
                details={"size_bytes": size_bytes},
            )
