"""
Demande Service - Manages demandes via Unit of Work.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from app.models import Demande
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
    "create_demande",
    "delete_demande",
    "get_demande_by_id",
    "get_demandes_for_client",
    "update_demande",
    "fetch_deleted_demandes",
    "restore_demande",
    "purge_demande",
]


def _overlay_client_demandes(client_id: int, items: list[Demande]) -> list[Demande]:
    records = [
        record
        for record in list_projection_records("demande")
        if as_int(record.data.get("client_id"), default=0) == int(client_id)
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
    merged: list[Demande] = []
    seen: set[int] = set()
    for item in items:
        item_id = int(item.id or 0)
        seen.add(item_id)
        if item_id in hidden_positive:
            continue
        record = by_positive.get(item_id)
        merged.append(
            cast(Demande, overlay_model_detail("demande", item_id, item)) if record else item
        )
    local_only: list[Demande] = []
    for record in records:
        if int(record.local_id) >= 0 or record.sync_status == "pending_delete":
            continue
        local_item = cast(
            Demande | None, overlay_model_detail("demande", int(record.local_id), None)
        )
        if local_item is not None:
            local_only.append(local_item)
    synced_positive: list[Demande] = []
    for record in records:
        record_id = int(record.local_id)
        if record_id <= 0 or record_id in seen or record.sync_status != "synced":
            continue
        synced_item = cast(Demande | None, overlay_model_detail("demande", record_id, None))
        if synced_item is not None:
            synced_positive.append(synced_item)
    return [*local_only, *synced_positive, *merged]


def create_demande(client_id: int, input_data: Mapping[str, object]) -> int:
    """Create a demande and update match cache."""
    processed_data = _prepare_demande_payload(input_data)
    try:
        created_id = create_entity(
            OfflineCreateRequest(
                entity_type="demande",
                path_template="/clients/{client_id}/demandes",
                path_refs={
                    "client_id": OfflineEntityRef(entity_type="client", local_id=int(client_id))
                },
                request_body=processed_data,
                projection_data={**processed_data, "client_id": int(client_id)},
                label="demande.create",
            )
        )
    except ApiError as exc:
        if exc.status_code == 404:
            raise ValueError("Client not found.") from exc
        raise ValueError(exc.message) from exc
    return int(created_id)


def update_demande(demande_id: int, input_data: Mapping[str, object]) -> None:
    """Update a demande and update match cache."""
    processed_data = _prepare_demande_payload(input_data)
    try:
        update_entity(
            "demande",
            demande_id,
            f"/demandes/{demande_id}",
            processed_data,
            dedupe_key=f"PUT:/demandes/{demande_id}",
            label="demande.update",
        )
    except ApiError as exc:
        if exc.status_code == 409:
            raise ValueError("Demande changed since you opened it. Refresh and try again.") from exc
        if exc.status_code == 404:
            raise ValueError("Demande not found.") from exc
        raise ValueError(exc.message) from exc


def _prepare_demande_payload(input_data: Mapping[str, object]) -> dict[str, object]:
    """Prepare demande payload for the strict backend write contract."""
    processed_data = dict(input_data)
    processed_data.pop("id", None)
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


def delete_demande(demande_id: int) -> None:
    """Delete a demande and update match cache."""
    delete_entity(
        "demande",
        demande_id,
        f"/demandes/{demande_id}",
        dedupe_key=f"DELETE:/demandes/{demande_id}",
        label="demande.delete",
    )


def restore_demande(demande_id: int) -> None:
    """Restore a demande and update match cache."""
    api_post_resilient(
        f"/demandes/{demande_id}/restore",
        dedupe_key=f"POST:/demandes/{demande_id}/restore",
        label="demande.restore",
    )


def purge_demande(demande_id: int) -> None:
    """Purge a demande and update match cache."""
    api_delete_resilient(
        f"/demandes/{demande_id}/purge",
        params={"confirm": f"PURGE_DEMANDE_{demande_id}"},
        dedupe_key=f"DELETE:/demandes/{demande_id}/purge",
        label="demande.purge",
    )


def get_demande_by_id(demande_id: int, include_deleted: bool = False) -> Demande | None:
    """Fetch a single demande by ID using UoW."""
    try:
        response = api_get(
            f"/demandes/{demande_id}",
            params={"include_deleted": int(include_deleted)},
        )
    except ApiError as exc:
        if exc.status_code == 404:
            return None
        raise
    payload = as_dict(response)
    demande = Demande.from_row(payload) if payload else None
    return cast(Demande | None, overlay_model_detail("demande", demande_id, demande))


def get_demandes_for_client(
    client_id: int,
    limit: int | None = None,
    offset: int = 0,
    include_deleted: bool = False,
) -> list[Demande]:
    """Fetch all demandes for a specific client using UoW."""
    response = api_get(
        f"/clients/{client_id}/demandes",
        params={
            "limit": limit,
            "offset": offset,
            "include_deleted": int(include_deleted),
        },
    )
    payload = as_dict(response)
    items = payload.get("items")
    if isinstance(items, list):
        demandes = [Demande.from_row(item) for item in items if isinstance(item, dict)]
        return _overlay_client_demandes(client_id, demandes)
    return _overlay_client_demandes(client_id, [])


def fetch_deleted_demandes(limit: int | None = None, offset: int = 0) -> list[Demande]:
    """Fetch soft-deleted demandes using UoW."""
    response = api_get(
        "/demandes/deleted",
        params={"limit": limit, "offset": offset},
    )
    payload = as_dict(response)
    items = payload.get("items")
    if isinstance(items, list):
        return [Demande.from_row(item) for item in items if isinstance(item, dict)]
    return []
