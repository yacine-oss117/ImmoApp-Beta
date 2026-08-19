"""
Contract operations for CRM (Postgres-backed).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date
from typing import Any

from core.data import crm_contracts as contracts
from core.data import crm_contracts_read as contracts_read
from core.data.errors import ConflictError, NotFoundError
from core.data.match_cache import mark_client_dirty, mark_clients_in_wilaya_dirty
from core.models import Contract
from server.pg.uow import DbSession, get_uow

from .ale_policy import CRM_CONTRACT_ALE_POLICIES

logger = logging.getLogger(__name__)

CONTRACT_TYPES = {"buy", "rent"}
DETAIL_UPDATE_IMMUTABLE_FIELDS = ("client_id", "listing_id", "contract_type")


def create_contract(input_data: Mapping[str, Any], *, actor: str | None = None) -> int:
    """Validate and create a new contract."""
    processed = _normalize_contract_data(input_data)
    requested_status = str(processed.get("status") or "draft").strip() or "draft"
    if requested_status != "draft":
        raise ValueError("Contracts must be created in draft status")
    processed["status"] = "draft"

    with get_uow().transaction(actor=actor) as session:
        contract_id = contracts.create_contract(session, processed)
        mark_client_dirty(session, int(processed["client_id"]))
        _mark_listing_wilaya_dirty(session, int(processed["listing_id"]))
    return contract_id


def update_contract(
    contract_id: int,
    input_data: Mapping[str, Any],
    *,
    actor: str | None = None,
) -> None:
    """Validate and update an existing contract."""
    existing = get_contract_by_id(contract_id)
    if existing is None:
        raise NotFoundError("Contract not found")
    _reject_lifecycle_or_identity_update(input_data, existing)
    processed = _normalize_contract_data(input_data, existing=existing)

    with get_uow().transaction(actor=actor) as session:
        contracts.update_contract(session, contract_id, processed)


def fetch_contracts(
    *,
    status: str | None = None,
    contract_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Contract]:
    """Fetch contracts with optional filtering."""
    with get_uow().session() as session:
        return contracts.fetch_contracts(session, status, contract_type, limit, offset)


def get_total_contract_count(*, status: str | None = None, contract_type: str | None = None) -> int:
    """Get total contract count for pagination."""
    with get_uow().session() as session:
        return contracts_read.get_total_contract_count(
            session, status=status, contract_type=contract_type
        )


def fetch_deleted_contracts(*, limit: int = 100, offset: int = 0) -> list[Contract]:
    """Fetch soft-deleted contracts for trash management."""
    with get_uow().session() as session:
        return contracts.fetch_deleted_contracts(session, limit, offset)


def get_total_deleted_contract_count() -> int:
    """Get total deleted contract count for pagination."""
    with get_uow().session() as session:
        return contracts_read.get_total_deleted_contract_count(session)


def delete_contract(contract_id: int, *, actor: str | None = None) -> None:
    """Soft-delete a contract."""
    with get_uow().transaction(actor=actor) as session:
        contracts.delete_contract(session, contract_id)


def restore_contract(contract_id: int, *, actor: str | None = None) -> None:
    """Restore a soft-deleted contract."""
    with get_uow().transaction(actor=actor) as session:
        contracts.restore_contract(session, contract_id)


def purge_contract(contract_id: int, *, actor: str | None = None) -> None:
    """Permanently delete a contract."""
    with get_uow().transaction(actor=actor) as session:
        contracts.purge_contract(session, contract_id)


def print_contract(contract_id: int, *, actor: str | None = None) -> None:
    """Mark a contract as printed."""
    with get_uow().transaction(actor=actor) as session:
        contracts.print_contract(session, contract_id)


def activate_contract(contract_id: int, *, actor: str | None = None) -> None:
    """Transition a contract to the 'signed' status and update related entities."""
    with get_uow().transaction(actor=actor) as session:
        contract = contracts_read.get_contract_by_id(session, contract_id)
        if not contract:
            raise NotFoundError("Contract not found")
        contracts.activate_contract(
            session,
            contract_id,
            contract.contract_type,
            contract.client_id,
            contract.listing_id,
        )
        mark_client_dirty(session, contract.client_id)
        _mark_listing_wilaya_dirty(session, contract.listing_id)


def cancel_contract(
    contract_id: int,
    *,
    restore_status: bool = True,
    actor: str | None = None,
) -> None:
    """Cancel a contract and optionally restore the original statuses of the client/listing."""
    with get_uow().transaction(actor=actor) as session:
        contract = contracts_read.get_contract_by_id(session, contract_id)
        if not contract:
            raise NotFoundError("Contract not found")
        was_signed = contract.status == "signed"
        contracts.cancel_contract(
            session,
            contract_id,
            contract.client_id,
            contract.listing_id,
            was_signed,
            restore_status,
        )
        mark_client_dirty(session, contract.client_id)
        _mark_listing_wilaya_dirty(session, contract.listing_id)


def get_contract_by_id(contract_id: int, *, include_deleted: bool = False) -> Contract | None:
    """Get a single contract by ID."""
    with get_uow().session() as session:
        return contracts_read.get_contract_by_id(session, contract_id, include_deleted)


def _normalize_contract_data(
    input_data: Mapping[str, Any], *, existing: Contract | None = None
) -> dict[str, Any]:
    from .ale_helper import normalize_ale_fields

    if existing:
        processed = existing.to_dict()
    else:
        processed = {}

    processed.update(input_data)

    contract_type = str(processed.get("contract_type") or "").strip().lower()
    if contract_type:
        if contract_type not in CONTRACT_TYPES:
            raise ValueError("Contract type must be buy or rent")
        processed["contract_type"] = contract_type
    elif existing is None:
        raise ValueError("Contract type must be buy or rent")

    # Dates
    start_date = processed.get("start_date")
    end_date = processed.get("end_date")
    if start_date:
        processed["start_date"] = _normalize_date_value(start_date)
    if end_date:
        processed["end_date"] = _normalize_date_value(end_date)
    if contract_type != "rent":
        processed["end_date"] = None

    normalize_ale_fields(
        processed,
        CRM_CONTRACT_ALE_POLICIES,
        changed_fields=set(input_data.keys()),
    )

    return processed


def _reject_lifecycle_or_identity_update(input_data: Mapping[str, Any], existing: Contract) -> None:
    """Keep generic detail edits from bypassing lifecycle/identity actions."""
    for field in DETAIL_UPDATE_IMMUTABLE_FIELDS:
        if field not in input_data:
            continue
        incoming = str(input_data.get(field) or "").strip().lower()
        current = str(getattr(existing, field) or "").strip().lower()
        if incoming and incoming != current:
            raise ConflictError(f"Contract {field} cannot be changed")
    if "status" in input_data:
        incoming_status = str(input_data.get("status") or "").strip()
        if incoming_status and incoming_status != str(existing.status or ""):
            raise ConflictError("Use the dedicated contract lifecycle action")


def _mark_listing_wilaya_dirty(session: DbSession, listing_id: int) -> None:
    rows = session.execute(
        """
        SELECT DISTINCT wilaya_id
        FROM offers
        WHERE listing_id = %s
          AND wilaya_id IS NOT NULL AND wilaya_id <> 0
        """,
        (listing_id,),
    ).fetchall()
    for row in rows:
        wilaya_id = row.get("wilaya_id")
        if isinstance(wilaya_id, int):
            mark_clients_in_wilaya_dirty(session, wilaya_id)


def _normalize_date_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None
