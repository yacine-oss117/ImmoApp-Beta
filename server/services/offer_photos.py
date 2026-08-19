"""
Offer photo service layer.
"""

from __future__ import annotations

from core.data import offer_photos_repository as data
from server.pg.uow import get_uow
from server.services import offer_photo_lifecycle as lifecycle

OfferPhotoAttachResult = lifecycle.OfferPhotoAttachResult


def list_offer_photos(*, offer_id: int, include_deleted: bool = False) -> list[dict[str, object]]:
    with get_uow().session() as session:
        return data.list_offer_photos(session, offer_id=offer_id, include_deleted=include_deleted)


def get_offer_photo_by_id(*, photo_id: int) -> dict[str, object] | None:
    with get_uow().session() as session:
        return data.get_offer_photo_by_id(session, photo_id=photo_id)


def add_offer_photo(
    *,
    offer_id: int,
    storage_id: str,
    position: int = 0,
    user_id: int | None = None,
    role: str | None = None,
    created_ip: str | None = None,
) -> OfferPhotoAttachResult:
    return lifecycle.add_offer_photo(
        offer_id=offer_id,
        storage_id=storage_id,
        position=position,
        user_id=user_id,
        role=role,
        created_ip=created_ip,
    )


def delete_offer_photo(
    *,
    photo_id: int,
    user_id: int | None = None,
    role: str | None = None,
    created_ip: str | None = None,
) -> bool:
    return lifecycle.delete_offer_photo(
        photo_id=photo_id,
        user_id=user_id,
        role=role,
        created_ip=created_ip,
    )
