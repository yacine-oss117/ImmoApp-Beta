"""
Write and lifecycle operations for CRM contracts.
"""

from __future__ import annotations

import logging

from core.data.errors import ConflictError, NotFoundError
from core.data.types import ContractInput
from core.matcher.ports.db import DbSession
from core.models_cast import as_int
from core.utils.time import utc_now_iso

logger = logging.getLogger(__name__)

CONTRACT_STATUSES = ("draft", "pending_signature", "signed", "completed", "cancelled")


def create_contract(session: DbSession, data: ContractInput) -> int:
    """Create a new contract. Returns contract ID."""
    now = utc_now_iso()
    session.execute(
        """
        INSERT INTO contracts
        (agency_id, client_id, listing_id, contract_type, status, start_date, end_date,
         amount, deposit, terms, notes, 
         amount_enc, deposit_enc, terms_enc, notes_enc,
         created_at, updated_at)
        SELECT
            c.agency_id,
            c.id,
            l.id,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        FROM clients c
        JOIN listings l ON l.id = %s AND l.deleted_at IS NULL
        WHERE c.id = %s
          AND c.deleted_at IS NULL
          AND c.agency_id = l.agency_id
        RETURNING id
    """,
        (
            data["contract_type"],
            data.get("status", "draft"),
            data.get("start_date"),
            data.get("end_date"),
            data.get("amount", 0.0),
            data.get("deposit", 0.0),
            data.get("terms", ""),
            data.get("notes", ""),
            data.get("amount_enc", ""),
            data.get("deposit_enc", ""),
            data.get("terms_enc", ""),
            data.get("notes_enc", ""),
            now,
            now,
            data["listing_id"],
            data["client_id"],
        ),
    )
    contract_id = session.lastrowid
    if not contract_id:
        raise ValueError("client and listing must belong to the same active agency")
    return int(contract_id or 0)


def update_contract(session: DbSession, contract_id: int, data: ContractInput) -> None:
    """Update contract information."""
    row_version = as_int(data.get("row_version"), default=0)
    if row_version <= 0:
        raise ValueError("row_version is required for contract updates")
    session.execute(
        """
        UPDATE contracts
        SET status = %s, amount = %s, deposit = %s, terms = %s, notes = %s,
            amount_enc = %s, deposit_enc = %s, terms_enc = %s, notes_enc = %s,
            start_date = %s, end_date = %s, updated_at = %s,
            row_version = row_version + 1
        WHERE id = %s AND deleted_at IS NULL AND row_version = %s
    """,
        (
            data.get("status"),
            data.get("amount"),
            data.get("deposit"),
            data.get("terms"),
            data.get("notes"),
            data.get("amount_enc"),
            data.get("deposit_enc"),
            data.get("terms_enc"),
            data.get("notes_enc"),
            data.get("start_date"),
            data.get("end_date"),
            utc_now_iso(),
            contract_id,
            row_version,
        ),
    )
    if session.rowcount == 0:
        row = session.execute("SELECT * FROM contracts WHERE id = %s", (contract_id,)).fetchone()
        if row and row.get("deleted_at") is None:
            raise ConflictError("Contract was updated by another user.")
        raise NotFoundError("Contract not found")


def delete_contract(session: DbSession, contract_id: int) -> None:
    now = utc_now_iso()
    session.execute(
        """
        UPDATE contracts
        SET deleted_at = %s, updated_at = %s, row_version = row_version + 1
        WHERE id = %s
          AND deleted_at IS NULL
          AND status IN ('draft', 'cancelled')
        """,
        (now, now, contract_id),
    )
    if session.rowcount == 0:
        _raise_contract_transition_failure(
            session,
            contract_id,
            "Only draft or cancelled contracts can be deleted",
        )


def print_contract(session: DbSession, contract_id: int) -> None:
    session.execute(
        """
        UPDATE contracts
        SET status = %s, updated_at = %s, row_version = row_version + 1
        WHERE id = %s
          AND deleted_at IS NULL
          AND status = 'draft'
        """,
        ("pending_signature", utc_now_iso(), contract_id),
    )
    if session.rowcount == 0:
        _raise_contract_transition_failure(
            session,
            contract_id,
            "Only draft contracts can be marked pending signature",
        )


def activate_contract(
    session: DbSession, contract_id: int, contract_type: str, client_id: int, listing_id: int
) -> None:
    session.execute(
        """
        UPDATE contracts
        SET status = %s, updated_at = %s, row_version = row_version + 1
        WHERE id = %s
          AND deleted_at IS NULL
          AND status = 'pending_signature'
        """,
        ("signed", utc_now_iso(), contract_id),
    )
    if session.rowcount == 0:
        _raise_contract_transition_failure(
            session,
            contract_id,
            "Only pending-signature contracts can be signed",
        )
    archive_status = "archived_rented" if contract_type == "rent" else "archived_sold"
    session.execute(
        "UPDATE clients SET status = %s, row_version = row_version + 1 WHERE id = %s AND deleted_at IS NULL",
        (archive_status, client_id),
    )
    listing_status = "rented" if contract_type == "rent" else "sold"
    session.execute(
        "UPDATE listings SET status = %s, row_version = row_version + 1 WHERE id = %s AND deleted_at IS NULL",
        (listing_status, listing_id),
    )


def cancel_contract(
    session: DbSession,
    contract_id: int,
    client_id: int,
    listing_id: int,
    was_signed: bool = False,
    restore_status: bool = True,
) -> None:
    session.execute(
        """
        UPDATE contracts
        SET status = %s, updated_at = %s, row_version = row_version + 1
        WHERE id = %s
          AND deleted_at IS NULL
          AND status IN ('draft', 'pending_signature', 'signed')
        """,
        ("cancelled", utc_now_iso(), contract_id),
    )
    if session.rowcount == 0:
        _raise_contract_transition_failure(
            session,
            contract_id,
            "Only active contracts can be cancelled",
        )
    if was_signed and restore_status:
        session.execute(
            "UPDATE clients SET status = %s, row_version = row_version + 1 WHERE id = %s AND deleted_at IS NULL",
            ("active", client_id),
        )
        session.execute(
            "UPDATE listings SET status = %s, row_version = row_version + 1 WHERE id = %s AND deleted_at IS NULL",
            ("available", listing_id),
        )


def restore_contract(session: DbSession, contract_id: int) -> None:
    session.execute(
        "UPDATE contracts SET deleted_at = NULL, updated_at = %s, row_version = row_version + 1 WHERE id = %s",
        (utc_now_iso(), contract_id),
    )


def purge_contract(session: DbSession, contract_id: int) -> None:
    session.execute("DELETE FROM contracts WHERE id = %s", (contract_id,))


def _raise_contract_transition_failure(
    session: DbSession,
    contract_id: int,
    message: str,
) -> None:
    row = session.execute(
        "SELECT deleted_at FROM contracts WHERE id = %s",
        (contract_id,),
    ).fetchone()
    if row is None or row.get("deleted_at") is not None:
        raise NotFoundError("Contract not found")
    raise ConflictError(message)
