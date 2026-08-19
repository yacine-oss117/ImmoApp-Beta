from __future__ import annotations

import pytest

pytest.importorskip(
    "psycopg",
    reason="match artifact pipeline tenant integrity tests require server dependencies",
)
pytest.importorskip(
    "cryptography",
    reason="match artifact pipeline tenant integrity tests require full server dependencies",
)

from app.tests.server_tests.test_match_artifact_pipeline_integration import (
    _cleanup_fixture,
    _seed_match_fixture,
)
from core.data import match_artifact_pipeline
from server.pg.uow import get_uow, use_security_context


def test_direct_pipeline_persists_explicit_agency_id_on_artifacts() -> None:
    fixture = _seed_match_fixture()
    agency_id = int(fixture["agency_id"])
    demande_ids = [int(value) for value in fixture["demande_ids"]]
    try:
        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().transaction() as session:
                match_artifact_pipeline.rebuild_match_artifacts_for_demandes(
                    session,
                    demande_ids,
                    limit=50,
                )

            with get_uow().session() as session:
                candidates = session.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM match_candidates
                    WHERE demande_id = ANY(%s)
                      AND agency_id = %s
                    """,
                    (demande_ids, agency_id),
                ).fetchone()
                pairs = session.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM match_pairs
                    WHERE demande_id = ANY(%s)
                      AND agency_id = %s
                    """,
                    (demande_ids, agency_id),
                ).fetchone()
                bad_candidates = session.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM match_candidates
                    WHERE demande_id = ANY(%s)
                      AND agency_id IS DISTINCT FROM %s
                    """,
                    (demande_ids, agency_id),
                ).fetchone()
                bad_pairs = session.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM match_pairs
                    WHERE demande_id = ANY(%s)
                      AND agency_id IS DISTINCT FROM %s
                    """,
                    (demande_ids, agency_id),
                ).fetchone()

        assert int(candidates["total"]) > 0
        assert int(pairs["total"]) > 0
        assert int(bad_candidates["total"]) == 0
        assert int(bad_pairs["total"]) == 0
    finally:
        _cleanup_fixture(fixture)
