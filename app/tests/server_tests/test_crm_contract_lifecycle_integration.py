from __future__ import annotations

# ruff: noqa: E402, I001

import uuid
from typing import cast

import pytest

pytest.importorskip("psycopg", reason="CRM lifecycle integration tests require Postgres")

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    create_agency,
    create_manager_user,
    ensure_django,
)

ensure_django()

from core.data import (
    client_repo_write,
    listing_repo_write,
    lookup_tables,
    offer_repo_write,
)  # noqa: E402
from core.data.types import OfferInput  # noqa: E402
from core.data.errors import ConflictError  # noqa: E402
from server.pg.schema import ensure_schema  # noqa: E402
from server.pg.uow import get_uow, use_security_context  # noqa: E402
from server.services import crm  # noqa: E402


def test_crm_contract_lifecycle_transitions_are_consistent() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    phone_digits = str(int(suffix, 16))[-6:].rjust(6, "0")

    agency_id = 0
    user_id = 0
    client_id = 0
    listing_id = 0
    offer_id = 0
    contract_ids: list[int] = []
    contract_id = 0
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"CRML{suffix}", f"CRM Lifecycle {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"crm_lf_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().transaction(actor="test_crm_seed") as session:
                type_id = lookup_tables.get_property_type_id(session, "apartment")
                action_id = lookup_tables.get_action_id(session, "rent")
                wilaya_id = lookup_tables.get_wilaya_id(session, "16")
                if type_id is None or action_id is None or wilaya_id is None:
                    raise RuntimeError(
                        "lookup seed data missing for CRM lifecycle integration test"
                    )
                client_id = client_repo_write.upsert_client(
                    session,
                    {
                        "family_name": f"CRM Client {suffix}",
                        "phone": f"0555{phone_digits}",
                        "status": "active",
                    },
                )
                listing_id = listing_repo_write.upsert_listing(
                    session,
                    {
                        "family_name": f"CRM Listing {suffix}",
                        "phone": f"0666{phone_digits}",
                        "status": "available",
                    },
                )
                offer_id = offer_repo_write.create_offer(
                    session,
                    int(listing_id),
                    cast(
                        OfferInput,
                        {
                            "type": "apartment",
                            "type_id": int(type_id),
                            "action": "rent",
                            "action_id": int(action_id),
                            "status": "available",
                            "wilaya": "Alger",
                            "wilaya_id": int(wilaya_id),
                            "location": "Hydra",
                            "beds": 3,
                            "surface": 120,
                            "budget": 150000,
                            "furnished": "no",
                            "floor": 2,
                            "elevator": True,
                            "accessibility_supported": False,
                            "remarks": "crm lifecycle offer",
                        },
                    ),
                )

            contract_id = crm.create_contract(
                {
                    "client_id": int(client_id),
                    "listing_id": int(listing_id),
                    "contract_type": "rent",
                    "status": "draft",
                    "amount": 150000,
                    "deposit": 30000,
                    "terms": "standard",
                    "notes": "lifecycle test",
                },
                actor="test_crm_create",
            )
            contract_ids.append(int(contract_id))

            with pytest.raises(ValueError, match="draft status"):
                crm.create_contract(
                    {
                        "client_id": int(client_id),
                        "listing_id": int(listing_id),
                        "contract_type": "rent",
                        "status": "signed",
                        "amount": 150000,
                    },
                    actor="test_crm_create_bad_status",
                )

            with pytest.raises(ConflictError, match="pending-signature"):
                crm.activate_contract(int(contract_id), actor="test_crm_activate_too_early")

            current = crm.get_contract_by_id(int(contract_id), include_deleted=False)
            assert current is not None
            with pytest.raises(ConflictError, match="dedicated contract lifecycle"):
                crm.update_contract(
                    int(contract_id),
                    {"row_version": current.row_version, "status": "signed"},
                    actor="test_crm_update_status_bypass",
                )

            crm.print_contract(int(contract_id), actor="test_crm_print")
            printed = crm.get_contract_by_id(int(contract_id), include_deleted=False)
            assert printed is not None
            assert printed.status == "pending_signature"

            with pytest.raises(ConflictError, match="draft contracts"):
                crm.print_contract(int(contract_id), actor="test_crm_print_again")

            crm.activate_contract(int(contract_id), actor="test_crm_activate")
            signed = crm.get_contract_by_id(int(contract_id), include_deleted=False)
            assert signed is not None
            assert signed.status == "signed"

            with pytest.raises(ConflictError, match="draft or cancelled"):
                crm.delete_contract(int(contract_id), actor="test_crm_delete_signed")

            with get_uow().session() as session:
                row = session.execute(
                    "SELECT status FROM clients WHERE id = %s",
                    (int(client_id),),
                ).fetchone()
                assert row is not None
                assert str(row.get("status")) == "archived_rented"
                row = session.execute(
                    "SELECT status FROM listings WHERE id = %s",
                    (int(listing_id),),
                ).fetchone()
                assert row is not None
                assert str(row.get("status")) == "rented"

            crm.cancel_contract(int(contract_id), restore_status=True, actor="test_crm_cancel")
            cancelled = crm.get_contract_by_id(int(contract_id), include_deleted=False)
            assert cancelled is not None
            assert cancelled.status == "cancelled"

            with pytest.raises(ConflictError, match="pending-signature"):
                crm.activate_contract(int(contract_id), actor="test_crm_activate_cancelled")

            with get_uow().session() as session:
                row = session.execute(
                    "SELECT status FROM clients WHERE id = %s",
                    (int(client_id),),
                ).fetchone()
                assert row is not None
                assert str(row.get("status")) == "active"
                row = session.execute(
                    "SELECT status FROM listings WHERE id = %s",
                    (int(listing_id),),
                ).fetchone()
                assert row is not None
                assert str(row.get("status")) == "available"

            buy_contract_id = crm.create_contract(
                {
                    "client_id": int(client_id),
                    "listing_id": int(listing_id),
                    "contract_type": "buy",
                    "status": "draft",
                    "start_date": "2026-06-01",
                    "end_date": "2027-06-01",
                    "amount": 22_000_000,
                    "deposit": 0,
                    "terms": "buy contract",
                    "notes": "buy lifecycle test",
                },
                actor="test_crm_create_buy",
            )
            contract_ids.append(int(buy_contract_id))
            buy_contract = crm.get_contract_by_id(int(buy_contract_id), include_deleted=False)
            assert buy_contract is not None
            assert buy_contract.contract_type == "buy"
            assert buy_contract.end_date == ""

            crm.update_contract(
                int(buy_contract_id),
                {
                    "row_version": buy_contract.row_version,
                    "end_date": "2028-01-01",
                    "notes": "buy updated without end date",
                },
                actor="test_crm_update_buy",
            )
            updated_buy = crm.get_contract_by_id(int(buy_contract_id), include_deleted=False)
            assert updated_buy is not None
            assert updated_buy.end_date == ""
            assert updated_buy.notes == "buy updated without end date"
    finally:
        for cleanup_contract_id in contract_ids:
            conn.execute("DELETE FROM contracts WHERE id = %s", (cleanup_contract_id,))
        if agency_id:
            conn.execute("DELETE FROM demande_locations WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM offer_locations WHERE agency_id = %s", (agency_id,))
        if offer_id:
            conn.execute("DELETE FROM offers WHERE id = %s", (offer_id,))
        if listing_id:
            conn.execute("DELETE FROM listings WHERE id = %s", (listing_id,))
        if client_id:
            conn.execute("DELETE FROM clients WHERE id = %s", (client_id,))
        if agency_id:
            conn.execute("DELETE FROM match_counts_cache WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM match_rebuild_state WHERE agency_id = %s", (agency_id,))
        if user_id:
            conn.execute(
                "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
                (user_id,),
            )
            conn.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        if agency_id:
            conn.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        conn.commit()
        conn.close()
