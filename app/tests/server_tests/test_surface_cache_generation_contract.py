from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    cleanup_import_test_agency,
    create_agency,
    create_manager_user,
    ensure_django,
)

ensure_django()

from core.data import client_repo_write, offer_repo_write  # noqa: E402
from core.data.surface_cache_generation import (  # noqa: E402
    CLIENTS_SURFACE,
    INVITES_ACTOR_SURFACE,
    INVITES_AGENCY_SURFACE,
    LISTINGS_SURFACE,
    NOTIFICATIONS_ACTOR_SURFACE,
    NOTIFICATIONS_AGENCY_SURFACE,
    NOTIFICATIONS_GLOBAL_SURFACE,
    NOTIFICATIONS_OWNER_SURFACE,
    NOTIFICATIONS_ROLE_SURFACE,
    USERS_SURFACE,
    actor_scope_key,
    agency_scope_key,
    owner_scope_key,
    read_generation,
    role_scope_key,
)
from server.pg.schema import ensure_schema  # noqa: E402
from server.pg.uow import get_uow, use_security_context  # noqa: E402
from server.services import clients, demandes, listings, notifications, offers  # noqa: E402


def _make_user_and_agency(prefix: str) -> tuple[int, int, object]:
    conn = admin_conn()
    try:
        agency_id = create_agency(
            conn,
            f"{prefix[:6]}{uuid.uuid4().hex[:6]}",
            f"{prefix} Agency",
        )
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"{prefix.lower()}_{uuid.uuid4().hex[:8]}",
            password="StrongTestPass_123!",
        )
        conn.commit()
    finally:
        conn.close()
    user = get_user_model().objects.get(id=user_id)
    return agency_id, user_id, user


def _cleanup_agency(*, agency_id: int, user_id: int) -> None:
    cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)


def _read_surface_generation(*, agency_id: int | None, surface: str, scope_key: str) -> int:
    with use_security_context(agency_id=agency_id, is_superuser=False):
        with get_uow().session() as session:
            return int(
                read_generation(
                    session,
                    surface=surface,
                    scope_key=scope_key,
                    agency_id=agency_id,
                )
            )


class _FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = list(rows)

    def fetchall(self) -> list[dict[str, object]]:
        return list(self._rows)

    def fetchone(self) -> dict[str, object] | None:
        return dict(self._rows[0]) if self._rows else None


class _FakeSession:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = list(rows)
        self.executed: list[tuple[str, object]] = []
        self.rowcount = len(rows)

    def execute(self, sql: str, params: object) -> _FakeResult:
        self.executed.append((sql, params))
        return _FakeResult(self._rows)


def test_clients_surface_generation_is_tenant_scoped_and_tracks_demande_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_a, user_a_id, _user_a = _make_user_and_agency("IMPSGA")
    agency_b, user_b_id, _user_b = _make_user_and_agency("IMPSGB")
    try:
        assert (
            _read_surface_generation(
                agency_id=agency_a,
                surface=CLIENTS_SURFACE,
                scope_key=agency_scope_key(agency_a),
            )
            == 1
        )
        assert (
            _read_surface_generation(
                agency_id=agency_b,
                surface=CLIENTS_SURFACE,
                scope_key=agency_scope_key(agency_b),
            )
            == 1
        )

        with use_security_context(agency_id=agency_a, is_superuser=False):
            client_id = clients.upsert_client(
                {
                    "family_name": "Scoped Client",
                    "phone": "0555099001",
                    "status": "active",
                }
            )

        assert (
            _read_surface_generation(
                agency_id=agency_a,
                surface=CLIENTS_SURFACE,
                scope_key=agency_scope_key(agency_a),
            )
            == 2
        )
        assert (
            _read_surface_generation(
                agency_id=agency_b,
                surface=CLIENTS_SURFACE,
                scope_key=agency_scope_key(agency_b),
            )
            == 1
        )

        monkeypatch.setattr(
            "server.services.demandes.enqueue_rebuild_demande_pairs",
            lambda _demande_id: None,
        )
        with use_security_context(agency_id=agency_a, is_superuser=False):
            demandes.create_demande(
                client_id,
                {
                    "type": "apartment",
                    "action": "buy",
                    "wilaya": "Algiers",
                    "locations": "Hydra",
                    "beds_min": 2,
                    "surface_min": 60,
                    "surface_max": 120,
                    "budget_min": 100,
                    "budget_max": 300,
                    "floor_min": 0,
                    "floor_max": 8,
                    "elevator": 1,
                    "accessibility_required": 1,
                },
            )

        assert (
            _read_surface_generation(
                agency_id=agency_a,
                surface=CLIENTS_SURFACE,
                scope_key=agency_scope_key(agency_a),
            )
            == 3
        )
        assert (
            _read_surface_generation(
                agency_id=agency_b,
                surface=CLIENTS_SURFACE,
                scope_key=agency_scope_key(agency_b),
            )
            == 1
        )
    finally:
        _cleanup_agency(agency_id=agency_a, user_id=user_a_id)
        _cleanup_agency(agency_id=agency_b, user_id=user_b_id)


def test_listings_surface_generation_is_tenant_scoped_and_tracks_offer_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    agency_a, user_a_id, _user_a = _make_user_and_agency("IMPSLA")
    agency_b, user_b_id, _user_b = _make_user_and_agency("IMPSLB")
    try:
        assert (
            _read_surface_generation(
                agency_id=agency_a,
                surface=LISTINGS_SURFACE,
                scope_key=agency_scope_key(agency_a),
            )
            == 1
        )
        assert (
            _read_surface_generation(
                agency_id=agency_b,
                surface=LISTINGS_SURFACE,
                scope_key=agency_scope_key(agency_b),
            )
            == 1
        )

        with use_security_context(agency_id=agency_a, is_superuser=False):
            listing_id = listings.upsert_listing(
                {
                    "family_name": "Scoped Listing",
                    "phone": "0666099001",
                    "status": "available",
                }
            )

        assert (
            _read_surface_generation(
                agency_id=agency_a,
                surface=LISTINGS_SURFACE,
                scope_key=agency_scope_key(agency_a),
            )
            == 2
        )
        assert (
            _read_surface_generation(
                agency_id=agency_b,
                surface=LISTINGS_SURFACE,
                scope_key=agency_scope_key(agency_b),
            )
            == 1
        )

        monkeypatch.setattr(
            "server.services.offers.enqueue_rebuild_offer_pairs",
            lambda _offer_id: None,
        )
        with use_security_context(agency_id=agency_a, is_superuser=False):
            offers.create_offer(
                listing_id,
                {
                    "type": "apartment",
                    "action": "sell",
                    "status": "available",
                    "wilaya": "Algiers",
                    "location": "Hydra",
                    "beds": 3,
                    "surface": 90,
                    "budget": 200,
                    "floor": 2,
                    "elevator": 1,
                    "accessibility_supported": 1,
                },
            )

        assert (
            _read_surface_generation(
                agency_id=agency_a,
                surface=LISTINGS_SURFACE,
                scope_key=agency_scope_key(agency_a),
            )
            == 3
        )
        assert (
            _read_surface_generation(
                agency_id=agency_b,
                surface=LISTINGS_SURFACE,
                scope_key=agency_scope_key(agency_b),
            )
            == 1
        )
    finally:
        _cleanup_agency(agency_id=agency_a, user_id=user_a_id)
        _cleanup_agency(agency_id=agency_b, user_id=user_b_id)


def test_client_batch_insert_bumps_every_affected_agency_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    session = _FakeSession([{"id": 11}, {"id": 12}])
    monkeypatch.setattr(
        client_repo_write,
        "bump_generations",
        lambda _session, *, surface, scopes: captured.update(
            {"surface": surface, "scopes": list(scopes)}
        )
        or {},
    )

    ids = client_repo_write.insert_clients_batch(
        session,
        [
            {"agency_id": 101, "family_name": "A", "phone": "0555001001"},
            {"agency_id": 202, "family_name": "B", "phone": "0555001002"},
        ],
    )

    assert ids == [11, 12]
    assert captured == {
        "surface": CLIENTS_SURFACE,
        "scopes": [
            (agency_scope_key(101), 101),
            (agency_scope_key(202), 202),
        ],
    }


def test_offer_batch_insert_bumps_every_returned_agency_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    session = _FakeSession(
        [
            {"id": 21, "wilaya_id": 16, "location": "Hydra", "agency_id": 301},
            {"id": 22, "wilaya_id": 31, "location": "Bir Mourad Rais", "agency_id": 404},
        ]
    )
    monkeypatch.setattr(
        offer_repo_write,
        "populate_location_links_batch",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        offer_repo_write,
        "bump_generations",
        lambda _session, *, surface, scopes: captured.update(
            {"surface": surface, "scopes": list(scopes)}
        )
        or {},
    )

    ids = offer_repo_write.insert_offers_batch(
        session,
        [
            {
                "listing_id": 1001,
                "type": "apartment",
                "type_id": 1,
                "action": "sell",
                "action_id": 1,
                "status": "available",
                "wilaya": "Algiers",
                "wilaya_id": 16,
                "location": "Hydra",
                "beds": 3,
                "surface": 90,
                "budget": 200,
                "furnished": "",
                "floor": 2,
                "elevator": 1,
                "accessibility_supported": 1,
            },
            {
                "listing_id": 2002,
                "type": "apartment",
                "type_id": 1,
                "action": "sell",
                "action_id": 1,
                "status": "available",
                "wilaya": "Oran",
                "wilaya_id": 31,
                "location": "Bir Mourad Rais",
                "beds": 4,
                "surface": 120,
                "budget": 320,
                "furnished": "",
                "floor": 5,
                "elevator": 1,
                "accessibility_supported": 1,
            },
        ],
    )

    assert ids == [21, 22]
    assert captured == {
        "surface": LISTINGS_SURFACE,
        "scopes": [
            (agency_scope_key(301), 301),
            (agency_scope_key(404), 404),
        ],
    }


def test_notification_surface_generations_bump_only_relevant_scopes() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPSNT")
    role = str(getattr(user, "role", "") or "")
    try:
        actor_generation = lambda: _read_surface_generation(  # noqa: E731
            agency_id=agency_id,
            surface=NOTIFICATIONS_ACTOR_SURFACE,
            scope_key=actor_scope_key(user_id),
        )
        agency_generation = lambda: _read_surface_generation(  # noqa: E731
            agency_id=agency_id,
            surface=NOTIFICATIONS_AGENCY_SURFACE,
            scope_key=agency_scope_key(agency_id),
        )
        role_generation = lambda: _read_surface_generation(  # noqa: E731
            agency_id=agency_id,
            surface=NOTIFICATIONS_ROLE_SURFACE,
            scope_key=role_scope_key(agency_id=agency_id, role=role),
        )
        owner_generation = lambda: _read_surface_generation(  # noqa: E731
            agency_id=agency_id,
            surface=NOTIFICATIONS_OWNER_SURFACE,
            scope_key=owner_scope_key(agency_id=agency_id),
        )

        assert actor_generation() == 1
        assert agency_generation() == 1
        assert role_generation() == 1
        assert owner_generation() == 1

        with use_security_context(agency_id=agency_id, is_superuser=False):
            actor_notification_id = notifications.insert_notification(
                agency_id=agency_id,
                scope="user",
                user_id=user_id,
                event_type="test.notifications.actor_scope",
                title="Actor scope",
                body="Actor notification",
            )
        assert isinstance(actor_notification_id, int) and actor_notification_id > 0
        assert actor_generation() == 2
        assert agency_generation() == 1
        assert role_generation() == 1
        assert owner_generation() == 1

        with use_security_context(agency_id=agency_id, is_superuser=False):
            notifications.insert_notification(
                agency_id=agency_id,
                scope="agency",
                event_type="test.notifications.agency_scope",
                title="Agency scope",
                body="Agency notification",
            )
        assert actor_generation() == 2
        assert agency_generation() == 2
        assert role_generation() == 1
        assert owner_generation() == 1

        with use_security_context(agency_id=agency_id, is_superuser=False):
            notifications.insert_notification(
                agency_id=agency_id,
                scope="role",
                role=role,
                event_type="test.notifications.role_scope",
                title="Role scope",
                body="Role notification",
            )
        assert actor_generation() == 2
        assert agency_generation() == 2
        assert role_generation() == 2
        assert owner_generation() == 1

        with use_security_context(agency_id=agency_id, is_superuser=False):
            notifications.insert_notification(
                agency_id=agency_id,
                scope="owner",
                event_type="test.notifications.owner_scope",
                title="Owner scope",
                body="Owner notification",
            )
        assert actor_generation() == 2
        assert agency_generation() == 2
        assert role_generation() == 2
        assert owner_generation() == 2

        with use_security_context(agency_id=agency_id, is_superuser=False):
            updated = notifications.mark_notifications_read(
                agency_id=agency_id,
                user_id=user_id,
                role=role,
                is_owner=bool(getattr(user, "is_owner", False)),
                is_superuser=False,
                notification_ids=[actor_notification_id],
                mark_all=False,
            )
        assert updated == 1
        assert actor_generation() == 3
        assert agency_generation() == 2
        assert role_generation() == 2
        assert owner_generation() == 2
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_surface_generation_api_and_cache_key_paths_require_explicit_scopes() -> None:
    surface_source = Path("core/data/surface_cache_generation.py").read_text(encoding="utf-8")
    client_read_source = Path("core/data/client_repo_read.py").read_text(encoding="utf-8")
    listing_read_source = Path("core/data/listing_repo_read.py").read_text(encoding="utf-8")
    users_queries_source = Path("server/services/users_queries.py").read_text(encoding="utf-8")
    invites_source = Path("server/services/registration_lifecycle.py").read_text(encoding="utf-8")
    notifications_source = Path("server/services/notifications_queries.py").read_text(
        encoding="utf-8"
    )
    clients_service_source = Path("server/services/clients.py").read_text(encoding="utf-8")
    listings_service_source = Path("server/services/listings.py").read_text(encoding="utf-8")
    clients_view_source = Path("server/api/views_clients_list.py").read_text(encoding="utf-8")
    listings_view_source = Path("server/api/views_listings_list.py").read_text(encoding="utf-8")
    users_view_source = Path("server/api/views_users.py").read_text(encoding="utf-8")
    invites_view_source = Path("server/api/views_user_invites.py").read_text(encoding="utf-8")
    notifications_view_source = Path("server/api/views_notifications.py").read_text(
        encoding="utf-8"
    )
    cache_control_source = Path("server/services/cache_control.py").read_text(encoding="utf-8")

    assert "current_setting('app.current_agency_id'" not in surface_source
    assert "agency_scope_key" in surface_source
    assert "actor_scope_key" in surface_source
    assert "global_scope_key" in surface_source
    assert "read_generations(" in surface_source
    assert "scope_key=agency_scope_key(resolved_agency_id)" in client_read_source
    assert "scope_key=agency_scope_key(resolved_agency_id)" in listing_read_source
    assert "def get_clients_surface_generation(*, agency_id: int)" in clients_service_source
    assert "def get_listings_surface_generation(*, agency_id: int)" in listings_service_source
    assert "def get_users_surface_generation(*, agency_id: int)" in users_queries_source
    assert "def get_pending_invites_surface_generation(*, actor: object | None)" in invites_source
    assert "def get_notifications_scope_generations(" in notifications_source
    assert (
        "get_clients_surface_generation(agency_id=int(agency_id or 0))" not in clients_view_source
    )
    assert (
        "get_listings_surface_generation(agency_id=int(agency_id or 0))" not in listings_view_source
    )
    assert "get_clients_surface_generation(agency_id=agency_id)" in clients_view_source
    assert "get_listings_surface_generation(agency_id=agency_id)" in listings_view_source
    assert "use_cache = agency_id is not None" in clients_view_source
    assert "use_cache = agency_id is not None" in listings_view_source
    assert "get_users_surface_generation(agency_id=int(cached_agency_id))" in users_view_source
    assert "get_pending_invites_surface_generation(actor=request.user)" in invites_view_source
    assert "get_notifications_scope_generations(" in notifications_view_source
    assert "_NAMESPACE_LOCAL_CACHE" not in cache_control_source


def test_generalized_surface_names_are_declared() -> None:
    surface_source = Path("core/data/surface_cache_generation.py").read_text(encoding="utf-8")

    assert USERS_SURFACE in surface_source
    assert INVITES_AGENCY_SURFACE in surface_source
    assert INVITES_ACTOR_SURFACE in surface_source
    assert NOTIFICATIONS_AGENCY_SURFACE in surface_source
    assert NOTIFICATIONS_ACTOR_SURFACE in surface_source
    assert NOTIFICATIONS_GLOBAL_SURFACE in surface_source
    assert "scope_key" in surface_source
    assert "PRIMARY KEY (surface, scope_key)" in Path(
        "server/alembic/versions/20260330_0029_surface_cache_generation_scopes.py"
    ).read_text(encoding="utf-8")


def test_listings_service_keeps_offer_table_reads_in_data_layer() -> None:
    listings_service_source = Path("server/services/listings.py").read_text(encoding="utf-8")
    offer_read_source = Path("core/data/offer_repo_read.py").read_text(encoding="utf-8")

    assert "session.execute(" not in listings_service_source
    assert "use_precomputed" not in listings_service_source
    assert "get_offer_ids_for_listing" in offer_read_source
    assert "get_offer_wilaya_ids_for_listing" in offer_read_source
