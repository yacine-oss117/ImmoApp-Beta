from __future__ import annotations

import uuid

import pytest

pytest.importorskip(
    "psycopg",
    reason="match artifact pipeline integration tests require server dependencies",
)
pytest.importorskip(
    "cryptography",
    reason="match artifact pipeline integration tests require full server dependencies",
)

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    cleanup_import_test_agency,
    create_agency,
    ensure_django,
)
from core.data import client_repo_write as client_write
from core.data import demande_repo_write as demande_write
from core.data import listing_repo_write as listing_write
from core.data import match_artifact_pipeline
from core.data import match_candidates as match_candidates_data
from core.data import match_pairs as match_pairs_data
from core.data import offer_repo_write as offer_write
from server.pg.schema import ensure_schema
from server.pg.uow import get_uow, use_security_context


def _seed_match_fixture() -> dict[str, object]:
    ensure_django()
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    phone_suffix = str(int(suffix, 16))[-6:].rjust(6, "0")

    conn = admin_conn()
    agency_id = 0
    client_id = 0
    listing_id = 0
    demande_ids: list[int] = []
    offer_ids: list[int] = []
    try:
        agency_id = create_agency(conn, f"MAP{suffix}", f"Match Artifact Agency {suffix}")
        conn.commit()

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().transaction() as session:
                client_id = client_write.upsert_client(
                    session,
                    {
                        "family_name": f"Match Artifact Client {suffix}",
                        "phone": f"0554{phone_suffix}",
                        "status": "active",
                    },
                )
                listing_id = listing_write.upsert_listing(
                    session,
                    {
                        "family_name": f"Match Artifact Listing {suffix}",
                        "phone": f"0664{phone_suffix}",
                        "status": "available",
                    },
                )
                demande_ids.append(
                    demande_write.create_demande(
                        session,
                        {
                            "client_id": client_id,
                            "type": "apartment",
                            "type_id": 1,
                            "action": "buy",
                            "action_id": 1,
                            "wilaya": "Alger",
                            "wilaya_id": 16,
                            "locations": f"Hydra {suffix}",
                            "beds_min": 2,
                            "surface_min": 60,
                            "surface_max": 120,
                            "budget_min": 100,
                            "budget_max": 300,
                            "floor_min": 0,
                            "floor_max": 8,
                            "elevator": True,
                            "accessibility_required": True,
                        },
                    )
                )
                demande_ids.append(
                    demande_write.create_demande(
                        session,
                        {
                            "client_id": client_id,
                            "type": "apartment",
                            "type_id": 1,
                            "action": "buy",
                            "action_id": 1,
                            "wilaya": "Alger",
                            "wilaya_id": 16,
                            "locations": "",
                            "beds_min": 2,
                            "surface_min": 60,
                            "surface_max": 120,
                            "budget_min": 100,
                            "budget_max": 300,
                            "floor_min": 0,
                            "floor_max": 8,
                            "elevator": True,
                            "accessibility_required": True,
                        },
                    )
                )
                offer_ids.append(
                    offer_write.create_offer(
                        session,
                        listing_id,
                        {
                            "type": "apartment",
                            "type_id": 1,
                            "action": "sell",
                            "action_id": 3,
                            "status": "available",
                            "wilaya": "Alger",
                            "wilaya_id": 16,
                            "location": f"Hydra {suffix}",
                            "beds": 3,
                            "surface": 90,
                            "budget": 200,
                            "floor": 2,
                            "elevator": True,
                            "accessibility_supported": True,
                        },
                    )
                )
                offer_ids.append(
                    offer_write.create_offer(
                        session,
                        listing_id,
                        {
                            "type": "apartment",
                            "type_id": 1,
                            "action": "sell",
                            "action_id": 3,
                            "status": "available",
                            "wilaya": "Alger",
                            "wilaya_id": 16,
                            "location": f"Hydra {suffix}",
                            "beds": 3,
                            "surface": 90,
                            "budget": 200,
                            "floor": 2,
                            "elevator": True,
                            "accessibility_supported": True,
                        },
                    )
                )
        return {
            "conn": conn,
            "agency_id": agency_id,
            "client_id": client_id,
            "listing_id": listing_id,
            "demande_ids": demande_ids,
            "offer_ids": offer_ids,
        }
    except Exception:
        conn.close()
        raise


def _cleanup_fixture(fixture: dict[str, object]) -> None:
    conn = fixture["conn"]
    agency_id = int(fixture["agency_id"])
    try:
        conn.rollback()
    finally:
        conn.close()
    if agency_id:
        cleanup_import_test_agency(agency_id=agency_id)


def _candidate_snapshot(*, agency_id: int, demande_ids: list[int]) -> list[tuple[object, ...]]:
    with use_security_context(agency_id=agency_id, is_superuser=False):
        with get_uow().session() as session:
            rows = session.execute(
                """
                SELECT
                    demande_id,
                    offer_id,
                    demande_visibility,
                    offer_visibility,
                    demande_owner_user_id,
                    offer_owner_user_id
                FROM match_candidates
                WHERE demande_id = ANY(%s)
                ORDER BY demande_id, offer_id
                """,
                (demande_ids,),
            ).fetchall()
    return [
        (
            row["demande_id"],
            row["offer_id"],
            row["demande_visibility"],
            row["offer_visibility"],
            row["demande_owner_user_id"],
            row["offer_owner_user_id"],
        )
        for row in rows
    ]


def _pair_snapshot(*, agency_id: int, demande_ids: list[int]) -> list[tuple[object, ...]]:
    with use_security_context(agency_id=agency_id, is_superuser=False):
        with get_uow().session() as session:
            rows = session.execute(
                """
                SELECT
                    demande_id,
                    offer_id,
                    score,
                    rank,
                    demande_visibility,
                    offer_visibility,
                    demande_owner_user_id,
                    offer_owner_user_id
                FROM match_pairs
                WHERE demande_id = ANY(%s)
                ORDER BY demande_id, rank, offer_id
                """,
                (demande_ids,),
            ).fetchall()
    return [
        (
            row["demande_id"],
            row["offer_id"],
            float(row["score"]),
            row["rank"],
            row["demande_visibility"],
            row["offer_visibility"],
            row["demande_owner_user_id"],
            row["offer_owner_user_id"],
        )
        for row in rows
    ]


def test_direct_pipeline_matches_legacy_rows_and_limit_ordering() -> None:
    fixture = _seed_match_fixture()
    agency_id = int(fixture["agency_id"])
    demande_ids = [int(v) for v in fixture["demande_ids"]]
    try:
        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().transaction() as session:
                candidate_counts = (
                    match_candidates_data.replace_candidates_for_demandes_from_match_query(
                        session,
                        demande_ids,
                    )
                )
                stored_total, ranked_total, _per_demande = (
                    match_pairs_data.rebuild_pairs_for_demandes_from_candidates_sql(
                        session,
                        demande_ids,
                        limit=1,
                    )
                )
        legacy_candidates = _candidate_snapshot(agency_id=agency_id, demande_ids=demande_ids)
        legacy_pairs = _pair_snapshot(agency_id=agency_id, demande_ids=demande_ids)

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().transaction() as session:
                match_candidates_data.clear_candidates(session, demande_ids=demande_ids)
                match_pairs_data.clear_pairs(session, demande_ids=demande_ids)
                direct_result = match_artifact_pipeline.rebuild_match_artifacts_for_demandes(
                    session,
                    demande_ids,
                    limit=1,
                )
        direct_candidates = _candidate_snapshot(agency_id=agency_id, demande_ids=demande_ids)
        direct_pairs = _pair_snapshot(agency_id=agency_id, demande_ids=demande_ids)

        assert sum(candidate_counts.values()) == 4
        assert stored_total == 2
        assert ranked_total == 4
        assert direct_result.candidate_total == 4
        assert direct_result.ranked_total == 4
        assert direct_result.pair_total == 2
        assert legacy_candidates == direct_candidates
        assert legacy_pairs == direct_pairs
        assert len(direct_pairs) == 2
        assert {row[1] for row in direct_pairs} == {min(int(v) for v in fixture["offer_ids"])}
    finally:
        _cleanup_fixture(fixture)


def test_direct_pipeline_can_rebuild_overlapping_existing_rows_without_pk_violation() -> None:
    fixture = _seed_match_fixture()
    agency_id = int(fixture["agency_id"])
    demande_ids = [int(v) for v in fixture["demande_ids"]]
    try:
        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().transaction() as session:
                first = match_artifact_pipeline.rebuild_match_artifacts_for_demandes(
                    session,
                    demande_ids,
                    limit=1,
                )
            with get_uow().transaction() as session:
                second = match_artifact_pipeline.rebuild_match_artifacts_for_demandes(
                    session,
                    demande_ids,
                    limit=1,
                )

        pairs = _pair_snapshot(agency_id=agency_id, demande_ids=demande_ids)
        assert first.candidate_total == second.candidate_total == 4
        assert first.pair_total == second.pair_total == 2
        assert len(pairs) == 2
    finally:
        _cleanup_fixture(fixture)


def test_direct_pipeline_limit_semantics_report_full_candidates_and_limited_pairs() -> None:
    fixture = _seed_match_fixture()
    agency_id = int(fixture["agency_id"])
    demande_ids = [int(v) for v in fixture["demande_ids"]]
    try:
        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().transaction() as session:
                limited = match_artifact_pipeline.rebuild_match_artifacts_for_demandes(
                    session,
                    demande_ids,
                    limit=1,
                )
            with get_uow().transaction() as session:
                unlimited = match_artifact_pipeline.rebuild_match_artifacts_for_demandes(
                    session,
                    demande_ids,
                    limit=None,
                )

        assert limited.candidate_total == 4
        assert limited.ranked_total == 4
        assert limited.pair_total == 2
        assert limited.per_demande[demande_ids[0]] == match_artifact_pipeline.MatchArtifactCounts(
            candidate_total=2,
            ranked_total=2,
            pair_total=1,
        )
        assert limited.per_demande[demande_ids[1]] == match_artifact_pipeline.MatchArtifactCounts(
            candidate_total=2,
            ranked_total=2,
            pair_total=1,
        )

        assert unlimited.candidate_total == 4
        assert unlimited.ranked_total == 4
        assert unlimited.pair_total == 4
        assert unlimited.per_demande[demande_ids[0]].pair_total == 2
        assert unlimited.per_demande[demande_ids[1]].pair_total == 2
    finally:
        _cleanup_fixture(fixture)


def test_direct_pipeline_clears_stale_rows_for_deleted_and_zero_match_demandes() -> None:
    fixture = _seed_match_fixture()
    conn = fixture["conn"]
    agency_id = int(fixture["agency_id"])
    demande_ids = [int(v) for v in fixture["demande_ids"]]
    try:
        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().transaction() as session:
                first = match_artifact_pipeline.rebuild_match_artifacts_for_demandes(
                    session,
                    demande_ids,
                    limit=1,
                )
        assert first.candidate_total == 4
        assert len(_candidate_snapshot(agency_id=agency_id, demande_ids=demande_ids)) == 4
        assert len(_pair_snapshot(agency_id=agency_id, demande_ids=demande_ids)) == 2

        conn.execute(
            "UPDATE demandes SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s",
            (demande_ids[0],),
        )
        conn.execute(
            """
            UPDATE demandes
            SET budget_min = %s,
                budget_max = %s,
                budget_range = numrange(%s, %s, '[]')
            WHERE id = %s
            """,
            (0, 50, 0, 50, demande_ids[1]),
        )
        conn.commit()

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().transaction() as session:
                result = match_artifact_pipeline.rebuild_match_artifacts_for_demandes(
                    session,
                    demande_ids,
                    limit=1,
                )

        assert result.candidate_total == 0
        assert result.ranked_total == 0
        assert result.pair_total == 0
        assert result.per_demande[demande_ids[0]] == match_artifact_pipeline.MatchArtifactCounts(
            candidate_total=0,
            ranked_total=0,
            pair_total=0,
        )
        assert result.per_demande[demande_ids[1]] == match_artifact_pipeline.MatchArtifactCounts(
            candidate_total=0,
            ranked_total=0,
            pair_total=0,
        )
        assert _candidate_snapshot(agency_id=agency_id, demande_ids=demande_ids) == []
        assert _pair_snapshot(agency_id=agency_id, demande_ids=demande_ids) == []
    finally:
        _cleanup_fixture(fixture)


def test_direct_pipeline_rolls_back_cleanly_on_insert_failure(monkeypatch) -> None:
    import psycopg

    fixture = _seed_match_fixture()
    agency_id = int(fixture["agency_id"])
    demande_ids = [int(v) for v in fixture["demande_ids"]]
    try:
        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().transaction() as session:
                match_artifact_pipeline.rebuild_match_artifacts_for_demandes(
                    session,
                    demande_ids,
                    limit=1,
                )
        candidates_before = _candidate_snapshot(agency_id=agency_id, demande_ids=demande_ids)
        pairs_before = _pair_snapshot(agency_id=agency_id, demande_ids=demande_ids)

        monkeypatch.setattr(
            match_artifact_pipeline,
            "_artifact_insert_query",
            lambda _demande_ids, *, limit: ("SELECT 1 / 0", []),
        )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with pytest.raises(psycopg.Error):
                with get_uow().transaction() as session:
                    match_artifact_pipeline.rebuild_match_artifacts_for_demandes(
                        session,
                        demande_ids,
                        limit=1,
                    )

        assert (
            _candidate_snapshot(agency_id=agency_id, demande_ids=demande_ids) == candidates_before
        )
        assert _pair_snapshot(agency_id=agency_id, demande_ids=demande_ids) == pairs_before
    finally:
        _cleanup_fixture(fixture)


def test_direct_pipeline_keeps_agency_isolation_when_foreign_demande_id_is_passed() -> None:
    fixture_a = _seed_match_fixture()
    fixture_b = _seed_match_fixture()
    agency_a = int(fixture_a["agency_id"])
    agency_b = int(fixture_b["agency_id"])
    demande_a = int(fixture_a["demande_ids"][0])
    demande_b = int(fixture_b["demande_ids"][0])
    try:
        with use_security_context(agency_id=agency_b, is_superuser=False):
            with get_uow().transaction() as session:
                match_artifact_pipeline.rebuild_match_artifacts_for_demandes(
                    session,
                    [demande_b],
                    limit=1,
                )
        foreign_candidates_before = _candidate_snapshot(agency_id=agency_b, demande_ids=[demande_b])
        foreign_pairs_before = _pair_snapshot(agency_id=agency_b, demande_ids=[demande_b])

        with use_security_context(agency_id=agency_a, is_superuser=False):
            with get_uow().transaction() as session:
                result = match_artifact_pipeline.rebuild_match_artifacts_for_demandes(
                    session,
                    [demande_a, demande_b],
                    limit=1,
                )

        assert result.per_demande[demande_a].candidate_total > 0
        assert result.per_demande[demande_b] == match_artifact_pipeline.MatchArtifactCounts(
            candidate_total=0,
            ranked_total=0,
            pair_total=0,
        )
        assert (
            _candidate_snapshot(agency_id=agency_b, demande_ids=[demande_b])
            == foreign_candidates_before
        )
        assert _pair_snapshot(agency_id=agency_b, demande_ids=[demande_b]) == foreign_pairs_before
    finally:
        _cleanup_fixture(fixture_a)
        _cleanup_fixture(fixture_b)


def test_direct_pipeline_inlines_visibility_and_owner_metadata_without_backfill() -> None:
    fixture = _seed_match_fixture()
    agency_id = int(fixture["agency_id"])
    demande_ids = [int(v) for v in fixture["demande_ids"]]
    try:
        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().transaction() as session:
                match_artifact_pipeline.rebuild_match_artifacts_for_demandes(
                    session,
                    demande_ids,
                    limit=1,
                )
            with get_uow().session() as session:
                candidate_rows = session.execute(
                    """
                    SELECT
                        mc.demande_visibility,
                        d.visibility AS expected_demande_visibility,
                        mc.offer_visibility,
                        o.visibility AS expected_offer_visibility,
                        mc.demande_owner_user_id,
                        d.owner_user_id AS expected_demande_owner_user_id,
                        mc.offer_owner_user_id,
                        o.owner_user_id AS expected_offer_owner_user_id
                    FROM match_candidates mc
                    JOIN demandes d ON d.id = mc.demande_id
                    JOIN offers o ON o.id = mc.offer_id
                    WHERE mc.demande_id = ANY(%s)
                    """,
                    (demande_ids,),
                ).fetchall()
                pair_rows = session.execute(
                    """
                    SELECT
                        mp.demande_visibility,
                        d.visibility AS expected_demande_visibility,
                        mp.offer_visibility,
                        o.visibility AS expected_offer_visibility,
                        mp.demande_owner_user_id,
                        d.owner_user_id AS expected_demande_owner_user_id,
                        mp.offer_owner_user_id,
                        o.owner_user_id AS expected_offer_owner_user_id
                    FROM match_pairs mp
                    JOIN demandes d ON d.id = mp.demande_id
                    JOIN offers o ON o.id = mp.offer_id
                    WHERE mp.demande_id = ANY(%s)
                    """,
                    (demande_ids,),
                ).fetchall()

        assert candidate_rows
        assert pair_rows
        for row in [*candidate_rows, *pair_rows]:
            assert row["demande_visibility"] == row["expected_demande_visibility"]
            assert row["offer_visibility"] == row["expected_offer_visibility"]
            assert row["demande_owner_user_id"] == row["expected_demande_owner_user_id"]
            assert row["offer_owner_user_id"] == row["expected_offer_owner_user_id"]
    finally:
        _cleanup_fixture(fixture)
