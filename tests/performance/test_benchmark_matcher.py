from __future__ import annotations

import os
import sys
import time

import pytest

pytestmark = pytest.mark.perf


def _run_perf_enabled() -> bool:
    raw = os.environ.get("IMMOAPP_RUN_PERF_TESTS", "")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _bootstrap_django() -> None:
    # Keep bootstrap local so normal test collection does not require OpenBao/DB.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    repo_root = os.getcwd()
    if repo_root not in sys.path:
        sys.path.append(repo_root)
    server_path = os.path.join(repo_root, "server")
    if server_path not in sys.path:
        sys.path.append(server_path)
    import django

    django.setup()


def run_benchmark() -> None:
    if not _run_perf_enabled():
        pytest.skip("Perf benchmark disabled. Set IMMOAPP_RUN_PERF_TESTS=1 to enable.")

    _bootstrap_django()
    from core.matcher.match_queries import (
        build_client_counts_query,
        build_demande_match_count_query,
    )
    from core.utils.row_casts import row_int
    from server.pg.simulation_seed import SIM_SCHEMA, seed_fake_data
    from server.pg.uow import get_uow, use_schema, use_security_context

    seed_count = int(os.environ.get("IMMOAPP_BENCH_SEED_COUNT", "1000"))
    if seed_count < 100:
        seed_count = 100

    print("=" * 60)
    print(f"MATCHING ENGINE BENCHMARK ({seed_count} Demandes x {seed_count} Offers)")
    print("=" * 60)

    print(f"\n[1/3] Seeding {seed_count} Clients (Demandes) and {seed_count} Listings (Offers)...")
    start_seed = time.monotonic()

    uow = get_uow()
    with uow.session() as session:
        agency_row = session.execute(
            "SELECT id FROM accounts_agency ORDER BY id LIMIT 1"
        ).fetchone()
        agency_id = row_int(agency_row, "id") if agency_row else 1

    with use_security_context(is_superuser=True, agency_id=agency_id):
        counts = seed_fake_data(
            client_count=seed_count,
            listing_count=seed_count,
            demandes_per_client=1,
            offers_per_listing=1,
        )

    seed_time = time.monotonic() - start_seed
    print(f"      -> Done in {seed_time:.2f}s")
    print(f"      -> Generated: {counts}")

    print("\n[2/3] Benchmarking GLOBAL Matching (All Clients)...")
    with use_schema(SIM_SCHEMA), use_security_context(is_superuser=True, agency_id=agency_id):
        with uow.session() as session:
            session.execute("SELECT 1")

        start_match = time.monotonic()
        with uow.session() as session:
            query = build_client_counts_query()
            print("      -> Executing match-count query...")
            rows = session.execute(query.sql, query.params).fetchall()
            match_count = len(rows)
            total_matches = sum(row_int(row, "match_count") for row in rows)
        match_time = time.monotonic() - start_match

        print(f"      -> Time: {match_time:.4f}s")
        print(f"      -> Clients with matches: {match_count}")
        print(f"      -> Total match pairs found: {total_matches}")
        if match_count > 0:
            print(f"      -> Avg matches per client: {total_matches / seed_count:.2f}")

    print("\n[3/3] Benchmarking SINGLE Demande (Hot Path)...")
    with use_schema(SIM_SCHEMA), use_security_context(is_superuser=True, agency_id=agency_id):
        with uow.session() as session:
            row = session.execute("SELECT id FROM demandes ORDER BY id LIMIT 1").fetchone()
            demande_id = row_int(row, "id") if row else 0
            assert demande_id > 0, "Benchmark seed did not create any demande rows"

            iterations = 100
            start_single = time.monotonic()
            for _ in range(iterations):
                query = build_demande_match_count_query(demande_id)
                session.execute(query.sql, query.params)
            duration = time.monotonic() - start_single
            avg_ms = (duration / iterations) * 1000.0

            print(f"      -> Avg time per lookup: {avg_ms:.3f}ms (over {iterations} runs)")
            assert avg_ms < 200.0, f"Per-demande count lookup too slow: {avg_ms:.3f}ms"


def test_benchmark_performance() -> None:
    run_benchmark()
