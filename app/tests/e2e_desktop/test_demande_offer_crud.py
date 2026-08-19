from __future__ import annotations

import uuid

import pytest

from app.tests.e2e_desktop import backend
from app.tests.e2e_desktop.pages import ClientsPage, ListingsPage, login_to_main_window
from app.tests.e2e_desktop.ui import wait_for

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_smoke]


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


def _single_demande_by_remarks(items: list[dict[str, object]], remarks: str) -> dict[str, object]:
    matches = [item for item in items if str(item.get("remarks") or "") == remarks]
    assert len(matches) == 1
    return matches[0]


def _single_offer_by_remarks(items: list[dict[str, object]], remarks: str) -> dict[str, object]:
    matches = [item for item in items if str(item.get("remarks") or "") == remarks]
    assert len(matches) == 1
    return matches[0]


def _open_seeded_client(clients: ClientsPage, *, phone: str, client_name: str) -> None:
    clients.select_existing(
        search_value="",
        expected_name=phone,
        editor_expected_name=client_name,
    )
    wait_for(
        "seeded client loaded",
        lambda: clients.current_phone() if clients.current_phone() == phone else None,
        timeout=20.0,
    )


def _open_seeded_listing(listings: ListingsPage, *, phone: str, owner_name: str) -> None:
    listings.select_existing(
        search_value="",
        expected_name=phone,
        editor_expected_name=owner_name,
    )
    wait_for(
        "seeded listing loaded",
        lambda: listings.current_phone() if listings.current_phone() == phone else None,
        timeout=20.0,
    )


def _create_prerequisite_client_via_ui(
    clients: ClientsPage,
    *,
    base_url: str,
    user: backend.DesktopUser,
    phone: str,
    client_name: str,
) -> int:
    clients.create_client(family_name=client_name, phone=phone)
    row = wait_for(
        "created prerequisite client visible through backend",
        lambda: backend.api_find_client_row(
            base_url=base_url,
            user=user,
            search=client_name,
            family_name=client_name,
            phone=phone,
        ),
        timeout=20.0,
    )
    client_id = _as_int(row.get("id"))
    assert client_id > 0
    _open_seeded_client(clients, phone=phone, client_name=client_name)
    return client_id


def _create_prerequisite_listing_via_ui(
    listings: ListingsPage,
    *,
    base_url: str,
    user: backend.DesktopUser,
    phone: str,
    owner_name: str,
) -> int:
    listings.create_listing(owner_name=owner_name, phone=phone, remarks="desktop e2e offer parent")
    row = wait_for(
        "created prerequisite listing visible through backend",
        lambda: backend.api_find_listing_row(
            base_url=base_url,
            user=user,
            search=owner_name,
            family_name=owner_name,
            phone=phone,
        ),
        timeout=20.0,
    )
    listing_id = _as_int(row.get("id"))
    assert listing_id > 0
    _open_seeded_listing(listings, phone=phone, owner_name=owner_name)
    return listing_id


def test_demande_create_edit_delete_via_desktop_ui(
    e2e_base_url: str,
    make_backend_user,
    launch_native_desktop,
) -> None:
    user = make_backend_user(prefix="e2e_demande_crud")
    client_name = f"Demande CRUD {uuid.uuid4().hex[:6]}"
    phone = _phone("213681")
    created_remarks = f"demande create {uuid.uuid4().hex[:8]}"
    edited_remarks = f"demande edit {uuid.uuid4().hex[:8]}"

    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )
    main.select_tab("clients")
    clients = ClientsPage(main, session)
    client_id = _create_prerequisite_client_via_ui(
        clients,
        base_url=e2e_base_url,
        user=user,
        phone=phone,
        client_name=client_name,
    )
    clients.add_demande(
        type_label="Apartment",
        action_label="To Buy",
        wilaya="Algiers",
        location="Hydra",
        beds_min=2,
        surface_min=60,
        surface_max=120,
        budget_min=100,
        budget_max=300,
        furnished_label="Any",
        floor_min=0,
        floor_max=8,
        elevator=True,
        accessibility_required=True,
        tags="parking",
        remarks=created_remarks,
    )
    clients.save_current(expected_text=client_name)
    clients.search("")
    clients.wait_for_tree_text("Apartment")
    clients.wait_for_tree_text("Buy")

    created = wait_for(
        "created demande persisted",
        lambda: _single_demande_by_remarks(
            backend.api_fetch_client_demandes(
                base_url=e2e_base_url,
                user=user,
                client_id=client_id,
            ),
            created_remarks,
        ),
        timeout=20.0,
    )
    demande_id = _as_int(created["id"])
    assert str(created["type"]) == "apartment"
    assert str(created["action"]) == "buy"
    assert str(created["locations"]) == "Hydra, Algiers - 16"
    assert _as_int(created["beds_min"]) == 2
    assert bool(created["elevator"]) is True
    assert bool(created["accessibility_required"]) is True

    _open_seeded_client(clients, phone=phone, client_name=client_name)
    clients.fill_first_demande(
        budget_min=150,
        remarks=edited_remarks,
    )
    clients.save_current(expected_text=client_name)
    clients.search("")

    edited = wait_for(
        "edited demande persisted",
        lambda: backend.api_fetch_demande(
            base_url=e2e_base_url,
            user=user,
            demande_id=demande_id,
        ),
        timeout=20.0,
    )
    assert edited is not None
    assert str(edited["type"]) == "apartment"
    assert _as_int(edited["budget_min"]) == 150
    assert _as_int(edited["budget_min"]) != _as_int(created["budget_min"])
    assert str(edited["locations"]) == str(created["locations"])
    assert str(edited["remarks"]) == edited_remarks

    _open_seeded_client(clients, phone=phone, client_name=client_name)
    clients.delete_first_demande_panel()
    clients.save_current(expected_text=client_name)
    clients.search("")
    clients.wait_for_tree_text_absent("Rent")

    wait_for(
        "active demande removed",
        lambda: (
            True
            if not backend.api_fetch_client_demandes(
                base_url=e2e_base_url,
                user=user,
                client_id=client_id,
            )
            else None
        ),
        timeout=20.0,
    )
    assert (
        backend.api_fetch_demande(
            base_url=e2e_base_url,
            user=user,
            demande_id=demande_id,
        )
        is None
    )
    deleted = backend.api_fetch_demande(
        base_url=e2e_base_url,
        user=user,
        demande_id=demande_id,
        include_deleted=True,
    )
    assert deleted is not None
    assert str(deleted["remarks"]) == edited_remarks
    assert str(deleted.get("deleted_at") or "")


def test_offer_create_edit_delete_via_desktop_ui(
    e2e_base_url: str,
    make_backend_user,
    launch_native_desktop,
) -> None:
    user = make_backend_user(prefix="e2e_offer_crud")
    owner_name = f"Offer CRUD {uuid.uuid4().hex[:6]}"
    phone = _phone("213781")
    created_remarks = f"offer create {uuid.uuid4().hex[:8]}"
    edited_remarks = f"offer edit {uuid.uuid4().hex[:8]}"

    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )
    main.select_tab("listings")
    listings = ListingsPage(main, session)
    listing_id = _create_prerequisite_listing_via_ui(
        listings,
        base_url=e2e_base_url,
        user=user,
        phone=phone,
        owner_name=owner_name,
    )
    listings.add_offer(
        type_label="Apartment",
        action_label="For Sale",
        wilaya="Algiers",
        location="Hydra",
        beds=3,
        surface=90,
        budget=250,
        furnished_label="Yes",
        floor=2,
        elevator=True,
        accessibility_supported=True,
        price_negotiable=True,
        price_flex_pct=12,
        link="",
        latitude="36.7525",
        longitude="3.042",
        remarks=created_remarks,
    )
    listings.save_current(expected_text=owner_name)
    listings.wait_for_tree_text("Apartment")
    listings.wait_for_tree_text("Sell")

    created = wait_for(
        "created offer persisted",
        lambda: _single_offer_by_remarks(
            backend.api_fetch_listing_offers(
                base_url=e2e_base_url,
                user=user,
                listing_id=listing_id,
            ),
            created_remarks,
        ),
        timeout=20.0,
    )
    offer_id = _as_int(created["id"])
    assert str(created["type"]) == "apartment"
    assert str(created["action"]) == "sell"
    assert str(created["location"]) == "Hydra, Algiers - 16"
    assert _as_int(created["beds"]) == 3
    assert _as_int(created["floor"]) == 2
    assert bool(created["elevator"]) is True
    assert bool(created["accessibility_supported"]) is True
    assert bool(created["price_negotiable"]) is True
    assert _as_int(created["price_flex_pct"]) == 12

    _open_seeded_listing(listings, phone=phone, owner_name=owner_name)
    listings.fill_first_offer(
        budget=275,
        remarks=edited_remarks,
    )
    listings.save_current(expected_text=owner_name)
    listings.wait_for_tree_text("Apartment")

    edited = wait_for(
        "edited offer persisted",
        lambda: backend.api_fetch_offer(
            base_url=e2e_base_url,
            user=user,
            offer_id=offer_id,
        ),
        timeout=20.0,
    )
    assert edited is not None
    assert str(edited["type"]) == "apartment"
    assert _as_int(edited["budget"]) == 275
    assert _as_int(edited["budget"]) != _as_int(created["budget"])
    assert str(edited["remarks"]) == edited_remarks
    assert bool(edited["accessibility_supported"]) is True
    assert bool(edited["price_negotiable"]) is True
    assert _as_int(edited["price_flex_pct"]) == 12
    assert bool(edited["elevator"]) is True
    assert str(edited["location"]) == str(created["location"])
    assert str(edited["latitude"]) == str(created["latitude"])
    assert str(edited["longitude"]) == str(created["longitude"])

    _open_seeded_listing(listings, phone=phone, owner_name=owner_name)
    listings.delete_first_offer_panel()
    listings.save_current(expected_text=owner_name)
    listings.wait_for_tree_text_absent("Apartment")

    wait_for(
        "active offer removed",
        lambda: (
            True
            if not backend.api_fetch_listing_offers(
                base_url=e2e_base_url,
                user=user,
                listing_id=listing_id,
            )
            else None
        ),
        timeout=20.0,
    )
    assert (
        backend.api_fetch_offer(
            base_url=e2e_base_url,
            user=user,
            offer_id=offer_id,
        )
        is None
    )
    deleted = backend.api_fetch_offer(
        base_url=e2e_base_url,
        user=user,
        offer_id=offer_id,
        include_deleted=True,
    )
    assert deleted is not None
    assert str(deleted["remarks"]) == edited_remarks
    assert str(deleted.get("deleted_at") or "")
