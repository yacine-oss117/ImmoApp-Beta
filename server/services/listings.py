"""
Postgres-backed listing operations with validation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from core.contracts.offer_photo_lifecycle import (
    PHOTO_DELETE_ORIGIN_LISTING_DELETED,
    PHOTO_DELETE_ORIGIN_LISTING_PURGED,
    PHOTO_DELETE_PARENT_SCOPE_LISTING,
)
from core.data import demande_repo_read as demande_read
from core.data import listing_repo_read as read
from core.data import listing_repo_write as write
from core.data import offer_repo_read as offer_read
from core.data.match_cache import mark_clients_in_wilaya_dirty
from core.data.types import ListingInput
from core.matcher.ports.db import DbSession
from core.models import Listing
from core.models_cast import as_int
from server.pg.uow import get_uow

from . import offer_photo_lifecycle
from .ale_policy import LISTING_ALE_POLICIES
from .match_jobs import enqueue_rebuild_offer_pairs, enqueue_rebuild_wilaya_pairs


def _fetch_listings_page(
    session: DbSession,
    *,
    limit: int | None,
    offset: int,
    search: str,
    status: str | None,
    include_deleted: bool,
) -> list[Listing]:
    if limit is None or limit <= 0 or offset < 0:
        return read.fetch_listings(session, limit, offset, search, status, include_deleted)
    cursor: int | None = None
    current_offset = 0
    while current_offset < offset:
        step = min(limit, offset - current_offset)
        page = read.fetch_listings_cursor(
            session,
            limit=step,
            cursor=cursor,
            search=search,
            status=status,
            include_deleted=include_deleted,
        )
        current_offset += len(page)
        if len(page) < step:
            return []
        last_id = getattr(page[-1], "id", 0) if page else 0
        cursor = int(last_id) if int(last_id) > 0 else None
        if cursor is None:
            return []
    return read.fetch_listings_cursor(
        session,
        limit=limit,
        cursor=cursor,
        search=search,
        status=status,
        include_deleted=include_deleted,
    )


def _infer_listing_total(*, limit: int | None, offset: int, item_count: int) -> int | None:
    if limit is None or limit <= 0:
        return None
    if item_count < limit:
        return max(0, int(offset)) + int(item_count)
    return None


def _enqueue_match_pairs_rebuild_for_wilayas(wilaya_ids: set[int]) -> None:
    if not wilaya_ids:
        return
    for wilaya_id in wilaya_ids:
        enqueue_rebuild_wilaya_pairs(wilaya_id)


def _enqueue_offer_rebuilds_with_hints(hints: dict[int, list[int]]) -> None:
    for offer_id, demande_ids in hints.items():
        enqueue_rebuild_offer_pairs(offer_id, demande_ids_hint=demande_ids)


def _enqueue_offer_rebuild_fallbacks(
    offer_ids: list[int],
    offer_demande_hints: dict[int, list[int]],
) -> None:
    for offer_id in offer_ids:
        if offer_id not in offer_demande_hints:
            enqueue_rebuild_offer_pairs(offer_id)


def _run_listing_upsert_post_commit(
    offer_demande_hints: dict[int, list[int]],
    offer_ids_to_rebuild: list[int],
) -> None:
    _enqueue_offer_rebuilds_with_hints(offer_demande_hints)
    _enqueue_offer_rebuild_fallbacks(offer_ids_to_rebuild, offer_demande_hints)


def _run_listing_delete_or_purge_post_commit(
    wilaya_ids: set[int],
    offer_demande_hints: dict[int, list[int]],
    offer_ids: list[int],
) -> None:
    _enqueue_match_pairs_rebuild_for_wilayas(wilaya_ids)
    _enqueue_offer_rebuilds_with_hints(offer_demande_hints)
    _enqueue_offer_rebuild_fallbacks(offer_ids, offer_demande_hints)


def _run_listing_restore_post_commit(
    wilaya_ids: set[int],
    offer_ids: list[int],
) -> None:
    _enqueue_match_pairs_rebuild_for_wilayas(wilaya_ids)
    for offer_id in offer_ids:
        enqueue_rebuild_offer_pairs(offer_id)


def _listing_upsert_post_commit_callback(
    *,
    offer_demande_hints: dict[int, list[int]],
    offer_ids_to_rebuild: list[int],
) -> Callable[[], None]:
    def _callback() -> None:
        _run_listing_upsert_post_commit(
            {offer_id: list(ids) for offer_id, ids in offer_demande_hints.items()},
            list(offer_ids_to_rebuild),
        )

    return _callback


def _listing_delete_or_purge_post_commit_callback(
    *,
    wilaya_ids: set[int],
    offer_demande_hints: dict[int, list[int]],
    offer_ids: list[int],
) -> Callable[[], None]:
    def _callback() -> None:
        _run_listing_delete_or_purge_post_commit(
            set(wilaya_ids),
            {offer_id: list(ids) for offer_id, ids in offer_demande_hints.items()},
            list(offer_ids),
        )

    return _callback


def _listing_restore_post_commit_callback(
    *,
    wilaya_ids: set[int],
    offer_ids: list[int],
) -> Callable[[], None]:
    def _callback() -> None:
        _run_listing_restore_post_commit(set(wilaya_ids), list(offer_ids))

    return _callback


def fetch_listings(
    *,
    limit: int | None = None,
    offset: int = 0,
    search: str = "",
    status: str | None = "available",
    include_deleted: bool = False,
) -> list[Listing]:
    """Fetch listings with optional filtering."""
    with get_uow().session() as session:
        return _fetch_listings_page(
            session,
            limit=limit,
            offset=offset,
            search=search,
            status=status,
            include_deleted=include_deleted,
        )


def fetch_listings_with_count(
    *,
    limit: int | None = None,
    offset: int = 0,
    search: str = "",
    status: str | None = "available",
    include_deleted: bool = False,
) -> tuple[list[Listing], int]:
    """Fetch paginated listings and total count using a single DB session."""
    with get_uow().session() as session:
        items = _fetch_listings_page(
            session,
            limit=limit,
            offset=offset,
            search=search,
            status=status,
            include_deleted=include_deleted,
        )
        inferred_total = _infer_listing_total(limit=limit, offset=offset, item_count=len(items))
        total = (
            inferred_total
            if inferred_total is not None
            else read.get_total_listing_count(session, search, status, include_deleted)
        )
    return items, total


def fetch_listings_cursor(
    *,
    limit: int = 100,
    cursor: int | None = None,
    search: str = "",
    status: str | None = "available",
    include_deleted: bool = False,
) -> list[Listing]:
    """Fetch listings using cursor pagination (id > cursor)."""
    with get_uow().session() as session:
        return read.fetch_listings_cursor(
            session,
            limit=limit,
            cursor=cursor,
            search=search,
            status=status,
            include_deleted=include_deleted,
        )


def get_total_listing_count(
    *,
    search: str = "",
    status: str | None = "available",
    include_deleted: bool = False,
) -> int:
    """Get total listing count for pagination."""
    with get_uow().session() as session:
        return int(read.get_total_listing_count(session, search, status, include_deleted))


def get_listings_surface_generation(*, agency_id: int) -> int:
    """Return the durable generation for listing list/count response caches."""
    with get_uow().session() as session:
        return int(read.get_listings_surface_generation(session, agency_id=int(agency_id)))


def get_total_deleted_listing_count(
    *,
    search: str = "",
) -> int:
    """Get total deleted listing count for pagination."""
    with get_uow().session() as session:
        return read.get_total_deleted_listing_count(session, search)


def get_listing_by_id(
    listing_id: int,
    *,
    include_deleted: bool = False,
) -> Listing | None:
    """Get a single listing by ID."""
    with get_uow().session() as session:
        return read.get_listing_by_id(session, listing_id, include_deleted)


def find_listing_ids_by_phone(
    phone: str,
    exclude_id: int | None = None,
) -> list[int]:
    """Find listing IDs by phone number."""
    with get_uow().session() as session:
        return read.find_listing_ids_by_phone(session, phone, exclude_id)


def fetch_deleted_listings(
    *,
    limit: int | None = None,
    offset: int = 0,
    search: str = "",
) -> list[Listing]:
    """Fetch soft-deleted listings for trash management."""
    with get_uow().session() as session:
        return read.fetch_deleted_listings(session, limit, offset, search)


def upsert_listing(
    listing_data: Mapping[str, object],
    *,
    actor: str | None = None,
) -> int:
    """Insert or update a listing."""
    listing_id = as_int(listing_data.get("id"))
    should_rebuild_offers = False
    offer_ids_to_rebuild: list[int] = []
    offer_demande_hints: dict[int, list[int]] = {}
    with get_uow().transaction(actor=actor) as session:
        existing = None
        if listing_id:
            existing = read.get_listing_by_id_for_update(session, listing_id)
        processed = normalize_listing_data(listing_data, existing=existing)
        if existing is not None:
            previous_status = str(existing.status or "")
            next_status = str(processed.get("status") or "")
            should_rebuild_offers = previous_status != next_status
            if should_rebuild_offers:
                offer_ids_to_rebuild = offer_read.get_offer_ids_for_listing(
                    session,
                    int(existing.id),
                    include_deleted=False,
                )
                offer_demande_hints = demande_read.get_demande_ids_for_offers(
                    session,
                    offer_ids_to_rebuild,
                )
                wilayas = offer_read.get_offer_wilaya_ids_for_listing(
                    session,
                    int(existing.id),
                    include_deleted=False,
                )
                for wilaya_id in wilayas:
                    mark_clients_in_wilaya_dirty(session, wilaya_id)
        result_id = write.upsert_listing(session, processed)
        if should_rebuild_offers:
            session.on_commit(
                _listing_upsert_post_commit_callback(
                    offer_demande_hints=offer_demande_hints,
                    offer_ids_to_rebuild=offer_ids_to_rebuild,
                )
            )
    return int(result_id or 0)


def delete_listing(listing_id: int, *, actor: str | None = None) -> None:
    """Soft-delete a listing and mark clients in related wilayas as dirty for matching."""
    with get_uow().transaction(actor=actor) as session:
        wilayas = offer_read.get_offer_wilaya_ids_for_listing(
            session,
            listing_id,
            include_deleted=False,
        )
        offer_ids = offer_read.get_offer_ids_for_listing(session, listing_id, include_deleted=False)
        offer_demande_hints = demande_read.get_demande_ids_for_offers(session, offer_ids)
        write.delete_listing(session, listing_id)
        offer_photo_lifecycle.mark_offer_photos_deleted_for_offers(
            session,
            offer_ids=offer_ids,
            delete_origin=PHOTO_DELETE_ORIGIN_LISTING_DELETED,
            delete_parent_scope=PHOTO_DELETE_PARENT_SCOPE_LISTING,
            delete_parent_id=listing_id,
        )
        for wilaya_id in wilayas:
            mark_clients_in_wilaya_dirty(session, wilaya_id)
        session.on_commit(
            _listing_delete_or_purge_post_commit_callback(
                wilaya_ids=wilayas,
                offer_demande_hints=offer_demande_hints,
                offer_ids=offer_ids,
            )
        )


def restore_listing(listing_id: int, *, actor: str | None = None) -> None:
    """Restore a soft-deleted listing."""
    with get_uow().transaction(actor=actor) as session:
        write.restore_listing(session, listing_id)
        wilayas = offer_read.get_offer_wilaya_ids_for_listing(
            session,
            listing_id,
            include_deleted=False,
        )
        offer_ids = offer_read.get_offer_ids_for_listing(session, listing_id, include_deleted=False)
        offer_photo_lifecycle.restore_offer_photos_for_offers(
            session,
            offer_ids=offer_ids,
            delete_origin=PHOTO_DELETE_ORIGIN_LISTING_DELETED,
            delete_parent_scope=PHOTO_DELETE_PARENT_SCOPE_LISTING,
            delete_parent_id=listing_id,
        )
        for wilaya_id in wilayas:
            mark_clients_in_wilaya_dirty(session, wilaya_id)
        session.on_commit(
            _listing_restore_post_commit_callback(
                wilaya_ids=wilayas,
                offer_ids=offer_ids,
            )
        )


def purge_listing(listing_id: int, *, actor: str | None = None) -> None:
    """Permanently delete a listing."""
    with get_uow().transaction(actor=actor) as session:
        wilayas = offer_read.get_offer_wilaya_ids_for_listing(
            session,
            listing_id,
            include_deleted=True,
        )
        offer_ids = offer_read.get_offer_ids_for_listing(session, listing_id, include_deleted=True)
        offer_demande_hints = demande_read.get_demande_ids_for_offers(session, offer_ids)
        offer_photo_lifecycle.mark_offer_photos_deleted_for_offers(
            session,
            offer_ids=offer_ids,
            delete_origin=PHOTO_DELETE_ORIGIN_LISTING_PURGED,
            delete_parent_scope=PHOTO_DELETE_PARENT_SCOPE_LISTING,
            delete_parent_id=listing_id,
            include_deleted_for_cleanup=True,
        )
        write.purge_listing(session, listing_id)
        for wilaya_id in wilayas:
            mark_clients_in_wilaya_dirty(session, wilaya_id)
        session.on_commit(
            _listing_delete_or_purge_post_commit_callback(
                wilaya_ids=wilayas,
                offer_demande_hints=offer_demande_hints,
                offer_ids=offer_ids,
            )
        )


def normalize_listing_data(
    listing_data: Mapping[str, object], existing: Listing | None = None
) -> ListingInput:
    from .ale_helper import normalize_ale_fields

    workspace: dict[str, Any] = dict(existing.to_dict()) if existing else {}
    workspace.update(listing_data)

    normalize_ale_fields(
        workspace,
        LISTING_ALE_POLICIES,
        changed_fields=set(listing_data.keys()),
    )

    processed: ListingInput = {
        "family_name": str(workspace.get("family_name", "")),
        "phone": str(workspace.get("phone", "")),
        "remarks": str(workspace.get("remarks", "")),
        "is_vip": 1 if workspace.get("is_vip") else 0,
        "status": str(workspace.get("status", "available")),
        "created_at": (
            str(workspace["created_at"]) if workspace.get("created_at") is not None else None
        ),
        "created_loc": str(workspace.get("created_loc", "")),
        "updated_at": (
            str(workspace["updated_at"]) if workspace.get("updated_at") is not None else None
        ),
        "family_name_enc": str(workspace.get("family_name_enc", "")),
        "family_name_search_src": (
            str(workspace["family_name_search_src"])
            if workspace.get("family_name_search_src") is not None
            else None
        ),
        "phone_enc": str(workspace.get("phone_enc", "")),
        "phone_search_src": (
            str(workspace["phone_search_src"])
            if workspace.get("phone_search_src") is not None
            else None
        ),
        "remarks_enc": str(workspace.get("remarks_enc", "")),
    }
    listing_id = as_int(workspace.get("id"), default=0)
    if listing_id > 0:
        processed["id"] = listing_id
    row_version = as_int(workspace.get("row_version"), default=0)
    if row_version > 0:
        processed["row_version"] = row_version
    agency_id = as_int(workspace.get("agency_id"), default=0)
    if agency_id > 0:
        processed["agency_id"] = agency_id
    return processed
