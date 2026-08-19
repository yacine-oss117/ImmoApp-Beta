"""
Postgres-backed offer operations with validation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.contracts.offer_photo_lifecycle import (
    PHOTO_DELETE_ORIGIN_OFFER_DELETED,
    PHOTO_DELETE_ORIGIN_OFFER_PURGED,
    PHOTO_DELETE_PARENT_SCOPE_OFFER,
)
from core.data import demande_repo_read
from core.data import offer_repo_read as read
from core.data import offer_repo_write as write
from core.data.match_cache import mark_clients_for_demande_ids_dirty, mark_clients_in_wilaya_dirty
from core.models import Offer
from core.models_cast import as_int
from core.utils.common import coerce_number, norm_text
from server.pg.lookup_resolver import resolve_lookup_fields
from server.pg.uow import get_uow

from . import offer_photo_lifecycle
from .ale_policy import OFFER_ALE_POLICIES
from .match_jobs import enqueue_rebuild_offer_pairs


def create_offer(
    listing_id: int,
    input_data: Mapping[str, object],
    *,
    actor: str | None = None,
) -> int:
    """Create a new offer for a listing."""
    from .listings import get_listing_by_id

    listing = get_listing_by_id(listing_id)
    if not listing:
        raise ValueError(f"Listing {listing_id} not found")

    processed = _normalize_offer_data(input_data)
    processed["listing_id"] = listing_id
    with get_uow().transaction(actor=actor) as session:
        processed = resolve_lookup_fields(session, processed)
        _enforce_required_offer_fields(processed)
        offer_id = write.create_offer(session, listing_id, processed)
        if processed.get("wilaya_id"):
            mark_clients_in_wilaya_dirty(session, int(processed["wilaya_id"]))
        if offer_id:
            session.on_commit(
                lambda resolved_offer_id=int(offer_id): enqueue_rebuild_offer_pairs(
                    resolved_offer_id
                )
            )
    return int(offer_id or 0)


def update_offer(
    offer_id: int,
    input_data: Mapping[str, object],
    *,
    actor: str | None = None,
) -> None:
    """Validate and update an existing offer."""
    with get_uow().transaction(actor=actor) as session:
        existing = read.get_offer_by_id(session, offer_id, include_deleted=False)
        old_wilaya_id = existing.wilaya_id if existing else None
        old_demande_ids = demande_repo_read.get_demande_ids_from_precomputed_for_offer(
            session,
            offer_id,
        )
        processed = _normalize_offer_data(input_data, existing=existing)
        processed = resolve_lookup_fields(session, processed)
        _enforce_required_offer_fields(processed)
        write.update_offer(session, offer_id, processed)
        updated = read.get_offer_by_id(session, offer_id, include_deleted=False)
        new_wilaya_id = updated.wilaya_id if updated else as_int(processed.get("wilaya_id"))
        new_demande_ids = demande_repo_read.get_demande_ids_for_offer(session, offer_id)
        for wilaya_id in sorted(
            {int(value) for value in (old_wilaya_id, new_wilaya_id) if int(value or 0) > 0}
        ):
            mark_clients_in_wilaya_dirty(session, wilaya_id)
        affected_demande_ids = sorted(
            {int(value) for value in (*old_demande_ids, *new_demande_ids) if int(value) > 0}
        )
        mark_clients_for_demande_ids_dirty(session, affected_demande_ids)
        session.on_commit(
            lambda resolved_offer_id=int(offer_id), demande_ids_hint=affected_demande_ids: (
                enqueue_rebuild_offer_pairs(
                    resolved_offer_id,
                    demande_ids_hint=demande_ids_hint,
                )
            )
        )


def delete_offer(offer_id: int, *, actor: str | None = None) -> None:
    """Soft-delete an offer."""
    with get_uow().transaction(actor=actor) as session:
        offer = read.get_offer_by_id(session, offer_id, include_deleted=False)
        write.delete_offer(session, offer_id)
        offer_photo_lifecycle.mark_offer_photos_deleted_for_offers(
            session,
            offer_ids=[offer_id],
            delete_origin=PHOTO_DELETE_ORIGIN_OFFER_DELETED,
            delete_parent_scope=PHOTO_DELETE_PARENT_SCOPE_OFFER,
            delete_parent_id=offer_id,
        )
        if offer and offer.wilaya_id:
            mark_clients_in_wilaya_dirty(session, offer.wilaya_id)
        session.on_commit(
            lambda resolved_offer_id=int(offer_id): enqueue_rebuild_offer_pairs(resolved_offer_id)
        )


def restore_offer(offer_id: int, *, actor: str | None = None) -> None:
    """Restore a soft-deleted offer."""
    with get_uow().transaction(actor=actor) as session:
        write.restore_offer(session, offer_id)
        offer_photo_lifecycle.restore_offer_photos_for_offers(
            session,
            offer_ids=[offer_id],
            delete_origin=PHOTO_DELETE_ORIGIN_OFFER_DELETED,
            delete_parent_scope=PHOTO_DELETE_PARENT_SCOPE_OFFER,
            delete_parent_id=offer_id,
        )
        offer = read.get_offer_by_id(session, offer_id, include_deleted=False)
        if offer and offer.wilaya_id:
            mark_clients_in_wilaya_dirty(session, offer.wilaya_id)
        session.on_commit(
            lambda resolved_offer_id=int(offer_id): enqueue_rebuild_offer_pairs(resolved_offer_id)
        )


def purge_offer(offer_id: int, *, actor: str | None = None) -> None:
    """Permanently delete an offer."""
    with get_uow().transaction(actor=actor) as session:
        offer = read.get_offer_by_id(session, offer_id, include_deleted=True)
        offer_photo_lifecycle.mark_offer_photos_deleted_for_offers(
            session,
            offer_ids=[offer_id],
            delete_origin=PHOTO_DELETE_ORIGIN_OFFER_PURGED,
            delete_parent_scope=PHOTO_DELETE_PARENT_SCOPE_OFFER,
            delete_parent_id=offer_id,
            include_deleted_for_cleanup=True,
        )
        write.purge_offer(session, offer_id)
        if offer and offer.wilaya_id:
            mark_clients_in_wilaya_dirty(session, offer.wilaya_id)
        session.on_commit(
            lambda resolved_offer_id=int(offer_id): enqueue_rebuild_offer_pairs(resolved_offer_id)
        )


def get_offer_by_id(offer_id: int, *, include_deleted: bool = False) -> Offer | None:
    """Retrieve a single offer by ID."""
    with get_uow().session() as session:
        return read.get_offer_by_id(session, offer_id, include_deleted)


def get_offers_for_listing(
    listing_id: int,
    *,
    limit: int | None = None,
    offset: int = 0,
    include_deleted: bool = False,
) -> list[Offer]:
    """Retrieve all offers belonging to a specific listing."""
    with get_uow().session() as session:
        return read.get_offers_for_listing(session, listing_id, limit, offset, include_deleted)


def fetch_deleted_offers(*, limit: int | None = None, offset: int = 0) -> list[Offer]:
    """Fetch soft-deleted offers for trash management."""
    with get_uow().session() as session:
        return read.fetch_deleted_offers(session, limit, offset)


def get_total_deleted_offer_count() -> int:
    """Get total deleted offer count for pagination."""
    with get_uow().session() as session:
        return read.get_total_deleted_offer_count(session)


def _normalize_offer_data(
    input_data: Mapping[str, object], *, existing: Offer | None = None
) -> dict[str, object]:
    from .ale_helper import normalize_ale_fields

    if existing:
        processed = existing.to_dict()
    else:
        processed = {}

    processed.update(input_data)
    _drop_stale_lookup_ids(processed, input_data)

    def normalize_bool(val: Any) -> int:
        if val is None:
            return 0
        v = as_int(val)
        return 1 if v == 1 else 0

    processed.update(
        {
            "type": norm_text(str(processed.get("type") or "")),
            "action": norm_text(str(processed.get("action") or "")),
            "status": norm_text(str(processed.get("status") or "available")) or "available",
            "wilaya": norm_text(str(processed.get("wilaya") or "")),
            "furnished": norm_text(str(processed.get("furnished") or "")),
            "beds": as_int(processed.get("beds")),
            "surface": coerce_number(processed.get("surface")),
            "budget": coerce_number(processed.get("budget")),
            "floor": as_int(processed.get("floor"), default=0),
            "elevator": normalize_bool(processed.get("elevator")),
            "accessibility_supported": normalize_bool(processed.get("accessibility_supported")),
            "price_negotiable": normalize_bool(processed.get("price_negotiable")),
            "price_flex_pct": coerce_number(processed.get("price_flex_pct")) or 0.0,
            "latitude": coerce_number(processed.get("latitude")),
            "longitude": coerce_number(processed.get("longitude")),
        }
    )

    normalize_ale_fields(
        processed,
        OFFER_ALE_POLICIES,
        changed_fields=set(input_data.keys()),
    )

    return processed


def _drop_stale_lookup_ids(processed: dict[str, object], input_data: Mapping[str, object]) -> None:
    """Let edited property type labels resolve fresh IDs when the client omits IDs."""
    if "type" in input_data:
        processed["type_id"] = None


def _enforce_required_offer_fields(processed: Mapping[str, object]) -> None:
    """Enforce strict offer invariants after lookup resolution."""
    type_id = as_int(processed.get("type_id"), default=0)
    action_id = as_int(processed.get("action_id"), default=0)
    wilaya_id = as_int(processed.get("wilaya_id"), default=0)

    if type_id <= 0:
        raise ValueError("type_id is required for offers")
    if action_id <= 0:
        raise ValueError("action_id is required for offers")
    if wilaya_id <= 0:
        raise ValueError("wilaya_id is required for offers")

    location = str(processed.get("location") or "").strip()
    if not location:
        raise ValueError("location is required for offers")

    beds = as_int(processed.get("beds"), default=-1)
    surface = coerce_number(processed.get("surface"))
    budget = coerce_number(processed.get("budget"))
    floor = as_int(processed.get("floor"), default=-1)

    if beds < 0:
        raise ValueError("beds is required for offers")
    if surface is None or surface < 0:
        raise ValueError("surface is required for offers")
    if budget is None or budget < 0:
        raise ValueError("budget is required for offers")
    if floor < 0:
        raise ValueError("floor is required for offers")
