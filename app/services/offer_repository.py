"""
Offer Service - Manages offers via Unit of Work.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.models import Offer
from app.models_cast import as_int
from app.services.api_client import (
    ApiError,
    api_delete_resilient,
    api_get,
    api_post_resilient,
    as_dict,
)
from app.services.lookup_service import (
    get_action_id,
    get_action_name,
    get_property_type_id,
    get_property_type_name,
    get_wilaya_id,
    get_wilaya_name,
)
from app.services.offline_entity_mutations import (
    OfflineCreateRequest,
    create_entity,
    delete_entity,
    update_entity,
)
from app.services.offline_projection import list_projection_records, overlay_model_detail
from app.services.offline_types import OfflineEntityRef

__all__ = [
    "get_offers_for_listing",
    "get_offer_by_id",
    "create_offer",
    "update_offer",
    "delete_offer",
    "fetch_deleted_offers",
    "restore_offer",
    "purge_offer",
]


def _overlay_listing_offers(listing_id: int, items: list[Offer]) -> list[Offer]:
    records = [
        record
        for record in list_projection_records("offer")
        if as_int(record.data.get("listing_id"), default=0) == int(listing_id)
    ]
    hidden_positive = {
        int(record.local_id)
        for record in records
        if int(record.local_id) > 0 and record.sync_status == "pending_delete"
    }
    by_positive = {
        int(record.local_id): record
        for record in records
        if int(record.local_id) > 0 and record.sync_status != "pending_delete"
    }
    merged: list[Offer] = []
    seen: set[int] = set()
    for item in items:
        item_id = int(item.id or 0)
        seen.add(item_id)
        if item_id in hidden_positive:
            continue
        record = by_positive.get(item_id)
        merged.append((overlay_model_detail("offer", item_id, item) if record else item) or item)
    local_only = [
        overlay_model_detail("offer", int(record.local_id), None)
        for record in records
        if int(record.local_id) < 0 and record.sync_status != "pending_delete"
    ]
    synced_positive = [
        overlay_model_detail("offer", int(record.local_id), None)
        for record in records
        if int(record.local_id) > 0
        and int(record.local_id) not in seen
        and record.sync_status == "synced"
    ]
    return [item for item in [*local_only, *synced_positive, *merged] if item is not None]


def create_offer(listing_id: int, input_data: Mapping[str, object]) -> int:
    """Create a new offer and update match cache using UoW."""
    processed_data = _prepare_offer_payload(input_data)
    try:
        created_id = create_entity(
            OfflineCreateRequest(
                entity_type="offer",
                path_template="/listings/{listing_id}/offers",
                path_refs={
                    "listing_id": OfflineEntityRef(entity_type="listing", local_id=int(listing_id))
                },
                request_body=processed_data,
                projection_data={**processed_data, "listing_id": int(listing_id)},
                label="offer.create",
            )
        )
    except ApiError as exc:
        if exc.status_code == 404:
            raise ValueError("Listing not found.") from exc
        raise ValueError(exc.message) from exc
    return int(created_id)


def update_offer(offer_id: int, input_data: Mapping[str, object]) -> None:
    """Update an offer and update match cache using UoW."""
    processed_data = _prepare_offer_payload(input_data)
    try:
        update_entity(
            "offer",
            offer_id,
            f"/offers/{offer_id}",
            processed_data,
            dedupe_key=f"PUT:/offers/{offer_id}",
            label="offer.update",
        )
    except ApiError as exc:
        if exc.status_code == 409:
            raise ValueError("Offer changed since you opened it. Refresh and try again.") from exc
        if exc.status_code == 404:
            raise ValueError("Offer not found.") from exc
        raise ValueError(exc.message) from exc


def _prepare_offer_payload(input_data: Mapping[str, object]) -> dict[str, object]:
    """Prepare offer payload for the strict backend write contract."""
    processed_data = dict(input_data)
    processed_data.pop("id", None)
    processed_data.pop("listing_id", None)
    _fill_lookup_fields(processed_data)
    return processed_data


def _label_name(value: object) -> str:
    text = str(value or "").strip()
    if " - " in text:
        name, code = text.rsplit(" - ", 1)
        if code.strip().isdigit():
            return name.strip()
    return text


def _fill_lookup_fields(processed_data: dict[str, object]) -> None:
    if as_int(processed_data.get("type_id"), default=0) <= 0:
        type_id = get_property_type_id(str(processed_data.get("type") or ""))
        if type_id:
            processed_data["type_id"] = int(type_id)
            processed_data["type"] = get_property_type_name(int(type_id)) or processed_data.get(
                "type", ""
            )

    if as_int(processed_data.get("action_id"), default=0) <= 0:
        action_id = get_action_id(str(processed_data.get("action") or ""))
        if action_id:
            processed_data["action_id"] = int(action_id)
            processed_data["action"] = get_action_name(int(action_id)) or processed_data.get(
                "action", ""
            )

    wilaya_name = _label_name(processed_data.get("wilaya"))
    if wilaya_name:
        processed_data["wilaya"] = wilaya_name
    if as_int(processed_data.get("wilaya_id"), default=0) <= 0:
        wilaya_id = get_wilaya_id(wilaya_name)
        if wilaya_id:
            processed_data["wilaya_id"] = int(wilaya_id)
            processed_data["wilaya"] = get_wilaya_name(int(wilaya_id)) or wilaya_name


def delete_offer(offer_id: int) -> None:
    """Soft-delete an offer using UoW."""
    delete_entity(
        "offer",
        offer_id,
        f"/offers/{offer_id}",
        dedupe_key=f"DELETE:/offers/{offer_id}",
        label="offer.delete",
    )


def restore_offer(offer_id: int) -> None:
    """Restore an offer using UoW."""
    api_post_resilient(
        f"/offers/{offer_id}/restore",
        dedupe_key=f"POST:/offers/{offer_id}/restore",
        label="offer.restore",
    )


def purge_offer(offer_id: int) -> None:
    """Purge an offer using UoW."""
    api_delete_resilient(
        f"/offers/{offer_id}/purge",
        params={"confirm": f"PURGE_OFFER_{offer_id}"},
        dedupe_key=f"DELETE:/offers/{offer_id}/purge",
        label="offer.purge",
    )


def get_offers_for_listing(
    listing_id: int, limit: int | None = None, offset: int = 0, include_deleted: bool = False
) -> list[Offer]:
    """Fetch all offers for a listing using UoW."""
    response = api_get(
        f"/listings/{listing_id}/offers",
        params={
            "limit": limit,
            "offset": offset,
            "include_deleted": int(include_deleted),
        },
    )
    payload = as_dict(response)
    items = payload.get("items")
    if isinstance(items, list):
        offers = [Offer.from_row(item) for item in items if isinstance(item, dict)]
        return _overlay_listing_offers(listing_id, offers)
    return _overlay_listing_offers(listing_id, [])


def get_offer_by_id(offer_id: int, include_deleted: bool = False) -> Offer | None:
    """Fetch a single offer by ID using UoW."""
    try:
        response = api_get(
            f"/offers/{offer_id}",
            params={"include_deleted": int(include_deleted)},
        )
    except ApiError as exc:
        if exc.status_code == 404:
            return None
        raise
    payload = as_dict(response)
    offer = Offer.from_row(payload) if payload else None
    return overlay_model_detail("offer", offer_id, offer)


def fetch_deleted_offers(limit: int | None = None, offset: int = 0) -> list[Offer]:
    """Fetch soft-deleted offers using UoW."""
    response = api_get(
        "/offers/deleted",
        params={"limit": limit, "offset": offset},
    )
    payload = as_dict(response)
    items = payload.get("items")
    if isinstance(items, list):
        return [Offer.from_row(item) for item in items if isinstance(item, dict)]
    return []
