from __future__ import annotations

import ast
import inspect
import uuid
from collections.abc import Callable
from pathlib import Path
from queue import Queue
from threading import Barrier, Thread

import django
import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    cleanup_import_test_agency,
    create_agency,
    create_manager_user,
    ensure_django,
)

_DJANGO_READY = False


def _ensure_django() -> None:
    global _DJANGO_READY
    if _DJANGO_READY:
        return
    django.setup()
    _DJANGO_READY = True


ensure_django()

from core.contracts.offer_photo_lifecycle import (  # noqa: E402
    PHOTO_DELETE_ORIGIN_LISTING_DELETED,
    PHOTO_DELETE_ORIGIN_MANUAL,
    PHOTO_DELETE_ORIGIN_OFFER_DELETED,
    PHOTO_DELETE_PARENT_SCOPE_LISTING,
    PHOTO_DELETE_PARENT_SCOPE_OFFER,
)
from core.contracts.offer_photo_media import (  # noqa: E402
    OFFER_PHOTO_CONTENT_TYPES,
    OFFER_PHOTO_EXTENSIONS,
    OFFER_PHOTO_PURPOSE,
    is_supported_offer_photo_filename,
    offer_photo_content_type_for_filename,
)
from core.data import storage_objects as storage_data  # noqa: E402
from core.data.errors import NotFoundError  # noqa: E402
from server.pg.schema import ensure_schema  # noqa: E402
from server.pg.uow import admin_transaction, get_uow, use_security_context  # noqa: E402
from server.services import listings as listings_service  # noqa: E402
from server.services import offer_photos, storage_validation  # noqa: E402
from server.services import offers as offers_service  # noqa: E402


class _User:
    is_authenticated = True
    is_active = True
    is_superuser = False
    agency_id = 1
    id = 7
    role = "owner"


class _ApiUser:
    is_authenticated = True
    is_active = True
    is_superuser = False
    role = "manager"

    def __init__(self, *, agency_id: int, user_id: int) -> None:
        self.agency_id = agency_id
        self.id = user_id


def test_offer_photo_create_response_includes_item_and_is_idempotent(monkeypatch) -> None:
    _ensure_django()

    import server.api.views_offers as module
    from server.api.views_offers import offer_photos_endpoint

    monkeypatch.setattr(
        module.offer_photos,
        "add_offer_photo",
        lambda **kwargs: module.offer_photos.OfferPhotoAttachResult(
            photo_id=41,
            created=True,
        ),
    )
    monkeypatch.setattr(
        module.offer_photos,
        "get_offer_photo_by_id",
        lambda *, photo_id: {
            "id": photo_id,
            "offer_id": 9,
            "storage_id": "550e8400-e29b-41d4-a716-446655440000",
            "position": 2,
            "created_at": "2026-03-10T12:00:00+00:00",
            "updated_at": "2026-03-10T12:00:00+00:00",
            "deleted_at": None,
            "row_version": 1,
        },
    )

    stored: list[tuple[object, int]] = []

    def _store(idem_ctx, response, request):
        stored.append((idem_ctx, response.status_code))
        return response

    monkeypatch.setattr(module, "check_idempotency", lambda request: ("ctx", None))
    monkeypatch.setattr(module, "store_idempotency", _store)

    request = APIRequestFactory().post(
        "/api/v1/offers/9/photos/",
        {"storage_id": "550e8400-e29b-41d4-a716-446655440000", "position": 2},
        format="json",
        HTTP_IDEMPOTENCY_KEY="offline:test:photo",
    )
    force_authenticate(request, user=_User())

    response = offer_photos_endpoint(request, 9)

    assert response.status_code == 201
    assert response.data["id"] == 41
    assert response.data["item"]["id"] == 41
    assert response.data["item"]["offer_id"] == 9
    assert stored == [("ctx", 201)]


def test_offer_photo_duplicate_attach_api_returns_existing_item(monkeypatch) -> None:
    _ensure_django()

    import server.api.views_offers as module
    from server.api.views_offers import offer_photos_endpoint

    monkeypatch.setattr(
        module.offer_photos,
        "add_offer_photo",
        lambda **kwargs: module.offer_photos.OfferPhotoAttachResult(
            photo_id=41,
            created=False,
        ),
    )
    monkeypatch.setattr(
        module.offer_photos,
        "get_offer_photo_by_id",
        lambda *, photo_id: {
            "id": photo_id,
            "offer_id": 9,
            "storage_id": "550e8400-e29b-41d4-a716-446655440000",
            "position": 2,
            "created_at": "2026-03-10T12:00:00+00:00",
            "updated_at": "2026-03-10T12:00:00+00:00",
            "deleted_at": None,
            "row_version": 1,
        },
    )

    stored: list[tuple[object, int]] = []

    def _store(idem_ctx, response, request):
        stored.append((idem_ctx, response.status_code))
        return response

    monkeypatch.setattr(module, "check_idempotency", lambda request: ("ctx", None))
    monkeypatch.setattr(module, "store_idempotency", _store)

    request = APIRequestFactory().post(
        "/api/v1/offers/9/photos/",
        {"storage_id": "550e8400-e29b-41d4-a716-446655440000", "position": 2},
        format="json",
        HTTP_IDEMPOTENCY_KEY="offline:test:photo:duplicate",
    )
    force_authenticate(request, user=_User())

    response = offer_photos_endpoint(request, 9)

    assert response.status_code == 200
    assert response.data["id"] == 41
    assert response.data["item"]["id"] == 41
    assert stored == [("ctx", 200)]


@pytest.mark.parametrize(
    ("reason", "message"),
    [
        ("missing", "Offer not found"),
        ("deleted", "Offer not found"),
        ("cross_tenant", "Offer not found"),
    ],
)
def test_offer_photo_attach_api_maps_not_found_safely(
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    message: str,
) -> None:
    _ensure_django()

    import server.api.views_offers as module
    from server.api.views_offers import offer_photos_endpoint

    def _raise_not_found(**_kwargs):
        raise NotFoundError(message)

    monkeypatch.setattr(module.offer_photos, "add_offer_photo", _raise_not_found)
    monkeypatch.setattr(module, "check_idempotency", lambda request: (f"ctx:{reason}", None))

    request = APIRequestFactory().post(
        "/api/v1/offers/999/photos/",
        {"storage_id": "550e8400-e29b-41d4-a716-446655440000", "position": 2},
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"offline:test:photo:{reason}",
    )
    force_authenticate(request, user=_User())

    response = offer_photos_endpoint(request, 999)

    assert response.status_code == 404
    assert response.data["detail"] == "Resource not found"
    assert message not in str(response.data)
    assert "traceback" not in str(response.data).lower()
    assert "unique constraint" not in str(response.data).lower()


def _cleanup_agency(agency_id: int, user_id: int) -> None:
    cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)


def _seed_agency(prefix: str) -> tuple[int, int]:
    suffix = uuid.uuid4().hex[:8]
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"{prefix.upper()}{suffix}", f"{prefix} {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"{prefix.lower()}_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()
        return int(agency_id), int(user_id)
    finally:
        conn.close()


def _create_listing_and_offer(*, agency_id: int, user_id: int, suffix: str) -> tuple[int, int]:
    _ = user_id
    with use_security_context(agency_id=agency_id, is_superuser=False):
        listing_id = listings_service.upsert_listing(
            {
                "family_name": f"Photo Owner {suffix}",
                "phone": f"2137{int(uuid.uuid4().int % 1000000):06d}",
                "status": "available",
                "remarks": "offer photo contract seed",
            },
            actor="test_offer_photos",
        )
        offer_id = offers_service.create_offer(
            listing_id,
            {
                "type_id": 1,
                "action_id": 1,
                "wilaya_id": 16,
                "location": "Hydra, Algiers - 16",
                "beds": 2,
                "surface": 90.0,
                "budget": 250.0,
                "price_negotiable": True,
                "price_flex_pct": 10.0,
                "furnished": "yes",
                "floor": 2,
                "elevator": True,
                "accessibility_supported": True,
                "link": "",
                "latitude": 36.7525,
                "longitude": 3.042,
                "remarks": f"photo offer {suffix}",
            },
            actor="test_offer_photos",
        )
    return int(listing_id), int(offer_id)


def _create_ready_storage(
    *,
    agency_id: int,
    user_id: int,
    suffix: str,
    purpose: str = OFFER_PHOTO_PURPOSE,
    content_type: str = "image/png",
    size_bytes: int = 128,
) -> str:
    with use_security_context(agency_id=agency_id, is_superuser=False):
        with get_uow().transaction(actor="test_offer_photo_storage_seed") as session:
            storage_id = storage_data.create_storage_object(
                session,
                bucket="immoapp",
                object_key=f"agency/{agency_id}/offer-photos/{suffix}.png",
                user_id=user_id,
                role="manager",
                purpose=purpose,
                content_type=content_type,
                size_bytes=size_bytes,
                checksum=f"checksum-{suffix}",
                created_ip="127.0.0.1",
            )
            storage_data.mark_storage_ready(
                session,
                storage_id=storage_id,
                content_type=content_type,
                size_bytes=size_bytes,
                checksum=f"checksum-{suffix}",
            )
            storage_data.bump_storage_usage(
                session,
                agency_id=agency_id,
                delta_bytes=size_bytes,
            )
            return storage_id


def _storage_row(storage_id: str) -> dict[str, object]:
    with admin_transaction() as session:
        row = storage_data.get_storage_object(session, storage_id)
    assert row is not None
    return row


def _usage_for_agency(agency_id: int) -> int:
    with admin_transaction() as session:
        return storage_data.get_usage_for_agency(session, agency_id=agency_id)


def _storage_event_count(storage_id: str, event_type: str) -> int:
    with admin_transaction() as session:
        row = session.execute(
            """
            SELECT COUNT(*) AS count
            FROM storage_events
            WHERE storage_id = %s AND event_type = %s
            """,
            (storage_id, event_type),
        ).fetchone()
    return int(row["count"]) if row else 0


def _photo_row(photo_id: int) -> dict[str, object]:
    with admin_transaction() as session:
        row = session.execute(
            "SELECT * FROM offer_photos WHERE id = %s",
            (photo_id,),
        ).fetchone()
    assert row is not None
    return dict(row)


def _active_photo_storage_statuses(storage_id: str) -> list[str]:
    with admin_transaction() as session:
        rows = session.execute(
            """
            SELECT so.status
            FROM offer_photos op
            JOIN storage_objects so ON so.id = op.storage_id
            WHERE op.storage_id = %s
              AND op.deleted_at IS NULL
            ORDER BY op.id
            """,
            (storage_id,),
        ).fetchall()
    return [str(row["status"]) for row in rows]


def _active_photo_count(storage_id: str) -> int:
    with admin_transaction() as session:
        row = session.execute(
            """
            SELECT COUNT(*) AS count
            FROM offer_photos
            WHERE storage_id = %s
              AND deleted_at IS NULL
            """,
            (storage_id,),
        ).fetchone()
    return int(row["count"]) if row else 0


def _run_two_lifecycle_threads(
    monkeypatch: pytest.MonkeyPatch,
    first: Callable[[], object],
    second: Callable[[], object],
) -> list[object]:
    import server.services.offer_photo_lifecycle as lifecycle

    barrier = Barrier(2)
    errors: Queue[BaseException] = Queue()
    results: Queue[object] = Queue()

    def _hook(_session: object, _storage_ids: object) -> None:
        barrier.wait(timeout=10)

    def _runner(fn: Callable[[], object]) -> None:
        try:
            results.put(fn())
        except Exception as exc:
            errors.put(exc)

    monkeypatch.setattr(lifecycle, "_before_aggregate_locks_acquired", _hook)
    threads = [Thread(target=_runner, args=(first,)), Thread(target=_runner, args=(second,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    hanging = [thread.name for thread in threads if thread.is_alive()]
    assert hanging == []
    if not errors.empty():
        raise errors.get()
    return list(results.queue)


def _post_offer_photo_api(
    *,
    agency_id: int,
    user_id: int,
    offer_id: int,
    storage_id: str,
    idempotency_suffix: str,
):
    from server.api.views_offers import offer_photos_endpoint

    request = APIRequestFactory().post(
        f"/api/v1/offers/{offer_id}/photos/",
        {"storage_id": storage_id, "position": 1},
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"offer-photo-api:{idempotency_suffix}:{uuid.uuid4().hex}",
    )
    force_authenticate(request, user=_ApiUser(agency_id=agency_id, user_id=user_id))
    with use_security_context(agency_id=agency_id, is_superuser=False):
        return offer_photos_endpoint(request, offer_id)


def _delete_offer_photo_api(
    *,
    agency_id: int,
    user_id: int,
    photo_id: int,
    idempotency_key: str,
):
    from server.api.views_offers import offer_photo_delete

    request = APIRequestFactory().delete(
        f"/api/v1/offers/photos/{photo_id}/",
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )
    force_authenticate(request, user=_ApiUser(agency_id=agency_id, user_id=user_id))
    with use_security_context(agency_id=agency_id, is_superuser=False):
        return offer_photo_delete(request, photo_id)


@pytest.mark.parametrize("case", ["missing", "deleted", "cross_tenant"])
def test_offer_photo_attach_api_not_found_contract_is_real_boundary(case: str) -> None:
    ensure_schema()
    agency_a, user_a = _seed_agency(f"photo_api_{case}_a")
    agency_b = 0
    user_b = 0
    try:
        _, offer_a = _create_listing_and_offer(
            agency_id=agency_a,
            user_id=user_a,
            suffix=f"api-{case}-a",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_a,
            user_id=user_a,
            suffix=f"api-{case}",
        )
        request_agency = agency_a
        request_user = user_a
        target_offer = offer_a
        if case == "missing":
            target_offer = 999_999_991
        elif case == "deleted":
            with use_security_context(agency_id=agency_a, is_superuser=False):
                offers_service.delete_offer(offer_a, actor="test_photo_api_deleted")
        else:
            agency_b, user_b = _seed_agency("photo_api_cross_b")
            storage_id = _create_ready_storage(
                agency_id=agency_b,
                user_id=user_b,
                suffix="api-cross-b",
            )
            request_agency = agency_b
            request_user = user_b

        response = _post_offer_photo_api(
            agency_id=request_agency,
            user_id=request_user,
            offer_id=target_offer,
            storage_id=storage_id,
            idempotency_suffix=case,
        )

        assert response.status_code == 404
        assert response.data["detail"] == "Resource not found"
        assert "Offer not found" not in str(response.data)
        assert "traceback" not in str(response.data).lower()
        assert "unique constraint" not in str(response.data).lower()
    finally:
        if agency_b and user_b:
            _cleanup_agency(agency_b, user_b)
        _cleanup_agency(agency_a, user_a)


def test_offer_photo_media_contract_is_shared_and_excludes_webp() -> None:
    from core.contracts.route_policy_registry import ROUTE_POLICIES

    assert OFFER_PHOTO_PURPOSE == "offer_photo"
    assert set(OFFER_PHOTO_EXTENSIONS) == {".png", ".jpg", ".jpeg", ".bmp"}
    assert set(OFFER_PHOTO_CONTENT_TYPES) == {"image/png", "image/jpeg", "image/bmp"}
    assert is_supported_offer_photo_filename("kitchen.PNG") is True
    assert is_supported_offer_photo_filename("tour.webp") is False
    assert offer_photo_content_type_for_filename("front.webp") == "application/octet-stream"
    assert "image/webp" not in storage_validation._ALLOWED_PURPOSES["offer_photo"]["content_types"]
    assert "offers/<int:offer_id>/photos/" in ROUTE_POLICIES
    assert "offers/photos/changes/" in ROUTE_POLICIES
    assert "storage/presign-upload/" in ROUTE_POLICIES
    assert "storage/complete-upload/" in ROUTE_POLICIES
    with pytest.raises(storage_validation.StorageError):
        storage_validation.validate_purpose("offer_photo", "tour.webp", "image/webp")
    with pytest.raises(storage_validation.StorageError):
        storage_validation.validate_purpose("offer_photo", "tour.png", "image/webp")


def test_offer_photo_architecture_has_no_listing_photos_or_e2e_mutation_backdoor() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    source_roots = (repo_root / "server", repo_root / "core", repo_root / "app")
    listing_photo_hits: list[str] = []
    for root in source_roots:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if path == Path(__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8")
            if "listing_photos" in text:
                listing_photo_hits.append(str(path.relative_to(repo_root)))
    assert listing_photo_hits == []

    e2e_sources = [
        repo_root / "server" / "api" / "views_e2e.py",
        repo_root / "server" / "services" / "e2e_control.py",
    ]
    e2e_text = "\n".join(path.read_text(encoding="utf-8") for path in e2e_sources)
    assert "offer_photo" not in e2e_text
    assert "offer_photos" not in e2e_text

    e2e_photo_test = repo_root / "app" / "tests" / "e2e_desktop" / "test_offer_photos.py"
    e2e_photo_text = e2e_photo_test.read_text(encoding="utf-8")
    forbidden = ("time.sleep", "pytest.skip", "pytest.xfail", "mark.skip", "mark.xfail")
    assert [token for token in forbidden if token in e2e_photo_text] == []

    widget_text = (repo_root / "app" / "widgets" / "offer_photos_widget.py").read_text(
        encoding="utf-8"
    )
    for token in (
        "offerPhotosSection_",
        "offerPhotosAddButton_",
        "offerPhotosList_",
        "offerPhotoItem_",
        "offerPhotoDeleteButton_",
        "offerPhotosStatus_",
    ):
        assert token in widget_text

    lifecycle_source = repo_root / "server" / "services" / "offer_photo_lifecycle.py"
    assert lifecycle_source.exists()
    lifecycle_text = lifecycle_source.read_text(encoding="utf-8")
    assert "purge_storage_object_now" not in lifecycle_text
    assert "pg_advisory_xact_lock" in lifecycle_text
    assert "_lock_photo_storage_aggregate" in lifecycle_text
    for function_name in (
        "add_offer_photo",
        "delete_offer_photo",
        "mark_offer_photos_deleted_for_offers",
        "restore_offer_photos_for_offers",
    ):
        start = lifecycle_text.index(f"def {function_name}(")
        next_def = lifecycle_text.find("\ndef ", start + 1)
        segment = lifecycle_text[start:] if next_def == -1 else lifecycle_text[start:next_def]
        assert "_lock_photo_storage_aggregates" in segment
        if "count_active_storage_refs" in segment:
            assert segment.index("_lock_photo_storage_aggregates") < segment.index(
                "count_active_storage_refs"
            )

    from core.contracts.route_policy_registry import ROUTE_POLICIES
    from server.api import idempotency as idempotency_facade

    views_offers_source = (repo_root / "server" / "api" / "views_offers.py").read_text(
        encoding="utf-8"
    )

    delete_policy = ROUTE_POLICIES["offers/photos/<int:photo_id>/"]
    assert delete_policy.retry_class == "IDEMPOTENCY_KEY_WRITE"
    start = views_offers_source.index("def offer_photo_delete(")
    next_route = views_offers_source.find("\n@route", start + 1)
    delete_source = (
        views_offers_source[start:] if next_route == -1 else views_offers_source[start:next_route]
    )
    assert "check_idempotency" in delete_source
    assert "store_idempotency" in delete_source

    facade_source = inspect.getsource(idempotency_facade)
    facade_tree = ast.parse(facade_source)
    facade_nodes = [
        node
        for node in facade_tree.body
        if not isinstance(node, (ast.Expr, ast.ImportFrom, ast.Assign))
    ]
    assert facade_nodes == []
    assert "idempotency_engine" in facade_source

    direct_update_hits: list[str] = []
    allowed_update_owner = repo_root / "core" / "data" / "offer_photos_repository.py"
    for root in (repo_root / "server", repo_root / "core"):
        for path in root.rglob("*.py"):
            if (
                "__pycache__" in path.parts
                or path == allowed_update_owner
                or ("alembic" in path.parts and "versions" in path.parts)
            ):
                continue
            text = path.read_text(encoding="utf-8")
            if "UPDATE offer_photos" in text:
                direct_update_hits.append(str(path.relative_to(repo_root)))
    assert direct_update_hits == []

    repository_text = allowed_update_owner.read_text(encoding="utf-8")
    restore_start = repository_text.index("def restore_offer_photos_for_offers(")
    restore_next = repository_text.find("\ndef ", restore_start + 1)
    restore_source = (
        repository_text[restore_start:]
        if restore_next == -1
        else repository_text[restore_start:restore_next]
    )
    assert "delete_origin = %s" in restore_source
    assert "delete_parent_scope = %s" in restore_source
    assert "delete_parent_id = %s" in restore_source

    photo_idempotency_modules = [
        str(path.relative_to(repo_root))
        for root in (repo_root / "server", repo_root / "core", repo_root / "app")
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
        and "photo" in path.name.lower()
        and "idempot" in path.name.lower()
    ]
    assert photo_idempotency_modules == []


def test_offer_photo_attach_rejects_wrong_storage_purpose() -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_purpose")
    try:
        _, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix="purpose",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="purpose",
            purpose="agency_logo",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            with pytest.raises(ValueError, match="purpose mismatch"):
                offer_photos.add_offer_photo(offer_id=offer_id, storage_id=storage_id)
    finally:
        _cleanup_agency(agency_id, user_id)


@pytest.mark.parametrize("storage_status", ["missing", "pending", "failed"])
def test_offer_photo_attach_rejects_unready_storage(storage_status: str) -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency(f"photo_unready_{storage_status}")
    try:
        _, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix=f"unready-{storage_status}",
        )
        storage_id = str(uuid.uuid4())
        with use_security_context(agency_id=agency_id, is_superuser=False):
            if storage_status != "missing":
                with get_uow().transaction(
                    actor="test_offer_photo_unready_storage_seed"
                ) as session:
                    storage_id = storage_data.create_storage_object(
                        session,
                        bucket="immoapp",
                        object_key=f"agency/{agency_id}/offer-photos/{storage_status}.png",
                        user_id=user_id,
                        role="manager",
                        purpose=OFFER_PHOTO_PURPOSE,
                        content_type="image/png",
                        size_bytes=128,
                        checksum=f"checksum-{storage_status}",
                        created_ip="127.0.0.1",
                    )
                    if storage_status == "failed":
                        storage_data.mark_storage_failed(
                            session,
                            storage_id=storage_id,
                            message="failed_for_test",
                        )
            with pytest.raises(ValueError, match="Storage object"):
                offer_photos.add_offer_photo(offer_id=offer_id, storage_id=storage_id)
    finally:
        _cleanup_agency(agency_id, user_id)


def test_offer_photo_attach_is_tenant_scoped() -> None:
    ensure_schema()
    agency_a, user_a = _seed_agency("photo_tenant_a")
    agency_b, user_b = _seed_agency("photo_tenant_b")
    try:
        _, offer_id = _create_listing_and_offer(
            agency_id=agency_a,
            user_id=user_a,
            suffix="tenant-a",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_b,
            user_id=user_b,
            suffix="tenant-b",
        )
        with use_security_context(agency_id=agency_b, is_superuser=False):
            assert offer_photos.list_offer_photos(offer_id=offer_id) == []
            with pytest.raises(NotFoundError):
                offer_photos.add_offer_photo(offer_id=offer_id, storage_id=storage_id)
    finally:
        _cleanup_agency(agency_a, user_a)
        _cleanup_agency(agency_b, user_b)


def test_offer_photo_duplicate_attach_is_idempotent_and_restore_reuses_row() -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_duplicate")
    try:
        _, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix="duplicate",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="duplicate",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            assert _usage_for_agency(agency_id) == 128
            first = offer_photos.add_offer_photo(
                offer_id=offer_id,
                storage_id=storage_id,
                position=1,
            )
            duplicate = offer_photos.add_offer_photo(
                offer_id=offer_id,
                storage_id=storage_id,
                position=2,
            )
            assert first.created is True
            assert first.status_code == 201
            assert duplicate.created is False
            assert duplicate.restored is False
            assert duplicate.status_code == 200
            assert duplicate.photo_id == first.photo_id
            assert len(offer_photos.list_offer_photos(offer_id=offer_id)) == 1

            assert offer_photos.delete_offer_photo(
                photo_id=first.photo_id,
                user_id=user_id,
                role="manager",
                created_ip="127.0.0.1",
            )
            assert _storage_row(storage_id)["status"] == "deleted"
            assert _usage_for_agency(agency_id) == 0
            deleted_row = _photo_row(first.photo_id)
            assert deleted_row["delete_origin"] == PHOTO_DELETE_ORIGIN_MANUAL
            assert deleted_row["delete_parent_scope"] is None
            assert deleted_row["delete_parent_id"] is None
            restored = offer_photos.add_offer_photo(
                offer_id=offer_id,
                storage_id=storage_id,
                position=3,
                user_id=user_id,
                role="manager",
                created_ip="127.0.0.1",
            )
            assert restored.photo_id == first.photo_id
            assert restored.created is False
            assert restored.restored is True
            assert restored.status_code == 201
            active = offer_photos.list_offer_photos(offer_id=offer_id)
            assert len(active) == 1
            assert active[0]["id"] == first.photo_id
            assert active[0]["deleted_at"] is None
            assert active[0]["position"] == 3
            restored_row = _photo_row(first.photo_id)
            assert restored_row["delete_origin"] is None
            assert restored_row["delete_parent_scope"] is None
            assert restored_row["delete_parent_id"] is None
            row = _storage_row(storage_id)
            assert row["status"] == "ready"
            assert row["deleted_at"] is None
            assert _usage_for_agency(agency_id) == 128
            assert _storage_event_count(storage_id, "restored") == 1
    finally:
        _cleanup_agency(agency_id, user_id)


def test_offer_photo_deleted_reattach_does_not_restore_purged_storage() -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_purged")
    try:
        _, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix="purged",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="purged",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            photo_id = offer_photos.add_offer_photo(
                offer_id=offer_id,
                storage_id=storage_id,
            ).photo_id
            assert offer_photos.delete_offer_photo(
                photo_id=photo_id,
                user_id=user_id,
                role="manager",
                created_ip="127.0.0.1",
            )
            with get_uow().transaction(actor="test_offer_photo_purge_storage") as session:
                storage_data.mark_storage_purged(session, storage_id=storage_id)

            with pytest.raises(ValueError, match="Storage object is not ready"):
                offer_photos.add_offer_photo(
                    offer_id=offer_id,
                    storage_id=storage_id,
                    user_id=user_id,
                    role="manager",
                    created_ip="127.0.0.1",
                )

            assert offer_photos.list_offer_photos(offer_id=offer_id) == []
            deleted = offer_photos.list_offer_photos(offer_id=offer_id, include_deleted=True)
            assert len(deleted) == 1
            assert deleted[0]["id"] == photo_id
            assert deleted[0]["deleted_at"] is not None
            assert _storage_row(storage_id)["status"] == "purged"
    finally:
        _cleanup_agency(agency_id, user_id)


def test_offer_photo_delete_keeps_shared_storage_until_last_active_ref() -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_shared")
    try:
        _, offer_a = _create_listing_and_offer(agency_id=agency_id, user_id=user_id, suffix="a")
        _, offer_b = _create_listing_and_offer(agency_id=agency_id, user_id=user_id, suffix="b")
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="shared",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            assert _usage_for_agency(agency_id) == 128
            photo_a = offer_photos.add_offer_photo(
                offer_id=offer_a,
                storage_id=storage_id,
            ).photo_id
            photo_b = offer_photos.add_offer_photo(
                offer_id=offer_b,
                storage_id=storage_id,
            ).photo_id

            assert offer_photos.delete_offer_photo(
                photo_id=photo_a,
                user_id=user_id,
                role="manager",
                created_ip="127.0.0.1",
            )
            assert _storage_row(storage_id)["status"] == "ready"
            assert _usage_for_agency(agency_id) == 128

            assert offer_photos.delete_offer_photo(
                photo_id=photo_b,
                user_id=user_id,
                role="manager",
                created_ip="127.0.0.1",
            )
            row = _storage_row(storage_id)
            assert row["status"] == "deleted"
            assert row["deleted_at"] is not None
            assert _usage_for_agency(agency_id) == 0
    finally:
        _cleanup_agency(agency_id, user_id)


def test_offer_photo_repeated_delete_does_not_double_decrement_usage() -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_repeat_delete")
    try:
        _, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix="repeat-delete",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="repeat-delete",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            photo_id = offer_photos.add_offer_photo(
                offer_id=offer_id,
                storage_id=storage_id,
            ).photo_id
            assert _usage_for_agency(agency_id) == 128
            assert offer_photos.delete_offer_photo(
                photo_id=photo_id,
                user_id=user_id,
                role="manager",
                created_ip="127.0.0.1",
            )
            deleted_row = _photo_row(photo_id)
            assert deleted_row["delete_origin"] == PHOTO_DELETE_ORIGIN_MANUAL
            assert _usage_for_agency(agency_id) == 0
            assert (
                offer_photos.delete_offer_photo(
                    photo_id=photo_id,
                    user_id=user_id,
                    role="manager",
                    created_ip="127.0.0.1",
                )
                is False
            )
            assert _usage_for_agency(agency_id) == 0
            assert _storage_event_count(storage_id, "deleted") == 1
            repeated_row = _photo_row(photo_id)
            assert repeated_row["delete_origin"] == PHOTO_DELETE_ORIGIN_MANUAL
            assert repeated_row["delete_parent_scope"] is None
            assert repeated_row["delete_parent_id"] is None
    finally:
        _cleanup_agency(agency_id, user_id)


def test_offer_photo_delete_api_uses_hmac_idempotency_without_duplicate_side_effects() -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_delete_idem")
    try:
        _, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix="delete-idem",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="delete-idem",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            photo_id = offer_photos.add_offer_photo(
                offer_id=offer_id,
                storage_id=storage_id,
            ).photo_id
            assert _usage_for_agency(agency_id) == 128

        key = f"offer-photo-delete:test:{uuid.uuid4().hex}"
        first = _delete_offer_photo_api(
            agency_id=agency_id,
            user_id=user_id,
            photo_id=photo_id,
            idempotency_key=key,
        )
        assert first.status_code == 204
        assert first.headers["Idempotency-Status"] == "created"
        assert _usage_for_agency(agency_id) == 0
        assert _storage_event_count(storage_id, "deleted") == 1

        replay = _delete_offer_photo_api(
            agency_id=agency_id,
            user_id=user_id,
            photo_id=photo_id,
            idempotency_key=key,
        )
        assert replay.status_code == 204
        assert replay.headers["Idempotency-Status"] == "replayed"
        assert _usage_for_agency(agency_id) == 0
        assert _storage_event_count(storage_id, "deleted") == 1

        different_key = _delete_offer_photo_api(
            agency_id=agency_id,
            user_id=user_id,
            photo_id=photo_id,
            idempotency_key=f"offer-photo-delete:test:{uuid.uuid4().hex}",
        )
        assert different_key.status_code == 404
        assert _usage_for_agency(agency_id) == 0
        assert _storage_event_count(storage_id, "deleted") == 1
    finally:
        _cleanup_agency(agency_id, user_id)


def test_offer_photo_attach_vs_delete_serializes_storage_aggregate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_concurrent_attach_delete")
    try:
        _, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix="concurrent-attach-delete",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="concurrent-attach-delete",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            photo_id = offer_photos.add_offer_photo(
                offer_id=offer_id,
                storage_id=storage_id,
            ).photo_id

        def _attach_duplicate() -> object:
            with use_security_context(agency_id=agency_id, is_superuser=False):
                return offer_photos.add_offer_photo(
                    offer_id=offer_id,
                    storage_id=storage_id,
                    user_id=user_id,
                    role="manager",
                    created_ip="127.0.0.1",
                )

        def _delete() -> object:
            with use_security_context(agency_id=agency_id, is_superuser=False):
                return offer_photos.delete_offer_photo(
                    photo_id=photo_id,
                    user_id=user_id,
                    role="manager",
                    created_ip="127.0.0.1",
                )

        _run_two_lifecycle_threads(monkeypatch, _attach_duplicate, _delete)

        statuses = _active_photo_storage_statuses(storage_id)
        assert all(status == "ready" for status in statuses)
        if _active_photo_count(storage_id) == 0:
            assert _storage_row(storage_id)["status"] == "deleted"
            assert _usage_for_agency(agency_id) == 0
        else:
            assert _storage_row(storage_id)["status"] == "ready"
            assert _usage_for_agency(agency_id) == 128
    finally:
        _cleanup_agency(agency_id, user_id)


def test_offer_photo_cascade_delete_vs_single_delete_serializes_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_concurrent_cascade_delete")
    try:
        _, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix="concurrent-cascade-delete",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="concurrent-cascade-delete",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            photo_id = offer_photos.add_offer_photo(
                offer_id=offer_id,
                storage_id=storage_id,
            ).photo_id

        def _delete_offer() -> object:
            with use_security_context(agency_id=agency_id, is_superuser=False):
                offers_service.delete_offer(offer_id, actor="test_concurrent_offer_delete")
                return "offer-deleted"

        def _delete_photo() -> object:
            with use_security_context(agency_id=agency_id, is_superuser=False):
                return offer_photos.delete_offer_photo(
                    photo_id=photo_id,
                    user_id=user_id,
                    role="manager",
                    created_ip="127.0.0.1",
                )

        _run_two_lifecycle_threads(monkeypatch, _delete_offer, _delete_photo)

        assert _active_photo_count(storage_id) == 0
        assert _storage_row(storage_id)["status"] == "deleted"
        assert _usage_for_agency(agency_id) == 0
        assert _storage_event_count(storage_id, "deleted") == 1
    finally:
        _cleanup_agency(agency_id, user_id)


def test_offer_photo_reattach_vs_delete_keeps_photo_and_storage_consistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_concurrent_reattach_delete")
    try:
        _, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix="concurrent-reattach-delete",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="concurrent-reattach-delete",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            photo_id = offer_photos.add_offer_photo(
                offer_id=offer_id,
                storage_id=storage_id,
            ).photo_id
            assert offer_photos.delete_offer_photo(
                photo_id=photo_id,
                user_id=user_id,
                role="manager",
                created_ip="127.0.0.1",
            )

        def _reattach() -> object:
            with use_security_context(agency_id=agency_id, is_superuser=False):
                return offer_photos.add_offer_photo(
                    offer_id=offer_id,
                    storage_id=storage_id,
                    user_id=user_id,
                    role="manager",
                    created_ip="127.0.0.1",
                )

        def _delete() -> object:
            with use_security_context(agency_id=agency_id, is_superuser=False):
                return offer_photos.delete_offer_photo(
                    photo_id=photo_id,
                    user_id=user_id,
                    role="manager",
                    created_ip="127.0.0.1",
                )

        _run_two_lifecycle_threads(monkeypatch, _reattach, _delete)

        statuses = _active_photo_storage_statuses(storage_id)
        assert all(status == "ready" for status in statuses)
        if _active_photo_count(storage_id) == 0:
            assert _storage_row(storage_id)["status"] == "deleted"
            assert _usage_for_agency(agency_id) == 0
        else:
            assert _storage_row(storage_id)["status"] == "ready"
            assert _usage_for_agency(agency_id) == 128
    finally:
        _cleanup_agency(agency_id, user_id)


def test_offer_delete_and_restore_soft_delete_photos_and_restore_storage() -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_restore")
    try:
        _, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix="restore",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="restore",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            photo_id = offer_photos.add_offer_photo(
                offer_id=offer_id,
                storage_id=storage_id,
            ).photo_id
            assert _usage_for_agency(agency_id) == 128
            offers_service.delete_offer(offer_id, actor="test_offer_delete")
            assert offer_photos.list_offer_photos(offer_id=offer_id) == []
            deleted = offer_photos.list_offer_photos(offer_id=offer_id, include_deleted=True)
            assert len(deleted) == 1
            assert deleted[0]["deleted_at"] is not None
            deleted_row = _photo_row(photo_id)
            assert deleted_row["delete_origin"] == PHOTO_DELETE_ORIGIN_OFFER_DELETED
            assert deleted_row["delete_parent_scope"] == PHOTO_DELETE_PARENT_SCOPE_OFFER
            assert deleted_row["delete_parent_id"] == offer_id
            assert _storage_row(storage_id)["status"] == "deleted"
            assert _usage_for_agency(agency_id) == 0

            offers_service.restore_offer(offer_id, actor="test_offer_restore")
            active = offer_photos.list_offer_photos(offer_id=offer_id)
            assert len(active) == 1
            assert active[0]["deleted_at"] is None
            restored_row = _photo_row(photo_id)
            assert restored_row["delete_origin"] is None
            assert restored_row["delete_parent_scope"] is None
            assert restored_row["delete_parent_id"] is None
            row = _storage_row(storage_id)
            assert row["status"] == "ready"
            assert row["deleted_at"] is None
            assert _usage_for_agency(agency_id) == 128
    finally:
        _cleanup_agency(agency_id, user_id)


def test_offer_restore_does_not_reactivate_purged_photo_storage() -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_restore_purged")
    try:
        _, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix="restore-purged",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="restore-purged",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            offer_photos.add_offer_photo(offer_id=offer_id, storage_id=storage_id)
            offers_service.delete_offer(offer_id, actor="test_offer_delete_purged_photo")
            with get_uow().transaction(actor="test_purge_deleted_photo_storage") as session:
                storage_data.mark_storage_purged(session, storage_id=storage_id)

            offers_service.restore_offer(offer_id, actor="test_offer_restore_purged_photo")

            assert offer_photos.list_offer_photos(offer_id=offer_id) == []
            deleted = offer_photos.list_offer_photos(offer_id=offer_id, include_deleted=True)
            assert len(deleted) == 1
            assert deleted[0]["deleted_at"] is not None
            assert _storage_row(storage_id)["status"] == "purged"
            assert _usage_for_agency(agency_id) == 0
    finally:
        _cleanup_agency(agency_id, user_id)


def test_offer_restore_does_not_restore_manually_deleted_photo() -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_manual_offer_restore")
    try:
        _, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix="manual-offer-restore",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="manual-offer-restore",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            photo_id = offer_photos.add_offer_photo(
                offer_id=offer_id,
                storage_id=storage_id,
            ).photo_id
            assert offer_photos.delete_offer_photo(
                photo_id=photo_id,
                user_id=user_id,
                role="manager",
                created_ip="127.0.0.1",
            )
            manual_row = _photo_row(photo_id)
            assert manual_row["delete_origin"] == PHOTO_DELETE_ORIGIN_MANUAL
            offers_service.delete_offer(offer_id, actor="test_manual_photo_offer_delete")
            offers_service.restore_offer(offer_id, actor="test_manual_photo_offer_restore")

            assert offer_photos.list_offer_photos(offer_id=offer_id) == []
            deleted = offer_photos.list_offer_photos(offer_id=offer_id, include_deleted=True)
            assert len(deleted) == 1
            row = _photo_row(photo_id)
            assert row["deleted_at"] is not None
            assert row["delete_origin"] == PHOTO_DELETE_ORIGIN_MANUAL
            assert row["delete_parent_scope"] is None
            assert row["delete_parent_id"] is None
            assert _storage_row(storage_id)["status"] == "deleted"
            assert _usage_for_agency(agency_id) == 0
    finally:
        _cleanup_agency(agency_id, user_id)


def test_listing_restore_does_not_restore_manually_deleted_photo() -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_manual_listing_restore")
    try:
        listing_id, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix="manual-listing-restore",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="manual-listing-restore",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            photo_id = offer_photos.add_offer_photo(
                offer_id=offer_id,
                storage_id=storage_id,
            ).photo_id
            assert offer_photos.delete_offer_photo(
                photo_id=photo_id,
                user_id=user_id,
                role="manager",
                created_ip="127.0.0.1",
            )
            listings_service.delete_listing(listing_id, actor="test_manual_photo_listing_delete")
            listings_service.restore_listing(listing_id, actor="test_manual_photo_listing_restore")

            assert offer_photos.list_offer_photos(offer_id=offer_id) == []
            row = _photo_row(photo_id)
            assert row["deleted_at"] is not None
            assert row["delete_origin"] == PHOTO_DELETE_ORIGIN_MANUAL
            assert row["delete_parent_scope"] is None
            assert row["delete_parent_id"] is None
            assert _storage_row(storage_id)["status"] == "deleted"
            assert _usage_for_agency(agency_id) == 0
    finally:
        _cleanup_agency(agency_id, user_id)


def test_offer_restore_does_not_restore_legacy_null_provenance_photo() -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_legacy_null_restore")
    try:
        _, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix="legacy-null-restore",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="legacy-null-restore",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            photo_id = offer_photos.add_offer_photo(
                offer_id=offer_id,
                storage_id=storage_id,
            ).photo_id
            offers_service.delete_offer(offer_id, actor="test_legacy_photo_offer_delete")
            with get_uow().transaction(actor="test_legacy_photo_null_provenance") as session:
                session.execute(
                    """
                    UPDATE offer_photos
                    SET delete_origin = NULL,
                        delete_parent_scope = NULL,
                        delete_parent_id = NULL
                    WHERE id = %s
                    """,
                    (photo_id,),
                )

            offers_service.restore_offer(offer_id, actor="test_legacy_photo_offer_restore")

            assert offer_photos.list_offer_photos(offer_id=offer_id) == []
            row = _photo_row(photo_id)
            assert row["deleted_at"] is not None
            assert row["delete_origin"] is None
            assert row["delete_parent_scope"] is None
            assert row["delete_parent_id"] is None
            assert _storage_row(storage_id)["status"] == "deleted"
            assert _usage_for_agency(agency_id) == 0
    finally:
        _cleanup_agency(agency_id, user_id)


def test_listing_delete_and_restore_reuses_offer_photo_lifecycle() -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_listing_restore")
    try:
        listing_id, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix="listing-restore",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="listing-restore",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            photo_id = offer_photos.add_offer_photo(
                offer_id=offer_id,
                storage_id=storage_id,
            ).photo_id
            assert _usage_for_agency(agency_id) == 128
            listings_service.delete_listing(listing_id, actor="test_listing_delete")
            assert offer_photos.list_offer_photos(offer_id=offer_id) == []
            deleted_row = _photo_row(photo_id)
            assert deleted_row["delete_origin"] == PHOTO_DELETE_ORIGIN_LISTING_DELETED
            assert deleted_row["delete_parent_scope"] == PHOTO_DELETE_PARENT_SCOPE_LISTING
            assert deleted_row["delete_parent_id"] == listing_id
            assert _storage_row(storage_id)["status"] == "deleted"
            assert _usage_for_agency(agency_id) == 0

            listings_service.restore_listing(listing_id, actor="test_listing_restore")
            active = offer_photos.list_offer_photos(offer_id=offer_id)
            assert len(active) == 1
            restored_row = _photo_row(photo_id)
            assert restored_row["delete_origin"] is None
            assert restored_row["delete_parent_scope"] is None
            assert restored_row["delete_parent_id"] is None
            row = _storage_row(storage_id)
            assert row["status"] == "ready"
            assert row["deleted_at"] is None
            assert _usage_for_agency(agency_id) == 128
    finally:
        _cleanup_agency(agency_id, user_id)


def test_offer_purge_leaves_photo_storage_deleted_for_gc() -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_offer_purge")
    try:
        _, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix="offer-purge",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="offer-purge",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            photo_id = offer_photos.add_offer_photo(
                offer_id=offer_id,
                storage_id=storage_id,
            ).photo_id
            offers_service.purge_offer(offer_id, actor="test_offer_photo_purge")

        with admin_transaction() as session:
            photo_row = session.execute(
                "SELECT id FROM offer_photos WHERE id = %s",
                (photo_id,),
            ).fetchone()
        assert photo_row is None
        row = _storage_row(storage_id)
        assert row["status"] == "deleted"
        assert row["deleted_at"] is not None
        assert _usage_for_agency(agency_id) == 0
        assert _storage_event_count(storage_id, "deleted") == 1
    finally:
        _cleanup_agency(agency_id, user_id)


def test_listing_purge_leaves_photo_storage_deleted_for_gc() -> None:
    ensure_schema()
    agency_id, user_id = _seed_agency("photo_listing_purge")
    try:
        listing_id, offer_id = _create_listing_and_offer(
            agency_id=agency_id,
            user_id=user_id,
            suffix="listing-purge",
        )
        storage_id = _create_ready_storage(
            agency_id=agency_id,
            user_id=user_id,
            suffix="listing-purge",
        )
        with use_security_context(agency_id=agency_id, is_superuser=False):
            photo_id = offer_photos.add_offer_photo(
                offer_id=offer_id,
                storage_id=storage_id,
            ).photo_id
            listings_service.purge_listing(listing_id, actor="test_listing_photo_purge")

        with admin_transaction() as session:
            photo_row = session.execute(
                "SELECT id FROM offer_photos WHERE id = %s",
                (photo_id,),
            ).fetchone()
        assert photo_row is None
        row = _storage_row(storage_id)
        assert row["status"] == "deleted"
        assert row["deleted_at"] is not None
        assert _usage_for_agency(agency_id) == 0
        assert _storage_event_count(storage_id, "deleted") == 1
    finally:
        _cleanup_agency(agency_id, user_id)
