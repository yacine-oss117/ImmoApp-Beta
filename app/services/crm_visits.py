"""
CRM visit operations.
"""

from __future__ import annotations

from typing import cast

from app.models import Visit
from app.models_cast import as_int
from app.services.api_client import (
    ApiError,
    api_delete_resilient,
    api_get,
    api_post_resilient,
    as_dict,
)
from app.services.offline_entity_mutations import (
    OfflineCreateRequest,
    create_entity,
    delete_entity,
    update_entity,
)
from app.services.offline_projection import overlay_model_list
from app.services.offline_types import OfflineEntityRef
from app.shared_types import VisitData


def create_visit(visit_data: VisitData) -> int:
    """Create a new visit using UoW."""
    payload_in = {k: v for k, v in dict(visit_data).items() if v is not None}
    try:
        created_id = create_entity(
            OfflineCreateRequest(
                entity_type="visit",
                path="/crm/visits",
                request_body=payload_in,
                projection_data=payload_in,
                body_refs={
                    "client_id": OfflineEntityRef(
                        entity_type="client",
                        local_id=as_int(payload_in.get("client_id"), default=0),
                    ),
                    "listing_id": OfflineEntityRef(
                        entity_type="listing",
                        local_id=as_int(payload_in.get("listing_id"), default=0),
                    ),
                },
                label="visit.create",
            )
        )
    except ApiError as exc:
        raise ValueError(exc.message) from exc
    return int(created_id)


def fetch_visits(
    limit: int = 100,
    offset: int = 0,
    client_id: int | None = None,
    status: str | None = None,
    scheduled_date: str | None = None,
) -> list[Visit]:
    """Fetch visits using UoW."""
    response = api_get(
        "/crm/visits",
        params={
            "limit": limit,
            "offset": offset,
            "client_id": client_id,
            "status": status,
            "scheduled_date": scheduled_date,
        },
    )
    payload = as_dict(response)
    items = payload.get("items")
    if isinstance(items, list):
        visits = [Visit.from_row(item) for item in items if isinstance(item, dict)]
        return cast(list[Visit], overlay_model_list("visit", visits))
    return cast(list[Visit], overlay_model_list("visit", []))


def update_visit(visit_id: int, visit_data: dict[str, object]) -> None:
    """Update a visit using UoW."""
    try:
        payload_in = {k: v for k, v in dict(visit_data).items() if v is not None}
        update_entity(
            "visit",
            visit_id,
            f"/crm/visits/{visit_id}",
            payload_in,
            dedupe_key=f"PUT:/crm/visits/{visit_id}",
            label="visit.update",
        )
    except ApiError as exc:
        if exc.status_code == 409:
            raise ValueError("Visit changed since you opened it. Refresh and try again.") from exc
        if exc.status_code == 404:
            raise ValueError("Visit not found.") from exc
        raise ValueError(exc.message) from exc


def delete_visit(visit_id: int) -> None:
    """Delete a visit using UoW."""
    delete_entity(
        "visit",
        visit_id,
        f"/crm/visits/{visit_id}",
        dedupe_key=f"DELETE:/crm/visits/{visit_id}",
        label="visit.delete",
    )


def fetch_deleted_visits(
    limit: int = 100,
    offset: int = 0,
) -> list[Visit]:
    """Fetch soft-deleted visits using UoW."""
    response = api_get(
        "/crm/visits/deleted",
        params={"limit": limit, "offset": offset},
    )
    payload = as_dict(response)
    items = payload.get("items")
    if isinstance(items, list):
        return [Visit.from_row(item) for item in items if isinstance(item, dict)]
    return []


def restore_visit(visit_id: int) -> None:
    """Restore a soft-deleted visit using UoW."""
    api_post_resilient(
        f"/crm/visits/{visit_id}/restore",
        dedupe_key=f"POST:/crm/visits/{visit_id}/restore",
        label="visit.restore",
    )


def purge_visit(visit_id: int) -> None:
    """Permanently delete a visit using UoW."""
    api_delete_resilient(
        f"/crm/visits/{visit_id}/purge",
        params={"confirm": f"PURGE_VISIT_{visit_id}"},
        dedupe_key=f"DELETE:/crm/visits/{visit_id}/purge",
        label="visit.purge",
    )
