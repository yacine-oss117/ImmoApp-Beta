"""Transactional offer-photo lifecycle orchestration."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from core.contracts.offer_photo_lifecycle import (
    PHOTO_DELETE_ORIGIN_MANUAL,
)
from core.contracts.offer_photo_media import OFFER_PHOTO_PURPOSE
from core.data import offer_photos_repository as photos_data
from core.data import storage_events as storage_events_data
from core.data import storage_objects as storage_data
from core.data.errors import NotFoundError
from core.models_cast import as_int
from server.pg.tenant_context import require_agency_id
from server.pg.uow import PgSession, get_uow
from server.services.storage_errors import StorageError

_OFFER_PHOTO_AGGREGATE_LOCK_PERSON = b"offerphoto"


def _noop_lifecycle_hook(_session: PgSession, _storage_ids: tuple[str, ...]) -> None:
    return None


_after_aggregate_locks_acquired: Callable[[PgSession, tuple[str, ...]], None] = _noop_lifecycle_hook
_before_aggregate_locks_acquired: Callable[[PgSession, tuple[str, ...]], None] = (
    _noop_lifecycle_hook
)


@dataclass(frozen=True)
class OfferPhotoAttachResult:
    photo_id: int
    created: bool
    restored: bool = False

    @property
    def status_code(self) -> int:
        return 201 if self.created or self.restored else 200


def _photo_id(row: dict[str, object]) -> int:
    return as_int(row.get("id"))


def _storage_size(row: dict[str, object]) -> int:
    return as_int(row.get("size_bytes"))


def _agency_id(row: dict[str, object]) -> int:
    return as_int(row.get("agency_id"))


def _offer_photo_aggregate_lock_key(storage_id: str) -> int:
    digest = hashlib.blake2b(
        str(storage_id).encode("utf-8"),
        digest_size=8,
        person=_OFFER_PHOTO_AGGREGATE_LOCK_PERSON,
    ).digest()
    key = int.from_bytes(digest, byteorder="big", signed=False)
    if key >= 2**63:
        key -= 2**64
    return key


def _lock_photo_storage_aggregate(session: PgSession, storage_id: str) -> None:
    session.execute(
        "SELECT pg_advisory_xact_lock(%s)",
        (_offer_photo_aggregate_lock_key(storage_id),),
    )


def _lock_photo_storage_aggregates(
    session: PgSession, storage_ids: list[str] | tuple[str, ...] | set[str]
) -> list[str]:
    ordered = sorted({str(storage_id) for storage_id in storage_ids if str(storage_id)})
    if ordered:
        _before_aggregate_locks_acquired(session, tuple(ordered))
    for storage_id in ordered:
        _lock_photo_storage_aggregate(session, storage_id)
    if ordered:
        _after_aggregate_locks_acquired(session, tuple(ordered))
    return ordered


def _lock_storage_rows(
    session: PgSession,
    storage_ids: list[str] | tuple[str, ...] | set[str],
) -> dict[str, dict[str, object]]:
    ordered = sorted({str(storage_id) for storage_id in storage_ids if str(storage_id)})
    if not ordered:
        return {}
    return storage_data.lock_storage_objects(session, ordered)


def _insert_storage_event(
    session: PgSession,
    *,
    storage_id: str,
    event_type: str,
    user_id: int | None,
    role: str | None,
    created_ip: str | None,
    size_bytes: int,
) -> None:
    storage_events_data.insert_storage_event(
        session,
        storage_id=storage_id,
        event_type=event_type,
        user_id=user_id,
        role=role,
        created_ip=created_ip,
        details={"size_bytes": size_bytes},
    )


def _restore_storage_in_transaction(
    session: PgSession,
    *,
    storage_id: str,
    storage_row: dict[str, object],
    user_id: int | None,
    role: str | None,
    created_ip: str | None,
) -> None:
    size_bytes = storage_data.restore_deleted_storage(session, storage_id=storage_id)
    if size_bytes:
        storage_data.bump_storage_usage(
            session,
            agency_id=_agency_id(storage_row),
            delta_bytes=size_bytes,
        )
    _insert_storage_event(
        session,
        storage_id=storage_id,
        event_type="restored",
        user_id=user_id,
        role=role,
        created_ip=created_ip,
        size_bytes=size_bytes,
    )


def _delete_storage_if_unreferenced_in_transaction(
    session: PgSession,
    *,
    storage_id: str,
    storage_row: dict[str, object] | None,
    user_id: int | None,
    role: str | None,
    created_ip: str | None,
) -> None:
    if storage_row is None or storage_row.get("status") != "ready":
        return
    remaining = photos_data.count_active_storage_refs(session, storage_id=storage_id)
    if remaining > 0:
        return
    size_bytes = storage_data.mark_storage_deleted(session, storage_id=storage_id)
    if size_bytes:
        storage_data.bump_storage_usage(
            session,
            agency_id=_agency_id(storage_row),
            delta_bytes=-size_bytes,
        )
    _insert_storage_event(
        session,
        storage_id=storage_id,
        event_type="deleted",
        user_id=user_id,
        role=role,
        created_ip=created_ip,
        size_bytes=size_bytes,
    )


def add_offer_photo(
    *,
    offer_id: int,
    storage_id: str,
    position: int = 0,
    user_id: int | None = None,
    role: str | None = None,
    created_ip: str | None = None,
) -> OfferPhotoAttachResult:
    agency_id = require_agency_id(error_message="agency_id is required for offer photos.")
    with get_uow().transaction() as session:
        _lock_photo_storage_aggregates(session, [storage_id])
        storage_row = _lock_storage_rows(session, [storage_id]).get(storage_id)
        if storage_row is None:
            raise ValueError("Storage object not found.")
        offer = photos_data.lock_active_offer(session, offer_id=offer_id)
        if offer is None:
            raise NotFoundError("Offer not found")
        if storage_row.get("purpose") != OFFER_PHOTO_PURPOSE:
            raise ValueError("Storage object purpose mismatch.")
        if _agency_id(storage_row) != agency_id or _agency_id(offer) != agency_id:
            raise ValueError("Storage object does not belong to this agency.")

        existing = photos_data.lock_active_offer_photo_for_storage(
            session,
            offer_id=offer_id,
            storage_id=storage_id,
        )
        if existing is not None:
            return OfferPhotoAttachResult(
                photo_id=_photo_id(existing),
                created=False,
                restored=False,
            )

        status = str(storage_row.get("status") or "")
        if status == "deleted":
            deleted_photo = photos_data.lock_deleted_offer_photo_for_storage(
                session,
                offer_id=offer_id,
                storage_id=storage_id,
            )
            if deleted_photo is None:
                raise ValueError("Storage object is not ready.")
            _restore_storage_in_transaction(
                session,
                storage_id=storage_id,
                storage_row=storage_row,
                user_id=user_id,
                role=role,
                created_ip=created_ip,
            )
            restored_id = photos_data.restore_deleted_offer_photo_for_storage(
                session,
                offer_id=offer_id,
                storage_id=storage_id,
                position=position,
            )
            if restored_id is None:
                raise StorageError("Storage object could not be restored.")
            return OfferPhotoAttachResult(
                photo_id=restored_id,
                created=False,
                restored=True,
            )

        if status != "ready":
            raise ValueError("Storage object is not ready.")

        photo_id, inserted = photos_data.create_offer_photo(
            session,
            offer_id=offer_id,
            storage_id=storage_id,
            position=position,
        )
        return OfferPhotoAttachResult(photo_id=photo_id, created=inserted)


def delete_offer_photo(
    *,
    photo_id: int,
    user_id: int | None = None,
    role: str | None = None,
    created_ip: str | None = None,
) -> bool:
    with get_uow().transaction() as session:
        photo = photos_data.get_offer_photo_by_id(session, photo_id=photo_id)
        if photo is None:
            return False
        storage_id = str(photo.get("storage_id") or "")
        storage_rows: dict[str, dict[str, object]] = {}
        if storage_id:
            _lock_photo_storage_aggregates(session, [storage_id])
            storage_rows = _lock_storage_rows(session, [storage_id])
        locked_photo = photos_data.lock_offer_photo_by_id(session, photo_id=photo_id)
        if locked_photo is None or locked_photo.get("deleted_at") is not None:
            return False
        deleted = photos_data.mark_offer_photo_deleted(
            session,
            photo_id=photo_id,
            delete_origin=PHOTO_DELETE_ORIGIN_MANUAL,
        )
        if deleted and storage_id:
            _delete_storage_if_unreferenced_in_transaction(
                session,
                storage_id=storage_id,
                storage_row=storage_rows.get(storage_id),
                user_id=user_id,
                role=role,
                created_ip=created_ip,
            )
        return deleted


def mark_offer_photos_deleted_for_offers(
    session: PgSession,
    *,
    offer_ids: list[int],
    delete_origin: str,
    delete_parent_scope: str,
    delete_parent_id: int,
    user_id: int | None = None,
    role: str | None = None,
    created_ip: str | None = None,
    include_deleted_for_cleanup: bool = False,
) -> int:
    candidate_storage_ids = photos_data.list_storage_ids_for_offer_ids(
        session,
        offer_ids=offer_ids,
        include_deleted=include_deleted_for_cleanup,
    )
    ordered_storage_ids = _lock_photo_storage_aggregates(session, candidate_storage_ids)
    storage_rows = _lock_storage_rows(session, ordered_storage_ids)
    deleted_storage_ids = photos_data.mark_offer_photos_deleted_for_offers(
        session,
        offer_ids=offer_ids,
        delete_origin=delete_origin,
        delete_parent_scope=delete_parent_scope,
        delete_parent_id=delete_parent_id,
        include_deleted_for_cleanup=include_deleted_for_cleanup,
    )
    deleted_count = len(deleted_storage_ids)
    if include_deleted_for_cleanup:
        deleted_storage_ids.extend(candidate_storage_ids)
    for storage_id in sorted(set(deleted_storage_ids)):
        _delete_storage_if_unreferenced_in_transaction(
            session,
            storage_id=storage_id,
            storage_row=storage_rows.get(storage_id),
            user_id=user_id,
            role=role,
            created_ip=created_ip,
        )
    return deleted_count


def restore_offer_photos_for_offers(
    session: PgSession,
    *,
    offer_ids: list[int],
    delete_origin: str,
    delete_parent_scope: str,
    delete_parent_id: int,
    user_id: int | None = None,
    role: str | None = None,
    created_ip: str | None = None,
) -> int:
    storage_ids = photos_data.list_storage_ids_for_offer_ids(
        session,
        offer_ids=offer_ids,
        include_deleted=True,
        delete_origin=delete_origin,
        delete_parent_scope=delete_parent_scope,
        delete_parent_id=delete_parent_id,
    )
    ordered_storage_ids = _lock_photo_storage_aggregates(session, storage_ids)
    storage_rows = _lock_storage_rows(session, ordered_storage_ids)
    for storage_id in ordered_storage_ids:
        storage_row = storage_rows.get(storage_id)
        if storage_row is None or storage_row.get("status") != "deleted":
            continue
        if storage_row.get("purpose") != OFFER_PHOTO_PURPOSE:
            continue
        _restore_storage_in_transaction(
            session,
            storage_id=storage_id,
            storage_row=storage_row,
            user_id=user_id,
            role=role,
            created_ip=created_ip,
        )
    return photos_data.restore_offer_photos_for_offers(
        session,
        offer_ids=offer_ids,
        delete_origin=delete_origin,
        delete_parent_scope=delete_parent_scope,
        delete_parent_id=delete_parent_id,
    )


__all__ = [
    "OfferPhotoAttachResult",
    "add_offer_photo",
    "delete_offer_photo",
    "mark_offer_photos_deleted_for_offers",
    "restore_offer_photos_for_offers",
]
