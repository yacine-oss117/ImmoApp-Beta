from __future__ import annotations

import uuid

import pytest

from app.tests.e2e_desktop import backend
from app.tests.e2e_desktop.pages import (
    ClientsPage,
    ListingsPage,
    MatchPage,
    login_to_main_window,
)
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


def _single_by_remarks(items: list[dict[str, object]], remarks: str) -> dict[str, object]:
    matches = [item for item in items if str(item.get("remarks") or "") == remarks]
    assert len(matches) == 1
    return matches[0]


def _open_client(clients: ClientsPage, *, phone: str, client_name: str) -> None:
    clients.select_existing(
        search_value=client_name,
        expected_name=client_name,
        editor_expected_name=client_name,
    )
    wait_for(
        "match seed client loaded",
        lambda: clients.current_phone() if clients.current_phone() == phone else None,
        timeout=20.0,
    )


def _open_listing(listings: ListingsPage, *, phone: str, owner_name: str) -> None:
    listings.select_existing(
        search_value=owner_name,
        expected_name=owner_name,
        editor_expected_name=owner_name,
    )
    wait_for(
        "match seed listing loaded",
        lambda: listings.current_phone() if listings.current_phone() == phone else None,
        timeout=20.0,
    )


def _match_total_below(
    *,
    base_url: str,
    user: backend.DesktopUser,
    client_id: int,
    threshold: int,
) -> dict[str, int] | None:
    total = backend.api_client_match_total(base_url=base_url, user=user, client_id=client_id)
    if total < int(threshold):
        return {"total": total}
    return None


def test_demande_mutation_rebuilds_match_results_via_desktop_ui(
    e2e_base_url: str,
    make_backend_user,
    launch_native_desktop,
) -> None:
    user = make_backend_user(prefix="e2e_match_rebuild")
    client_name = f"Match Rebuild Client {uuid.uuid4().hex[:6]}"
    listing_owner = f"Match Rebuild Listing {uuid.uuid4().hex[:6]}"
    client_phone = _phone("213682")
    listing_phone = _phone("213782")
    demande_remarks = f"match demande {uuid.uuid4().hex[:8]}"
    offer_remarks = f"match offer {uuid.uuid4().hex[:8]}"

    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )

    main.select_tab("clients")
    clients = ClientsPage(main, session)
    clients.create_client(family_name=client_name, phone=client_phone)
    client_row = wait_for(
        "match seed client visible through backend",
        lambda: backend.api_find_client_row(
            base_url=e2e_base_url,
            user=user,
            search=client_name,
            family_name=client_name,
            phone=client_phone,
        ),
        timeout=20.0,
    )
    client_id = _as_int(client_row.get("id"))
    assert client_id > 0
    _open_client(clients, phone=client_phone, client_name=client_name)
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
        tags="match",
        remarks=demande_remarks,
    )
    clients.save_current(expected_text=client_name)
    demande = wait_for(
        "match seed demande persisted",
        lambda: _single_by_remarks(
            backend.api_fetch_client_demandes(
                base_url=e2e_base_url,
                user=user,
                client_id=client_id,
            ),
            demande_remarks,
        ),
        timeout=20.0,
    )
    demande_id = _as_int(demande["id"])
    assert demande_id > 0

    main.select_tab("listings")
    listings = ListingsPage(main, session)
    listings.create_listing(
        owner_name=listing_owner,
        phone=listing_phone,
        remarks="desktop e2e match listing",
    )
    listing_row = wait_for(
        "match seed listing visible through backend",
        lambda: backend.api_find_listing_row(
            base_url=e2e_base_url,
            user=user,
            search=listing_owner,
            family_name=listing_owner,
            phone=listing_phone,
        ),
        timeout=20.0,
    )
    listing_id = _as_int(listing_row.get("id"))
    assert listing_id > 0
    backend.api_create_offer(
        base_url=e2e_base_url,
        user=user,
        listing_id=listing_id,
        payload={
            "type": "apartment",
            "type_id": 1,
            "action": "sell",
            "action_id": 3,
            "status": "available",
            "wilaya": "Algiers",
            "wilaya_id": 16,
            "location": "Hydra, Algiers - 16",
            "beds": 3,
            "surface": 90,
            "budget": 250,
            "furnished": "yes",
            "floor": 2,
            "elevator": 1,
            "accessibility_supported": 1,
            "remarks": offer_remarks,
        },
    )
    offer = wait_for(
        "match seed offer persisted",
        lambda: _single_by_remarks(
            backend.api_fetch_listing_offers(
                base_url=e2e_base_url,
                user=user,
                listing_id=listing_id,
            ),
            offer_remarks,
        ),
        timeout=20.0,
    )
    offer_id = _as_int(offer["id"])
    assert offer_id > 0

    main.select_tab("matches")
    match_page = MatchPage(main)
    match_page.run_for_client(client_name)
    initial_total = wait_for(
        "seeded match API total",
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
    match_page.wait_for_visible_match_text(listing_owner)

    main.select_tab("clients")
    clients = ClientsPage(main, session)
    _open_client(clients, phone=client_phone, client_name=client_name)
    clients.fill_first_demande(
        budget_min=900,
        budget_max=1200,
        remarks="desktop e2e match incompatible",
    )
    clients.save_current(expected_text=client_name)
    incompatible_demande = wait_for(
        "incompatible demande mutation persisted",
        lambda: backend.api_fetch_demande(
            base_url=e2e_base_url,
            user=user,
            demande_id=demande_id,
        ),
        timeout=20.0,
    )
    assert incompatible_demande is not None
    assert str(incompatible_demande["type"]) == "apartment"
    assert _as_int(incompatible_demande["budget_min"]) == 900
    assert _as_int(incompatible_demande["budget_max"]) == 1200

    reduced_total = wait_for(
        "match API total reduced after incompatible demande edit",
        lambda: _match_total_below(
            base_url=e2e_base_url,
            user=user,
            client_id=client_id,
            threshold=int(initial_total),
        ),
        timeout=60.0,
    )["total"]
    assert int(reduced_total) == 0

    main.select_tab("matches")
    match_page = MatchPage(main)
    match_page.run_for_client(client_name)
    match_page.wait_for_no_matching_listings()

    main.select_tab("clients")
    clients = ClientsPage(main, session)
    _open_client(clients, phone=client_phone, client_name=client_name)
    clients.fill_first_demande(
        budget_min=100,
        budget_max=300,
        remarks="desktop e2e match compatible again",
    )
    clients.save_current(expected_text=client_name)
    compatible_demande = wait_for(
        "compatible demande mutation persisted",
        lambda: backend.api_fetch_demande(
            base_url=e2e_base_url,
            user=user,
            demande_id=demande_id,
        ),
        timeout=20.0,
    )
    assert compatible_demande is not None
    assert str(compatible_demande["type"]) == "apartment"
    assert _as_int(compatible_demande["type_id"]) == _as_int(demande["type_id"])
    assert _as_int(compatible_demande["budget_min"]) == _as_int(demande["budget_min"])
    assert _as_int(compatible_demande["budget_max"]) == _as_int(demande["budget_max"])

    restored_total = wait_for(
        "match API total restored after compatible demande edit",
        lambda: (
            total
            if (
                total := backend.api_client_match_total(
                    base_url=e2e_base_url,
                    user=user,
                    client_id=client_id,
                )
            )
            >= int(initial_total)
            else None
        ),
        timeout=60.0,
    )
    assert int(restored_total) >= int(initial_total)

    main.select_tab("matches")
    match_page = MatchPage(main)
    match_page.run_for_client(client_name)
    match_page.wait_for_visible_match_text(listing_owner)


def test_offer_mutation_rebuilds_match_results_via_desktop_ui(
    e2e_base_url: str,
    make_backend_user,
    launch_native_desktop,
) -> None:
    user = make_backend_user(prefix="e2e_offer_match_rebuild")
    client_name = f"Offer Match Client {uuid.uuid4().hex[:6]}"
    listing_owner = f"Offer Match Listing {uuid.uuid4().hex[:6]}"
    client_phone = _phone("213683")
    listing_phone = _phone("213783")
    demande_remarks = f"offer side demande {uuid.uuid4().hex[:8]}"
    offer_remarks = f"offer side offer {uuid.uuid4().hex[:8]}"

    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )

    main.select_tab("clients")
    clients = ClientsPage(main, session)
    clients.create_client(family_name=client_name, phone=client_phone)
    client_row = wait_for(
        "offer-side match seed client visible through backend",
        lambda: backend.api_find_client_row(
            base_url=e2e_base_url,
            user=user,
            search=client_name,
            family_name=client_name,
            phone=client_phone,
        ),
        timeout=20.0,
    )
    client_id = _as_int(client_row.get("id"))
    assert client_id > 0
    _open_client(clients, phone=client_phone, client_name=client_name)
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
        tags="offer-match",
        remarks=demande_remarks,
    )
    clients.save_current(expected_text=client_name)
    wait_for(
        "offer-side match seed demande persisted",
        lambda: _single_by_remarks(
            backend.api_fetch_client_demandes(
                base_url=e2e_base_url,
                user=user,
                client_id=client_id,
            ),
            demande_remarks,
        ),
        timeout=20.0,
    )

    main.select_tab("listings")
    listings = ListingsPage(main, session)
    listings.create_listing(
        owner_name=listing_owner,
        phone=listing_phone,
        remarks="desktop e2e offer-side match listing",
    )
    listing_row = wait_for(
        "offer-side match seed listing visible through backend",
        lambda: backend.api_find_listing_row(
            base_url=e2e_base_url,
            user=user,
            search=listing_owner,
            family_name=listing_owner,
            phone=listing_phone,
        ),
        timeout=20.0,
    )
    listing_id = _as_int(listing_row.get("id"))
    assert listing_id > 0
    _open_listing(listings, phone=listing_phone, owner_name=listing_owner)
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
        link="",
        latitude="36.7525",
        longitude="3.042",
        remarks=offer_remarks,
    )
    listings.save_current(expected_text=listing_owner)
    offer = wait_for(
        "offer-side match seed offer persisted",
        lambda: _single_by_remarks(
            backend.api_fetch_listing_offers(
                base_url=e2e_base_url,
                user=user,
                listing_id=listing_id,
            ),
            offer_remarks,
        ),
        timeout=20.0,
    )
    offer_id = _as_int(offer["id"])
    assert offer_id > 0

    main.select_tab("matches")
    match_page = MatchPage(main)
    match_page.run_for_client(client_name)
    initial_total = wait_for(
        "offer-side seeded match API total",
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
    match_page.wait_for_visible_match_text(listing_owner)

    main.select_tab("listings")
    listings = ListingsPage(main, session)
    _open_listing(listings, phone=listing_phone, owner_name=listing_owner)
    listings.fill_first_offer(
        budget=999,
        remarks="desktop e2e offer match incompatible",
    )
    listings.save_current(expected_text=listing_owner)
    incompatible_offer = wait_for(
        "incompatible offer mutation persisted",
        lambda: backend.api_fetch_offer(
            base_url=e2e_base_url,
            user=user,
            offer_id=offer_id,
        ),
        timeout=20.0,
    )
    assert incompatible_offer is not None
    assert _as_int(incompatible_offer["budget"]) == 999
    assert _as_int(incompatible_offer["budget"]) != _as_int(offer["budget"])

    reduced_total = wait_for(
        "match API total reduced after incompatible offer edit",
        lambda: _match_total_below(
            base_url=e2e_base_url,
            user=user,
            client_id=client_id,
            threshold=int(initial_total),
        ),
        timeout=60.0,
    )["total"]
    assert int(reduced_total) == 0

    main.select_tab("matches")
    match_page = MatchPage(main)
    match_page.run_for_client(client_name)
    match_page.wait_for_no_matching_listings()

    main.select_tab("listings")
    listings = ListingsPage(main, session)
    _open_listing(listings, phone=listing_phone, owner_name=listing_owner)
    listings.fill_first_offer(
        budget=250,
        remarks="desktop e2e offer match compatible again",
    )
    listings.save_current(expected_text=listing_owner)
    compatible_offer = wait_for(
        "compatible offer mutation persisted",
        lambda: backend.api_fetch_offer(
            base_url=e2e_base_url,
            user=user,
            offer_id=offer_id,
        ),
        timeout=20.0,
    )
    assert compatible_offer is not None
    assert str(compatible_offer["type"]) == "apartment"
    assert _as_int(compatible_offer["type_id"]) == _as_int(offer["type_id"])
    assert _as_int(compatible_offer["budget"]) == _as_int(offer["budget"])

    restored_total = wait_for(
        "match API total restored after compatible offer edit",
        lambda: (
            total
            if (
                total := backend.api_client_match_total(
                    base_url=e2e_base_url,
                    user=user,
                    client_id=client_id,
                )
            )
            >= int(initial_total)
            else None
        ),
        timeout=60.0,
    )
    assert int(restored_total) >= int(initial_total)

    main.select_tab("matches")
    match_page = MatchPage(main)
    match_page.run_for_client(client_name)
    match_page.wait_for_visible_match_text(listing_owner)
