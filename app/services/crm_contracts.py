"""
CRM contract operations.
"""

from __future__ import annotations

from datetime import date
from typing import cast

from app.models import Contract
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
from app.shared_types import ContractData, ContractUpdateData


def create_contract(contract_data: ContractData) -> int:
    """Create a new contract using the API."""
    processed_data = {
        "client_id": int(contract_data["client_id"]),
        "listing_id": int(contract_data["listing_id"]),
        "contract_type": str(contract_data["contract_type"]),
        "amount": contract_data.get("amount"),
        "deposit": contract_data.get("deposit"),
        "terms": str(contract_data.get("terms", "")),
        "notes": str(contract_data.get("notes", "")),
        "status": contract_data.get("status"),
        "start_date": _normalize_date_value(contract_data.get("start_date")),
        "end_date": _normalize_date_value(contract_data.get("end_date")),
    }
    payload_in = {k: v for k, v in processed_data.items() if v is not None}
    try:
        created_id = create_entity(
            OfflineCreateRequest(
                entity_type="contract",
                path="/crm/contracts",
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
                label="contract.create",
            )
        )
    except ApiError as exc:
        raise ValueError(exc.message) from exc
    return int(created_id)


def activate_contract(contract_id: int) -> None:
    """Activate a contract using UoW."""
    api_post_resilient(
        f"/crm/contracts/{contract_id}/activate",
        dedupe_key=f"POST:/crm/contracts/{contract_id}/activate",
        label="contract.activate",
    )


def cancel_contract(contract_id: int, restore_status: bool = True) -> None:
    """Cancel a contract using UoW."""
    api_post_resilient(
        f"/crm/contracts/{contract_id}/cancel",
        {"restore_status": restore_status},
        dedupe_key=f"POST:/crm/contracts/{contract_id}/cancel",
        label="contract.cancel",
    )


def delete_contract(contract_id: int) -> None:
    """Soft-delete a contract using UoW."""
    delete_entity(
        "contract",
        contract_id,
        f"/crm/contracts/{contract_id}",
        dedupe_key=f"DELETE:/crm/contracts/{contract_id}",
        label="contract.delete",
    )


def print_contract(contract_id: int) -> None:
    """Mark contract as pending_signature using UoW."""
    api_post_resilient(
        f"/crm/contracts/{contract_id}/print",
        dedupe_key=f"POST:/crm/contracts/{contract_id}/print",
        label="contract.print",
    )


def restore_contract(contract_id: int) -> None:
    """Restore a soft-deleted contract using UoW."""
    api_post_resilient(
        f"/crm/contracts/{contract_id}/restore",
        dedupe_key=f"POST:/crm/contracts/{contract_id}/restore",
        label="contract.restore",
    )


def purge_contract(contract_id: int) -> None:
    """Permanently delete a contract using UoW."""
    api_delete_resilient(
        f"/crm/contracts/{contract_id}/purge",
        params={"confirm": f"PURGE_CONTRACT_{contract_id}"},
        dedupe_key=f"DELETE:/crm/contracts/{contract_id}/purge",
        label="contract.purge",
    )


def update_contract(contract_id: int, contract_data: ContractUpdateData) -> None:
    """Update contract information using UoW."""
    processed = dict(contract_data)
    if "start_date" in contract_data:
        processed["start_date"] = _normalize_date_value(contract_data.get("start_date"))
    if "end_date" in contract_data:
        processed["end_date"] = _normalize_date_value(contract_data.get("end_date"))
    payload_in = {k: v for k, v in processed.items() if v is not None}
    try:
        update_entity(
            "contract",
            contract_id,
            f"/crm/contracts/{contract_id}",
            payload_in,
            dedupe_key=f"PUT:/crm/contracts/{contract_id}",
            label="contract.update",
        )
    except ApiError as exc:
        if exc.status_code == 409:
            raise ValueError(
                "Contract changed since you opened it. Refresh and try again."
            ) from exc
        if exc.status_code == 404:
            raise ValueError("Contract not found.") from exc
        raise ValueError(exc.message) from exc


def fetch_contracts(
    status: str | None = None, contract_type: str | None = None, limit: int = 100, offset: int = 0
) -> list[Contract]:
    """Fetch contracts using UoW."""
    response = api_get(
        "/crm/contracts",
        params={
            "status": status,
            "contract_type": contract_type,
            "limit": limit,
            "offset": offset,
        },
    )
    payload = as_dict(response)
    items = payload.get("items")
    if isinstance(items, list):
        contracts = [Contract.from_row(item) for item in items if isinstance(item, dict)]
        return cast(list[Contract], overlay_model_list("contract", contracts))
    return cast(list[Contract], overlay_model_list("contract", []))


def fetch_deleted_contracts(limit: int = 100, offset: int = 0) -> list[Contract]:
    """Fetch soft-deleted contracts using UoW."""
    response = api_get(
        "/crm/contracts/deleted",
        params={"limit": limit, "offset": offset},
    )
    payload = as_dict(response)
    items = payload.get("items")
    if isinstance(items, list):
        return [Contract.from_row(item) for item in items if isinstance(item, dict)]
    return []


def _normalize_date_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None
