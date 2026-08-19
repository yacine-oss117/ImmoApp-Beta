from __future__ import annotations

import base64
import uuid
from pathlib import Path

import pytest

from app.tests.e2e_desktop import backend
from app.tests.e2e_desktop.pages import ListingsPage, login_to_main_window
from app.tests.e2e_desktop.ui import wait_for

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_nightly, pytest.mark.nightly]

_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ"
    "/pLvAAAAAElFTkSuQmCC"
)


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


def _single_active_photo(
    *,
    base_url: str,
    user: backend.DesktopUser,
    offer_id: int,
) -> dict[str, object] | None:
    photos = backend.api_fetch_offer_photos(
        base_url=base_url,
        user=user,
        offer_id=offer_id,
    )
    if len(photos) != 1:
        return None
    return photos[0]


def _write_tiny_png(path: Path) -> None:
    path.write_bytes(base64.b64decode(_TINY_PNG_B64))


def test_offer_property_photo_upload_delete_via_desktop_ui(
    e2e_base_url: str,
    make_backend_user,
    launch_native_desktop,
    artifact_dir: Path,
) -> None:
    user = make_backend_user(prefix="e2e_offer_photo")
    owner_name = f"Offer Photo Owner {uuid.uuid4().hex[:6]}"
    phone = _phone("213783")
    offer_remarks = f"offer photo {uuid.uuid4().hex[:8]}"
    png_path = artifact_dir / "property-photo.png"
    unsupported_path = artifact_dir / "property-photo.txt"
    _write_tiny_png(png_path)
    unsupported_path.write_text("not an image", encoding="utf-8")

    listing_id = backend.api_create_listing(
        base_url=e2e_base_url,
        user=user,
        family_name=owner_name,
        phone=phone,
        remarks="desktop e2e offer photo parent",
    )
    offer_id = backend.api_create_offer(
        base_url=e2e_base_url,
        user=user,
        listing_id=listing_id,
        payload={
            "type_id": 1,
            "action_id": 1,
            "wilaya_id": 16,
            "location": "Hydra, Algiers - 16",
            "beds": 3,
            "surface": 95.0,
            "budget": 300.0,
            "price_negotiable": True,
            "price_flex_pct": 8.0,
            "furnished": "yes",
            "floor": 2,
            "elevator": True,
            "accessibility_supported": True,
            "link": "",
            "latitude": 36.7525,
            "longitude": 3.042,
            "remarks": offer_remarks,
        },
    )
    assert offer_id > 0

    session = launch_native_desktop(username=user.username)
    main = login_to_main_window(
        session,
        username=user.username,
        password=user.password,
        base_url=e2e_base_url,
    )
    main.select_tab("listings")
    listings = ListingsPage(main, session)
    listings.select_existing(
        search_value="",
        expected_name=phone,
        editor_expected_name=owner_name,
    )
    listings.wait_for_offer_photo_status(
        offer_id=offer_id,
        expected_text="No property photos yet.",
    )

    listings.add_offer_photo(offer_id=offer_id, file_path=png_path)
    photo = wait_for(
        "uploaded offer photo backend truth",
        lambda: _single_active_photo(base_url=e2e_base_url, user=user, offer_id=offer_id),
        timeout=60.0,
    )
    photo_id = _as_int(photo.get("id"))
    assert photo_id > 0
    storage_id = str(photo.get("storage_id") or "")
    assert storage_id
    listings.wait_for_offer_photo_item(offer_id=offer_id, photo_id=photo_id)

    storage_row = backend.fetch_storage_object_row(
        agency_id=user.agency_id,
        storage_id=storage_id,
    )
    assert storage_row is not None
    assert str(storage_row["status"]) == "ready"
    assert str(storage_row["purpose"]) == "offer_photo"
    assert str(storage_row["content_type"]) == "image/png"
    assert _as_int(storage_row["agency_id"]) == user.agency_id

    listings.delete_offer_photo(offer_id=offer_id, photo_id=photo_id)
    wait_for(
        "offer photo removed from active API list",
        lambda: (
            True
            if not backend.api_fetch_offer_photos(
                base_url=e2e_base_url,
                user=user,
                offer_id=offer_id,
            )
            else None
        ),
        timeout=30.0,
    )
    deleted = backend.api_fetch_offer_photos(
        base_url=e2e_base_url,
        user=user,
        offer_id=offer_id,
        include_deleted=True,
    )
    deleted_photo = next(item for item in deleted if _as_int(item.get("id")) == photo_id)
    assert str(deleted_photo.get("deleted_at") or "")

    listings.add_unsupported_offer_photo_expect_error(
        offer_id=offer_id,
        file_path=unsupported_path,
    )
    assert not backend.api_fetch_offer_photos(
        base_url=e2e_base_url,
        user=user,
        offer_id=offer_id,
    )
