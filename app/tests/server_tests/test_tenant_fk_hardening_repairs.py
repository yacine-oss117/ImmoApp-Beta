from __future__ import annotations

import pytest

pytest.importorskip("psycopg", reason="tenant FK hardening repair tests require server deps")

from app.tests.server_tests._integration_auth_helpers import admin_conn, ensure_django
from server.pg import tenant_fk_hardening as hardening
from server.pg.schema import ensure_schema


@pytest.fixture()
def repair_conn():
    ensure_django()
    ensure_schema()
    conn = admin_conn()
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _patch_scope(
    monkeypatch,
    *,
    root: tuple[str, ...] = (),
    single: tuple[tuple[str, str, str, str], ...] = (),
    dual: tuple[tuple[str, str], ...] = (),
    artifacts: tuple[str, ...] = (),
    cache: str = "tfh_match_counts_cache",
) -> None:
    monkeypatch.setattr(hardening, "_ROOT_TABLES", root)
    monkeypatch.setattr(hardening, "_SINGLE_PARENT_TABLES", single)
    monkeypatch.setattr(hardening, "_DUAL_PARENT_TABLES", dual)
    monkeypatch.setattr(hardening, "_ARTIFACT_TABLES", artifacts)
    monkeypatch.setattr(hardening, "_CACHE_TABLE", cache)


def test_single_parent_child_agency_is_repaired_from_parent(monkeypatch, repair_conn) -> None:
    _patch_scope(
        monkeypatch,
        single=(("tfh_demandes", "id", "client_id", "tfh_clients"),),
    )
    repair_conn.execute("CREATE TEMP TABLE tfh_clients (id BIGINT PRIMARY KEY, agency_id BIGINT)")
    repair_conn.execute(
        "CREATE TEMP TABLE tfh_demandes (id BIGINT PRIMARY KEY, agency_id BIGINT, client_id BIGINT)"
    )
    repair_conn.execute(
        "CREATE TEMP TABLE tfh_match_counts_cache (agency_id BIGINT, client_id BIGINT)"
    )
    repair_conn.execute("INSERT INTO tfh_clients (id, agency_id) VALUES (1, 10)")
    repair_conn.execute("INSERT INTO tfh_demandes (id, agency_id, client_id) VALUES (7, 99, 1)")

    report = hardening.repair_tenant_integrity(repair_conn)
    row = repair_conn.execute("SELECT agency_id FROM tfh_demandes WHERE id = 7").fetchone()

    assert report.ok
    assert int(row["agency_id"]) == 10


def test_dual_parent_row_with_agreeing_parents_is_repaired(monkeypatch, repair_conn) -> None:
    _patch_scope(monkeypatch, dual=(("tfh_visits", "id"),))
    repair_conn.execute("CREATE TEMP TABLE clients (id BIGINT PRIMARY KEY, agency_id BIGINT)")
    repair_conn.execute("CREATE TEMP TABLE listings (id BIGINT PRIMARY KEY, agency_id BIGINT)")
    repair_conn.execute(
        "CREATE TEMP TABLE tfh_visits (id BIGINT PRIMARY KEY, agency_id BIGINT, client_id BIGINT, listing_id BIGINT)"
    )
    repair_conn.execute(
        "CREATE TEMP TABLE tfh_match_counts_cache (agency_id BIGINT, client_id BIGINT)"
    )
    repair_conn.execute("INSERT INTO clients (id, agency_id) VALUES (1, 20)")
    repair_conn.execute("INSERT INTO listings (id, agency_id) VALUES (2, 20)")
    repair_conn.execute(
        "INSERT INTO tfh_visits (id, agency_id, client_id, listing_id) VALUES (3, 0, 1, 2)"
    )

    report = hardening.repair_tenant_integrity(repair_conn)
    row = repair_conn.execute("SELECT agency_id FROM tfh_visits WHERE id = 3").fetchone()

    assert report.ok
    assert int(row["agency_id"]) == 20


def test_dual_parent_disagreement_blocks_enforcement(monkeypatch, repair_conn) -> None:
    _patch_scope(monkeypatch, dual=(("tfh_contracts", "id"),))
    repair_conn.execute("CREATE TEMP TABLE clients (id BIGINT PRIMARY KEY, agency_id BIGINT)")
    repair_conn.execute("CREATE TEMP TABLE listings (id BIGINT PRIMARY KEY, agency_id BIGINT)")
    repair_conn.execute(
        "CREATE TEMP TABLE tfh_contracts (id BIGINT PRIMARY KEY, agency_id BIGINT, client_id BIGINT, listing_id BIGINT)"
    )
    repair_conn.execute(
        "CREATE TEMP TABLE tfh_match_counts_cache (agency_id BIGINT, client_id BIGINT)"
    )
    repair_conn.execute("INSERT INTO clients (id, agency_id) VALUES (1, 30)")
    repair_conn.execute("INSERT INTO listings (id, agency_id) VALUES (2, 31)")
    repair_conn.execute(
        "INSERT INTO tfh_contracts (id, agency_id, client_id, listing_id) VALUES (4, NULL, 1, 2)"
    )

    report = hardening.repair_tenant_integrity(repair_conn)

    assert not report.ok
    assert any(
        finding.table_name == "tfh_contracts" and finding.issue_code == "DUAL_PARENT_DISAGREE"
        for finding in report.findings
    )
    with pytest.raises(RuntimeError):
        hardening.assert_report_ok(report)


def test_invalid_artifact_rows_are_purged_when_parent_agencies_disagree(
    monkeypatch, repair_conn
) -> None:
    _patch_scope(monkeypatch, artifacts=("tfh_match_pairs",))
    repair_conn.execute("CREATE TEMP TABLE demandes (id BIGINT PRIMARY KEY, agency_id BIGINT)")
    repair_conn.execute("CREATE TEMP TABLE offers (id BIGINT PRIMARY KEY, agency_id BIGINT)")
    repair_conn.execute(
        "CREATE TEMP TABLE tfh_match_pairs (demande_id BIGINT, offer_id BIGINT, agency_id BIGINT)"
    )
    repair_conn.execute(
        "CREATE TEMP TABLE tfh_match_counts_cache (agency_id BIGINT, client_id BIGINT)"
    )
    repair_conn.execute("INSERT INTO demandes (id, agency_id) VALUES (1, 40)")
    repair_conn.execute("INSERT INTO offers (id, agency_id) VALUES (2, 41)")
    repair_conn.execute(
        "INSERT INTO tfh_match_pairs (demande_id, offer_id, agency_id) VALUES (1, 2, 40)"
    )

    report = hardening.repair_tenant_integrity(repair_conn)
    row = repair_conn.execute("SELECT COUNT(*) AS total FROM tfh_match_pairs").fetchone()

    assert report.ok
    assert int(row["total"]) == 0


def test_match_counts_cache_rows_are_repaired_or_deleted(monkeypatch, repair_conn) -> None:
    _patch_scope(monkeypatch)
    repair_conn.execute("CREATE TEMP TABLE clients (id BIGINT PRIMARY KEY, agency_id BIGINT)")
    repair_conn.execute(
        "CREATE TEMP TABLE tfh_match_counts_cache (agency_id BIGINT, client_id BIGINT)"
    )
    repair_conn.execute("INSERT INTO clients (id, agency_id) VALUES (1, 50)")
    repair_conn.execute(
        "INSERT INTO tfh_match_counts_cache (agency_id, client_id) VALUES (99, 1), (88, 999)"
    )

    report = hardening.repair_tenant_integrity(repair_conn)
    rows = repair_conn.execute(
        "SELECT agency_id, client_id FROM tfh_match_counts_cache ORDER BY client_id"
    ).fetchall()

    assert report.ok
    assert rows == [{"agency_id": 50, "client_id": 1}]


def test_root_null_agency_is_backfilled_in_single_agency_mode(monkeypatch, repair_conn) -> None:
    _patch_scope(monkeypatch, root=("clients",))
    repair_conn.execute("CREATE TEMP TABLE accounts_agency (id BIGINT PRIMARY KEY)")
    repair_conn.execute("CREATE TEMP TABLE clients (id BIGINT PRIMARY KEY, agency_id BIGINT)")
    repair_conn.execute(
        "CREATE TEMP TABLE tfh_match_counts_cache (agency_id BIGINT, client_id BIGINT)"
    )
    repair_conn.execute("INSERT INTO accounts_agency (id) VALUES (60)")
    repair_conn.execute("INSERT INTO clients (id, agency_id) VALUES (1, NULL)")

    report = hardening.repair_tenant_integrity(repair_conn)
    row = repair_conn.execute("SELECT agency_id FROM clients WHERE id = 1").fetchone()

    assert report.ok
    assert int(row["agency_id"]) == 60


def test_root_null_agency_in_multi_agency_mode_blocks_enforcement(monkeypatch, repair_conn) -> None:
    _patch_scope(monkeypatch, root=("clients",))
    repair_conn.execute("CREATE TEMP TABLE accounts_agency (id BIGINT PRIMARY KEY)")
    repair_conn.execute("CREATE TEMP TABLE clients (id BIGINT PRIMARY KEY, agency_id BIGINT)")
    repair_conn.execute(
        "CREATE TEMP TABLE tfh_match_counts_cache (agency_id BIGINT, client_id BIGINT)"
    )
    repair_conn.execute("INSERT INTO accounts_agency (id) VALUES (70), (71)")
    repair_conn.execute("INSERT INTO clients (id, agency_id) VALUES (1, NULL)")

    report = hardening.repair_tenant_integrity(repair_conn)

    assert not report.ok
    assert any(
        finding.table_name == "clients" and finding.issue_code == "ROOT_NULL_AGENCY"
        for finding in report.findings
    )
    with pytest.raises(RuntimeError):
        hardening.assert_report_ok(report)
