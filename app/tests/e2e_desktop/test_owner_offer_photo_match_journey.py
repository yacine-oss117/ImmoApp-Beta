from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

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


def _write_png(path: Path, *, color: tuple[int, int, int], label: str) -> None:
    image = Image.new("RGB", (96, 64), color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, 92, 60), outline=(255, 255, 255), width=2)
    draw.text((12, 24), label, fill=(255, 255, 255))
    image.save(path, format="PNG")


def _active_photo(
    *,
    base_url: str,
    user: backend.DesktopUser,
    offer_id: int,
    exclude_ids: set[int] | None = None,
) -> dict[str, object] | None:
    excluded = set(exclude_ids or set())
    photos = backend.api_fetch_offer_photos(
        base_url=base_url,
        user=user,
        offer_id=offer_id,
    )
    matches = [photo for photo in photos if _as_int(photo.get("id")) not in excluded]
    if len(matches) != 1:
        return None
    return matches[0]


def _match_offer_ids_by_demande(
    payload: dict[str, object],
) -> dict[int, set[int]]:
    pairings: dict[int, set[int]] = {}
    for raw_result in list(payload.get("demande_results", []) or []):
        if not isinstance(raw_result, dict):
            continue
        demande_id = _as_int(raw_result.get("demande_id"))
        if demande_id <= 0:
            continue
        offer_ids: set[int] = set()
        for raw_match in list(raw_result.get("matches", []) or []):
            if not isinstance(raw_match, dict):
                continue
            offer_payload = raw_match.get("offer")
            if isinstance(offer_payload, dict):
                offer_id = _as_int(offer_payload.get("id"))
            else:
                offer_id = _as_int(raw_match.get("offer_id"))
            if offer_id > 0:
                offer_ids.add(offer_id)
        pairings[demande_id] = offer_ids
    return pairings


def test_owner_two_offers_photos_two_demandes_match_end_to_end_via_desktop_ui(
    e2e_base_url: str,
    make_backend_user,
    launch_native_desktop,
    artifact_dir: Path,
) -> None:
    user = make_backend_user(prefix="e2e_owner_offer_photo_match")
    suffix = uuid.uuid4().hex[:6]
    owner_name = f"Journey Owner {suffix}"
    buyer_name = f"Journey Buyer {suffix}"
    owner_phone = _phone("213784")
    buyer_phone = _phone("213684")
    offer_1_remarks = f"journey offer bab ezzouar {uuid.uuid4().hex[:8]}"
    offer_2_remarks = f"journey offer el harrach {uuid.uuid4().hex[:8]}"
    demande_1_remarks = f"journey demande bab ezzouar {uuid.uuid4().hex[:8]}"
    demande_2_remarks = f"journey demande el harrach {uuid.uuid4().hex[:8]}"
    photo_a = artifact_dir / "offer-a-bab-ezzouar.png"
    photo_b = artifact_dir / "offer-b-el-harrach.png"
    _write_png(photo_a, color=(30, 105, 210), label="A1")
    _write_png(photo_b, color=(180, 65, 40), label="B2")

    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )

    main.select_tab("listings")
    listings = ListingsPage(main, session)
    listings.create_listing(
        owner_name=owner_name,
        phone=owner_phone,
        remarks=f"owner journey listing {suffix}",
    )
    listing_row = wait_for(
        "owner listing created through desktop UI",
        lambda: backend.api_find_listing_row(
            base_url=e2e_base_url,
            user=user,
            search=owner_name,
            family_name=owner_name,
            phone=owner_phone,
        ),
        timeout=30.0,
    )
    listing_id = _as_int(listing_row.get("id"))
    assert listing_id > 0

    listings.select_visible_existing(
        expected_name=owner_name,
        editor_expected_name=owner_name,
    )
    listings.add_offer(
        panel_index=1,
        type_label="Apartment",
        action_label="For Sale",
        wilaya="Algiers - 16",
        location="Bab Ezzouar",
        beds=3,
        surface=88,
        budget=260,
        furnished_label="Yes",
        floor=4,
        elevator=True,
        accessibility_supported=True,
        price_negotiable=True,
        price_flex_pct=7,
        link="",
        remarks=offer_1_remarks,
    )
    listings.add_offer(
        panel_index=2,
        type_label="Apartment",
        action_label="For Sale",
        wilaya="Algiers - 16",
        location="El Harrach",
        beds=2,
        surface=72,
        budget=430,
        furnished_label="No",
        floor=1,
        elevator=False,
        accessibility_supported=False,
        price_negotiable=True,
        price_flex_pct=5,
        link="",
        remarks=offer_2_remarks,
    )
    listings.save_current(expected_text=owner_name)

    offer_1 = wait_for(
        "first desktop-created offer persisted",
        lambda: _single_by_remarks(
            backend.api_fetch_listing_offers(
                base_url=e2e_base_url,
                user=user,
                listing_id=listing_id,
            ),
            offer_1_remarks,
        ),
        timeout=30.0,
    )
    offer_2 = wait_for(
        "second desktop-created offer persisted",
        lambda: _single_by_remarks(
            backend.api_fetch_listing_offers(
                base_url=e2e_base_url,
                user=user,
                listing_id=listing_id,
            ),
            offer_2_remarks,
        ),
        timeout=30.0,
    )
    offer_1_id = _as_int(offer_1["id"])
    offer_2_id = _as_int(offer_2["id"])
    assert offer_1_id > 0 and offer_2_id > 0 and offer_1_id != offer_2_id
    assert str(offer_1["location"]) == "Bab Ezzouar, Algiers - 16"
    assert str(offer_2["location"]) == "El Harrach, Algiers - 16"

    listings.select_visible_existing(
        expected_name=owner_name,
        editor_expected_name=owner_name,
    )
    listings.add_offer_photo(offer_id=offer_1_id, file_path=photo_a)
    uploaded_a = wait_for(
        "first offer photo uploaded",
        lambda: _active_photo(base_url=e2e_base_url, user=user, offer_id=offer_1_id),
        timeout=60.0,
    )
    photo_a_first_id = _as_int(uploaded_a["id"])
    listings.wait_for_offer_photo_item(offer_id=offer_1_id, photo_id=photo_a_first_id)
    listings.wait_for_offer_photo_thumbnail_loaded(
        offer_id=offer_1_id,
        photo_id=photo_a_first_id,
    )

    listings.add_offer_photo(offer_id=offer_2_id, file_path=photo_b)
    uploaded_b = wait_for(
        "second offer photo uploaded",
        lambda: _active_photo(base_url=e2e_base_url, user=user, offer_id=offer_2_id),
        timeout=60.0,
    )
    photo_b_id = _as_int(uploaded_b["id"])
    listings.wait_for_offer_photo_item(offer_id=offer_2_id, photo_id=photo_b_id)
    listings.wait_for_offer_photo_thumbnail_loaded(offer_id=offer_2_id, photo_id=photo_b_id)

    listings.delete_offer_photo(offer_id=offer_1_id, photo_id=photo_a_first_id)
    wait_for(
        "first offer photo deleted from active backend list",
        lambda: (
            True
            if not backend.api_fetch_offer_photos(
                base_url=e2e_base_url,
                user=user,
                offer_id=offer_1_id,
            )
            else None
        ),
        timeout=30.0,
    )
    deleted_photos = backend.api_fetch_offer_photos(
        base_url=e2e_base_url,
        user=user,
        offer_id=offer_1_id,
        include_deleted=True,
    )
    deleted_photo = next(
        item for item in deleted_photos if _as_int(item.get("id")) == photo_a_first_id
    )
    assert str(deleted_photo.get("deleted_at") or "")

    listings.add_offer_photo(offer_id=offer_1_id, file_path=photo_a)
    uploaded_a_again = wait_for(
        "first offer photo re-added after delete",
        lambda: _active_photo(
            base_url=e2e_base_url,
            user=user,
            offer_id=offer_1_id,
            exclude_ids={photo_a_first_id},
        ),
        timeout=60.0,
    )
    photo_a_final_id = _as_int(uploaded_a_again["id"])
    assert photo_a_final_id > 0 and photo_a_final_id != photo_a_first_id
    listings.wait_for_offer_photo_item(offer_id=offer_1_id, photo_id=photo_a_final_id)
    listings.wait_for_offer_photo_thumbnail_loaded(
        offer_id=offer_1_id,
        photo_id=photo_a_final_id,
    )

    main.select_tab("clients")
    clients = ClientsPage(main, session)
    clients.create_client(family_name=buyer_name, phone=buyer_phone)
    client_row = wait_for(
        "buyer client created through desktop UI",
        lambda: backend.api_find_client_row(
            base_url=e2e_base_url,
            user=user,
            search=buyer_name,
            family_name=buyer_name,
            phone=buyer_phone,
        ),
        timeout=30.0,
    )
    client_id = _as_int(client_row.get("id"))
    assert client_id > 0

    clients.select_visible_existing(
        expected_name=buyer_name,
        editor_expected_name=buyer_name,
    )
    clients.add_demande(
        panel_index=1,
        type_label="Apartment",
        action_label="To Buy",
        wilaya="Algiers - 16",
        location="Bab Ezzouar",
        beds_min=3,
        surface_min=80,
        surface_max=95,
        budget_min=220,
        budget_max=300,
        furnished_label="Yes",
        floor_min=2,
        floor_max=6,
        elevator=True,
        accessibility_required=True,
        tags="journey-apartment",
        remarks=demande_1_remarks,
    )
    clients.add_demande(
        panel_index=2,
        type_label="Apartment",
        action_label="To Buy",
        wilaya="Algiers - 16",
        location="El Harrach",
        beds_min=2,
        surface_min=65,
        surface_max=85,
        budget_min=380,
        budget_max=470,
        furnished_label="No",
        floor_min=0,
        floor_max=2,
        elevator=None,
        accessibility_required=None,
        tags="journey-el-harrach",
        remarks=demande_2_remarks,
    )
    clients.save_current(expected_text=buyer_name)

    demande_1 = wait_for(
        "first desktop-created demande persisted",
        lambda: _single_by_remarks(
            backend.api_fetch_client_demandes(
                base_url=e2e_base_url,
                user=user,
                client_id=client_id,
            ),
            demande_1_remarks,
        ),
        timeout=30.0,
    )
    demande_2 = wait_for(
        "second desktop-created demande persisted",
        lambda: _single_by_remarks(
            backend.api_fetch_client_demandes(
                base_url=e2e_base_url,
                user=user,
                client_id=client_id,
            ),
            demande_2_remarks,
        ),
        timeout=30.0,
    )
    demande_1_id = _as_int(demande_1["id"])
    demande_2_id = _as_int(demande_2["id"])
    assert demande_1_id > 0 and demande_2_id > 0 and demande_1_id != demande_2_id

    main.select_tab("matches")
    match_page = MatchPage(main)
    match_page.run_for_client(buyer_name)

    match_payload = wait_for(
        "backend match truth contains intended offer-demande pairings",
        lambda: (
            payload
            if (
                offer_1_id
                in _match_offer_ids_by_demande(
                    payload := backend.api_fetch_client_matches(
                        base_url=e2e_base_url,
                        user=user,
                        client_id=client_id,
                    )
                ).get(demande_1_id, set())
                and offer_2_id in _match_offer_ids_by_demande(payload).get(demande_2_id, set())
            )
            else None
        ),
        timeout=90.0,
    )
    pairings = _match_offer_ids_by_demande(match_payload)
    assert offer_1_id in pairings[demande_1_id]
    assert offer_2_id in pairings[demande_2_id]

    for expected_text in (
        owner_name,
        "Bab Ezzouar",
        "El Harrach",
        "Apartment",
    ):
        match_page.wait_for_visible_match_text(expected_text)
    match_page.open_offer_photos_for_match(
        listing_id=listing_id,
        offer_id=offer_1_id,
        expected_photo_id=photo_a_final_id,
    )
    match_page.open_offer_photos_for_match(
        listing_id=listing_id,
        offer_id=offer_2_id,
        expected_photo_id=photo_b_id,
    )

    refreshed_offers = backend.api_fetch_listing_offers(
        base_url=e2e_base_url,
        user=user,
        listing_id=listing_id,
    )
    assert len(refreshed_offers) == 2
    refreshed_demandes = backend.api_fetch_client_demandes(
        base_url=e2e_base_url,
        user=user,
        client_id=client_id,
    )
    assert len(refreshed_demandes) == 2
    active_offer_1_photos = backend.api_fetch_offer_photos(
        base_url=e2e_base_url,
        user=user,
        offer_id=offer_1_id,
    )
    active_offer_2_photos = backend.api_fetch_offer_photos(
        base_url=e2e_base_url,
        user=user,
        offer_id=offer_2_id,
    )
    assert [_as_int(item.get("id")) for item in active_offer_1_photos] == [photo_a_final_id]
    assert [_as_int(item.get("id")) for item in active_offer_2_photos] == [photo_b_id]
    assert str(active_offer_1_photos[0].get("storage_id") or "") != str(
        active_offer_2_photos[0].get("storage_id") or ""
    )
