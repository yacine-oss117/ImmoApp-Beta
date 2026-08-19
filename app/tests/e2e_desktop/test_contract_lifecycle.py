from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest

from app.tests.e2e_desktop import backend
from app.tests.e2e_desktop.pages import ContractsPage, MatchPage, login_to_main_window
from app.tests.e2e_desktop.runtime import DesktopSession
from app.tests.e2e_desktop.ui import wait_for

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_nightly, pytest.mark.nightly]


def _phone(prefix: str) -> str:
    return f"{prefix}{backend.numeric_suffix(6)}"


def _as_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return int(float(str(value)))


def _single_contract_by_notes(items: list[dict[str, object]], notes: str) -> dict[str, object]:
    matches = [item for item in items if str(item.get("notes") or "") == notes]
    assert len(matches) == 1
    return matches[0]


def _contract_status(
    *,
    base_url: str,
    user: backend.DesktopUser,
    contract_id: int,
    expected_status: str,
) -> dict[str, object] | None:
    contract = backend.api_fetch_contract(
        base_url=base_url,
        user=user,
        contract_id=contract_id,
    )
    if contract is not None and str(contract.get("status") or "") == expected_status:
        return contract
    return None


def test_contract_lifecycle_from_match_create_edit_cancel_delete_via_desktop_ui(
    e2e_base_url: str,
    make_backend_user: Callable[..., backend.DesktopUser],
    launch_native_desktop: Callable[..., DesktopSession],
) -> None:
    user = make_backend_user(prefix="e2e_contract_lifecycle")
    suffix = uuid.uuid4().hex[:6]
    client_name = f"Contract Client {suffix}"
    listing_owner = f"Contract Listing {suffix}"
    client_phone = _phone("213684")
    listing_phone = _phone("213784")
    created_terms = f"contract terms {uuid.uuid4().hex[:8]}"
    created_notes = f"contract notes {uuid.uuid4().hex[:8]}"
    edited_terms = f"contract edited terms {uuid.uuid4().hex[:8]}"
    edited_notes = f"contract edited notes {uuid.uuid4().hex[:8]}"

    client_id = backend.api_create_client(
        base_url=e2e_base_url,
        user=user,
        family_name=client_name,
        phone=client_phone,
        remarks="desktop e2e contract lifecycle client",
    )
    backend.api_create_demande(
        base_url=e2e_base_url,
        user=user,
        client_id=client_id,
        payload={
            "action": "rent",
            "action_id": 2,
            "type": "apartment",
            "type_id": 1,
            "wilaya": "Algiers",
            "wilaya_id": 16,
            "locations": "Hydra",
            "budget_min": 100_000,
            "budget_max": 250_000,
            "surface_min": 60,
            "surface_max": 140,
            "beds_min": 2,
            "floor_min": 0,
            "floor_max": 8,
            "elevator": 1,
            "accessibility_required": 1,
            "remarks": "desktop e2e contract lifecycle demande",
        },
    )
    listing_id = backend.api_create_listing(
        base_url=e2e_base_url,
        user=user,
        family_name=listing_owner,
        phone=listing_phone,
        remarks="desktop e2e contract lifecycle listing",
    )
    backend.api_create_offer(
        base_url=e2e_base_url,
        user=user,
        listing_id=listing_id,
        payload={
            "action": "rent",
            "action_id": 2,
            "type": "apartment",
            "type_id": 1,
            "status": "available",
            "wilaya": "Algiers",
            "wilaya_id": 16,
            "location": "Hydra",
            "beds": 3,
            "surface": 95,
            "budget": 175_000,
            "floor": 2,
            "elevator": 1,
            "accessibility_supported": 1,
            "remarks": "desktop e2e contract lifecycle offer",
        },
    )

    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )

    main.select_tab("matches")
    match_page = MatchPage(main)
    match_page.run_for_client(client_name)
    wait_for(
        "contract lifecycle matched listing backend total",
        lambda: (
            total
            if (
                total := backend.api_client_match_total(
                    base_url=e2e_base_url,
                    user=user,
                    client_id=client_id,
                )
            )
            > 0
            else None
        ),
        timeout=60.0,
    )

    contract_dialog = match_page.open_create_contract_for_visible_listing(
        listing_owner,
        listing_id=listing_id,
    )
    contract_dialog.fill_and_save(
        amount=175_000,
        deposit=50_000,
        start_date="2026-06-01",
        end_date="2027-06-01",
        terms=created_terms,
        notes=created_notes,
    )

    created = wait_for(
        "contract persisted after desktop create",
        lambda: _single_contract_by_notes(
            backend.api_fetch_contracts(base_url=e2e_base_url, user=user),
            created_notes,
        ),
        timeout=30.0,
    )
    contract_id = _as_int(created.get("id"))
    assert contract_id > 0
    assert _as_int(created.get("client_id")) == client_id
    assert _as_int(created.get("listing_id")) == listing_id
    assert str(created.get("contract_type") or "") == "rent"
    assert str(created.get("status") or "") == "draft"
    assert _as_int(created.get("amount")) == 175_000
    assert _as_int(created.get("deposit")) == 50_000
    assert str(created.get("start_date") or "") == "2026-06-01"
    assert str(created.get("end_date") or "") == "2027-06-01"
    assert str(created.get("terms") or "") == created_terms

    contracts = ContractsPage.open(main, session)
    contracts.wait_for_contract(
        contract_id=contract_id,
        expected_text="175 000",
        status_text="Draft",
    )

    contracts.edit_details(
        contract_id,
        amount=185_000,
        deposit=60_000,
        start_date="2026-07-01",
        end_date="2027-07-01",
        terms=edited_terms,
        notes=edited_notes,
    )
    edited = wait_for(
        "contract persisted after desktop edit",
        lambda: (
            contract
            if (
                contract := backend.api_fetch_contract(
                    base_url=e2e_base_url,
                    user=user,
                    contract_id=contract_id,
                )
            )
            and str(contract.get("notes") or "") == edited_notes
            else None
        ),
        timeout=30.0,
    )
    assert _as_int(edited.get("amount")) == 185_000
    assert _as_int(edited.get("deposit")) == 60_000
    assert str(edited.get("start_date") or "") == "2026-07-01"
    assert str(edited.get("end_date") or "") == "2027-07-01"
    assert str(edited.get("terms") or "") == edited_terms
    contracts.wait_for_contract(
        contract_id=contract_id,
        expected_text="185 000",
        status_text="Draft",
    )

    contracts.print_contract(contract_id)
    wait_for(
        "contract pending signature after desktop print",
        lambda: _contract_status(
            base_url=e2e_base_url,
            user=user,
            contract_id=contract_id,
            expected_status="pending_signature",
        ),
        timeout=30.0,
    )
    contracts.wait_for_contract(
        contract_id=contract_id,
        expected_text="185 000",
        status_text="Pending signature",
    )

    contracts.sign_contract(contract_id)
    wait_for(
        "contract signed after desktop sign",
        lambda: _contract_status(
            base_url=e2e_base_url,
            user=user,
            contract_id=contract_id,
            expected_status="signed",
        ),
        timeout=30.0,
    )
    signed_client = backend.api_fetch_client_by_id(
        base_url=e2e_base_url,
        user=user,
        client_id=client_id,
    )
    signed_listing = backend.api_fetch_listing_by_id(
        base_url=e2e_base_url,
        user=user,
        listing_id=listing_id,
    )
    assert signed_client is not None
    assert signed_listing is not None
    assert str(signed_client.get("status") or "") == "archived_rented"
    assert str(signed_listing.get("status") or "") == "rented"
    contracts.wait_for_contract(
        contract_id=contract_id,
        expected_text="185 000",
        status_text="Signed",
    )

    contracts.cancel_contract(contract_id)
    wait_for(
        "contract cancelled after desktop cancel",
        lambda: _contract_status(
            base_url=e2e_base_url,
            user=user,
            contract_id=contract_id,
            expected_status="cancelled",
        ),
        timeout=30.0,
    )
    restored_client = backend.api_fetch_client_by_id(
        base_url=e2e_base_url,
        user=user,
        client_id=client_id,
    )
    restored_listing = backend.api_fetch_listing_by_id(
        base_url=e2e_base_url,
        user=user,
        listing_id=listing_id,
    )
    assert restored_client is not None
    assert restored_listing is not None
    assert str(restored_client.get("status") or "") == "active"
    assert str(restored_listing.get("status") or "") == "available"
    contracts.wait_for_contract(
        contract_id=contract_id,
        expected_text="185 000",
        status_text="Cancelled",
    )

    contracts.delete_contract(contract_id)
    wait_for(
        "contract absent from active list after desktop delete",
        lambda: (
            True
            if all(
                _as_int(item.get("id")) != contract_id
                for item in backend.api_fetch_contracts(base_url=e2e_base_url, user=user)
            )
            else None
        ),
        timeout=30.0,
    )
    contracts.wait_for_contract_absent(contract_id=contract_id)
    deleted = wait_for(
        "contract present in deleted backend truth",
        lambda: next(
            (
                item
                for item in backend.api_fetch_deleted_contracts(
                    base_url=e2e_base_url,
                    user=user,
                )
                if _as_int(item.get("id")) == contract_id
            ),
            None,
        ),
        timeout=30.0,
    )
    assert str(deleted.get("status") or "") == "cancelled"
    assert str(deleted.get("deleted_at") or "")

    deleted_detail = backend.api_fetch_contract(
        base_url=e2e_base_url,
        user=user,
        contract_id=contract_id,
    )
    assert deleted_detail is not None
    assert str(deleted_detail.get("deleted_at") or "")
