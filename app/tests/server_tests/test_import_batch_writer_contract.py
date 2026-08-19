# ruff: noqa: E402
from __future__ import annotations

import uuid

import pytest

pytest.importorskip("psycopg", reason="batch writer contract tests require Postgres")

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    cleanup_import_test_agency,
    create_agency,
    ensure_django,
)

ensure_django()

from core.contracts.import_batch_refs import CreatedRowRef  # noqa: E402
from core.data import client_repo_write, listing_repo_write  # noqa: E402
from core.data.demande_repo_write_create import (  # noqa: E402
    insert_demandes_batch,
    insert_demandes_batch_refs,
)
from core.data.offer_repo_write import insert_offers_batch, insert_offers_batch_refs  # noqa: E402
from server.pg.schema import ensure_schema  # noqa: E402
from server.services.import_load_policy import (
    remember_created_anchor_keys,
    timed_insert_batch_rows,
)  # noqa: E402
from server.services.import_types import ImportLoadOutcome  # noqa: E402


class _ConnectionSession:
    def __init__(self, conn) -> None:
        self._conn = conn

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        cursor = self._conn.cursor()
        try:
            cursor.executemany(*args, **kwargs)
            return cursor
        except Exception:
            cursor.close()
            raise


def _cleanup_agency_data(*, agency_id: int) -> None:
    cleanup_import_test_agency(agency_id=agency_id)


def test_client_and_listing_batch_writers_return_ids_in_input_order() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    conn = admin_conn()
    agency_id = 0
    try:
        session = _ConnectionSession(conn)
        agency_id = create_agency(conn, f"IMPBW_{suffix}", f"Batch Writer {suffix}")
        conn.commit()

        client_rows = [
            {"agency_id": agency_id, "family_name": "Client B", "phone": f"05558{suffix[:5]}1"},
            {"agency_id": agency_id, "family_name": "Client A", "phone": f"05558{suffix[:5]}2"},
        ]
        client_ids = client_repo_write.insert_clients_batch(session, client_rows)
        client_phone_rows = conn.execute(
            "SELECT id, phone FROM clients WHERE id = ANY(%s)",
            (client_ids,),
        ).fetchall()
        phone_by_client_id = {int(row["id"]): str(row["phone"]) for row in client_phone_rows}

        listing_rows = [
            {"agency_id": agency_id, "family_name": "Listing B", "phone": f"05559{suffix[:5]}1"},
            {"agency_id": agency_id, "family_name": "Listing A", "phone": f"05559{suffix[:5]}2"},
        ]
        listing_ids = listing_repo_write.insert_listings_batch(session, listing_rows)
        listing_phone_rows = conn.execute(
            "SELECT id, phone FROM listings WHERE id = ANY(%s)",
            (listing_ids,),
        ).fetchall()
        phone_by_listing_id = {int(row["id"]): str(row["phone"]) for row in listing_phone_rows}
        conn.commit()

        assert [phone_by_client_id[int(client_id)] for client_id in client_ids] == [
            str(row["phone"]) for row in client_rows
        ]
        assert [phone_by_listing_id[int(listing_id)] for listing_id in listing_ids] == [
            str(row["phone"]) for row in listing_rows
        ]
    finally:
        conn.close()
        if agency_id:
            _cleanup_agency_data(agency_id=agency_id)


def test_client_and_listing_batch_ref_writers_preserve_explicit_source_ordinals() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    conn = admin_conn()
    agency_id = 0
    try:
        session = _ConnectionSession(conn)
        agency_id = create_agency(conn, f"IMPBWR_{suffix}", f"Batch Writer Ref {suffix}")
        conn.commit()

        client_rows = [
            {"agency_id": agency_id, "family_name": "Client Ref B", "phone": f"05548{suffix[:5]}1"},
            {"agency_id": agency_id, "family_name": "Client Ref A", "phone": f"05548{suffix[:5]}2"},
        ]
        client_refs = client_repo_write.insert_clients_batch_refs(
            session,
            client_rows,
            source_ordinals=[7, 3],
        )
        client_phone_rows = conn.execute(
            "SELECT id, phone FROM clients WHERE id = ANY(%s)",
            ([int(ref.created_id) for ref in client_refs],),
        ).fetchall()
        phone_by_client_id = {int(row["id"]): str(row["phone"]) for row in client_phone_rows}

        listing_rows = [
            {
                "agency_id": agency_id,
                "family_name": "Listing Ref B",
                "phone": f"05549{suffix[:5]}1",
            },
            {
                "agency_id": agency_id,
                "family_name": "Listing Ref A",
                "phone": f"05549{suffix[:5]}2",
            },
        ]
        listing_refs = listing_repo_write.insert_listings_batch_refs(
            session,
            listing_rows,
            source_ordinals=[11, 2],
        )
        listing_phone_rows = conn.execute(
            "SELECT id, phone FROM listings WHERE id = ANY(%s)",
            ([int(ref.created_id) for ref in listing_refs],),
        ).fetchall()
        phone_by_listing_id = {int(row["id"]): str(row["phone"]) for row in listing_phone_rows}
        conn.commit()

        assert {
            int(ref.source_ordinal): phone_by_client_id[int(ref.created_id)] for ref in client_refs
        } == {7: str(client_rows[0]["phone"]), 3: str(client_rows[1]["phone"])}
        assert {
            int(ref.source_ordinal): phone_by_listing_id[int(ref.created_id)]
            for ref in listing_refs
        } == {11: str(listing_rows[0]["phone"]), 2: str(listing_rows[1]["phone"])}
    finally:
        conn.close()
        if agency_id:
            _cleanup_agency_data(agency_id=agency_id)


def test_demande_and_offer_batch_writers_return_ids_in_input_order() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    conn = admin_conn()
    agency_id = 0
    try:
        session = _ConnectionSession(conn)
        agency_id = create_agency(conn, f"IMPBW2_{suffix}", f"Batch Writer 2 {suffix}")
        conn.commit()

        client_ids = client_repo_write.insert_clients_batch(
            session,
            [
                {
                    "agency_id": agency_id,
                    "family_name": "Demande Parent A",
                    "phone": f"05557{suffix[:5]}1",
                },
                {
                    "agency_id": agency_id,
                    "family_name": "Demande Parent B",
                    "phone": f"05557{suffix[:5]}2",
                },
            ],
        )
        listing_ids = listing_repo_write.insert_listings_batch(
            session,
            [
                {
                    "agency_id": agency_id,
                    "family_name": "Offer Parent A",
                    "phone": f"05556{suffix[:5]}1",
                },
                {
                    "agency_id": agency_id,
                    "family_name": "Offer Parent B",
                    "phone": f"05556{suffix[:5]}2",
                },
            ],
        )

        demande_rows = [
            {
                "client_id": int(client_ids[1]),
                "type": "apartment",
                "type_id": 1,
                "action": "buy",
                "action_id": 1,
                "wilaya": "16",
                "wilaya_id": 16,
                "locations": "Hydra",
                "budget_max": 1000000,
                "surface_min": 80,
                "remarks": "demande-b",
            },
            {
                "client_id": int(client_ids[0]),
                "type": "villa",
                "type_id": 1,
                "action": "buy",
                "action_id": 1,
                "wilaya": "16",
                "wilaya_id": 16,
                "locations": "Cheraga",
                "budget_max": 2000000,
                "surface_min": 120,
                "remarks": "demande-a",
            },
        ]
        demande_ids = insert_demandes_batch(session, demande_rows)
        demande_parent_rows = conn.execute(
            "SELECT id, client_id FROM demandes WHERE id = ANY(%s)",
            (demande_ids,),
        ).fetchall()
        client_by_demande_id = {
            int(row["id"]): int(row["client_id"]) for row in demande_parent_rows
        }

        offer_rows = [
            {
                "listing_id": int(listing_ids[1]),
                "type": "apartment",
                "type_id": 1,
                "action": "sale",
                "action_id": 1,
                "status": "available",
                "wilaya": "16",
                "wilaya_id": 16,
                "location": "Hydra",
                "beds": 2,
                "surface": 75,
                "budget": 120000,
                "floor": 3,
                "remarks": "offer-b",
            },
            {
                "listing_id": int(listing_ids[0]),
                "type": "villa",
                "type_id": 1,
                "action": "sale",
                "action_id": 1,
                "status": "available",
                "wilaya": "16",
                "wilaya_id": 16,
                "location": "Cheraga",
                "beds": 4,
                "surface": 180,
                "budget": 8000000,
                "floor": 1,
                "remarks": "offer-a",
            },
        ]
        offer_ids = insert_offers_batch(session, offer_rows)
        offer_parent_rows = conn.execute(
            "SELECT id, listing_id FROM offers WHERE id = ANY(%s)",
            (offer_ids,),
        ).fetchall()
        listing_by_offer_id = {int(row["id"]): int(row["listing_id"]) for row in offer_parent_rows}
        conn.commit()

        assert [client_by_demande_id[int(demande_id)] for demande_id in demande_ids] == [
            int(row["client_id"]) for row in demande_rows
        ]
        assert [listing_by_offer_id[int(offer_id)] for offer_id in offer_ids] == [
            int(row["listing_id"]) for row in offer_rows
        ]
    finally:
        conn.close()
        if agency_id:
            _cleanup_agency_data(agency_id=agency_id)


def test_demande_and_offer_batch_ref_writers_preserve_explicit_source_ordinals() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    conn = admin_conn()
    agency_id = 0
    try:
        session = _ConnectionSession(conn)
        agency_id = create_agency(conn, f"IMPBWR2_{suffix}", f"Batch Writer Ref 2 {suffix}")
        conn.commit()

        client_ids = client_repo_write.insert_clients_batch(
            session,
            [
                {
                    "agency_id": agency_id,
                    "family_name": "Demande Ref Parent A",
                    "phone": f"05547{suffix[:5]}1",
                },
                {
                    "agency_id": agency_id,
                    "family_name": "Demande Ref Parent B",
                    "phone": f"05547{suffix[:5]}2",
                },
            ],
        )
        listing_ids = listing_repo_write.insert_listings_batch(
            session,
            [
                {
                    "agency_id": agency_id,
                    "family_name": "Offer Ref Parent A",
                    "phone": f"05546{suffix[:5]}1",
                },
                {
                    "agency_id": agency_id,
                    "family_name": "Offer Ref Parent B",
                    "phone": f"05546{suffix[:5]}2",
                },
            ],
        )

        demande_rows = [
            {
                "client_id": int(client_ids[1]),
                "type": "apartment",
                "type_id": 1,
                "action": "buy",
                "action_id": 1,
                "wilaya": "16",
                "wilaya_id": 16,
                "locations": "Hydra",
                "budget_max": 1000000,
                "surface_min": 80,
                "remarks": "demande-ref-b",
            },
            {
                "client_id": int(client_ids[0]),
                "type": "villa",
                "type_id": 1,
                "action": "buy",
                "action_id": 1,
                "wilaya": "16",
                "wilaya_id": 16,
                "locations": "Cheraga",
                "budget_max": 2000000,
                "surface_min": 120,
                "remarks": "demande-ref-a",
            },
        ]
        demande_refs = insert_demandes_batch_refs(
            session,
            demande_rows,
            source_ordinals=[5, 1],
        )
        demande_parent_rows = conn.execute(
            "SELECT id, client_id FROM demandes WHERE id = ANY(%s)",
            ([int(ref.created_id) for ref in demande_refs],),
        ).fetchall()
        client_by_demande_id = {
            int(row["id"]): int(row["client_id"]) for row in demande_parent_rows
        }

        offer_rows = [
            {
                "listing_id": int(listing_ids[1]),
                "type": "apartment",
                "type_id": 1,
                "action": "sale",
                "action_id": 1,
                "status": "available",
                "wilaya": "16",
                "wilaya_id": 16,
                "location": "Hydra",
                "beds": 2,
                "surface": 75,
                "budget": 120000,
                "floor": 3,
                "remarks": "offer-ref-b",
            },
            {
                "listing_id": int(listing_ids[0]),
                "type": "villa",
                "type_id": 1,
                "action": "sale",
                "action_id": 1,
                "status": "available",
                "wilaya": "16",
                "wilaya_id": 16,
                "location": "Cheraga",
                "beds": 4,
                "surface": 180,
                "budget": 8000000,
                "floor": 1,
                "remarks": "offer-ref-a",
            },
        ]
        offer_refs = insert_offers_batch_refs(
            session,
            offer_rows,
            source_ordinals=[6, 4],
        )
        offer_parent_rows = conn.execute(
            "SELECT id, listing_id FROM offers WHERE id = ANY(%s)",
            ([int(ref.created_id) for ref in offer_refs],),
        ).fetchall()
        listing_by_offer_id = {int(row["id"]): int(row["listing_id"]) for row in offer_parent_rows}
        conn.commit()

        assert {
            int(ref.source_ordinal): client_by_demande_id[int(ref.created_id)]
            for ref in demande_refs
        } == {5: int(demande_rows[0]["client_id"]), 1: int(demande_rows[1]["client_id"])}
        assert {
            int(ref.source_ordinal): listing_by_offer_id[int(ref.created_id)] for ref in offer_refs
        } == {6: int(offer_rows[0]["listing_id"]), 4: int(offer_rows[1]["listing_id"])}
    finally:
        conn.close()
        if agency_id:
            _cleanup_agency_data(agency_id=agency_id)


def test_timed_insert_batch_rows_rejects_partial_returned_ids() -> None:
    with pytest.raises(ValueError, match="returned 1 ids for 2 input rows"):
        timed_insert_batch_rows(
            write_session=object(),
            entity_type="client",
            batch_rows=[{"row": 1}, {"row": 2}],
            load_outcome=ImportLoadOutcome(),
            insert_batch_fn=lambda **_kwargs: [101],
        )


def test_remember_created_anchor_keys_rejects_cardinality_mismatch() -> None:
    with pytest.raises(ValueError, match="returned 1 created-row refs for 2 input rows"):
        remember_created_anchor_keys(
            created_anchor_map={},
            batch_entries=[
                {"row": 1, "data": {"phone": "0555001001"}, "anchor_keys": ["phone:1"]},
                {"row": 2, "data": {"phone": "0555001002"}, "anchor_keys": ["phone:2"]},
            ],
            created_rows=[CreatedRowRef(source_ordinal=0, created_id=501)],
        )


def test_remember_created_anchor_keys_uses_source_ordinal_instead_of_result_order() -> None:
    created_anchor_map: dict[str, int] = {}

    remember_created_anchor_keys(
        created_anchor_map=created_anchor_map,
        batch_entries=[
            {"row": 1, "data": {"phone": "0555001001"}, "anchor_keys": ["phone:1"]},
            {"row": 2, "data": {"phone": "0555001002"}, "anchor_keys": ["phone:2"]},
        ],
        created_rows=[
            CreatedRowRef(source_ordinal=1, created_id=7002),
            CreatedRowRef(source_ordinal=0, created_id=7001),
        ],
    )

    assert created_anchor_map == {"phone:1": 7001, "phone:2": 7002}
