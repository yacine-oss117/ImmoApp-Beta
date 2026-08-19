import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "server"))
django.setup()

from core.matcher import match_queries
from server.pg.uow import admin_transaction, get_uow, use_security_context


def _write_explain_output(*, lines: list[str], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _explain_analyze_buffers(session, *, sql: str, params, run_analyze: bool = False) -> list[str]:
    # NOTE:
    # - EXPLAIN (ANALYZE, BUFFERS) actually EXECUTES the query.
    # - Use FORMAT TEXT so it is readable and easy to grep for Seq Scan / Index Scan.
    if run_analyze:
        explain_sql = "EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS, FORMAT TEXT) " + sql
    else:
        explain_sql = "EXPLAIN (VERBOSE, SETTINGS, FORMAT TEXT) " + sql
    plan_rows = session.execute(explain_sql, params).fetchall()
    return [row["QUERY PLAN"] for row in plan_rows]


def _build_single_query_counts_sql() -> str:
    return """
        SELECT d.client_id, COUNT(DISTINCT o.id) AS match_count
        FROM demandes d
        JOIN demande_locations dl ON d.id = dl.demande_id
        JOIN offer_locations ol ON dl.location_id = ol.location_id
        JOIN offers o ON ol.offer_id = o.id AND o.status = 'available' AND o.deleted_at IS NULL
        JOIN listings l ON l.id = o.listing_id AND l.status = 'available' AND l.deleted_at IS NULL
        WHERE d.deleted_at IS NULL
          AND (d.elevator IS NULL OR o.elevator = 1)
          AND (d.accessibility_required IS NULL OR o.accessibility_supported = 1)
          AND o.type_id = d.type_id
          AND o.action_id = CASE WHEN (d.action_id = 1) THEN 3 WHEN (d.action_id = 2) THEN 2 ELSE NULL::integer END
          AND o.price_range && d.budget_range
          AND o.surface <@ d.surface_range
          AND o.beds <@ d.beds_range
          AND (
              (d.floor_min IS NULL AND d.floor_max IS NULL)
              OR (COALESCE(o.floor, 0) >= COALESCE(d.floor_min, 0)
                  AND COALESCE(o.floor, 0) <= COALESCE(d.floor_max, 100))
          )
        GROUP BY d.client_id
        """


def _build_single_query_fallback_sql() -> str:
    return """
        WITH demande_scope AS (
            SELECT
                d.*,
                CASE
                    WHEN EXISTS (
                        SELECT 1 FROM demande_locations dl WHERE dl.demande_id = d.id
                    ) THEN 'loc'
                    WHEN d.wilaya_id IS NOT NULL AND d.wilaya_id <> 0 THEN 'wilaya'
                    ELSE 'nationwide'
                END AS scope
            FROM demandes d
        )
        SELECT ds.client_id, COUNT(DISTINCT o.id) AS match_count
        FROM demande_scope ds
        LEFT JOIN demande_locations dl
          ON ds.scope = 'loc' AND dl.demande_id = ds.id
        LEFT JOIN offer_locations ol
          ON ds.scope = 'loc' AND dl.location_id = ol.location_id
        JOIN offers o
          ON (
              (ds.scope = 'loc' AND ol.offer_id = o.id)
              OR (ds.scope = 'wilaya' AND o.wilaya_id = ds.wilaya_id)
              OR (ds.scope = 'nationwide')
          )
         AND o.status = 'available'
         AND o.deleted_at IS NULL
        JOIN listings l ON l.id = o.listing_id AND l.status = 'available' AND l.deleted_at IS NULL
        WHERE ds.deleted_at IS NULL
          AND (ds.elevator IS NULL OR o.elevator = 1)
          AND (ds.accessibility_required IS NULL OR o.accessibility_supported = 1)
          AND (ds.type_id IS NULL OR o.type_id = ds.type_id)
          AND o.action_id = CASE WHEN (ds.action_id = 1) THEN 3 WHEN (ds.action_id = 2) THEN 2 ELSE NULL::integer END
          AND o.price_range && ds.budget_range
          AND o.surface <@ ds.surface_range
          AND o.beds <@ ds.beds_range
          AND (
              (ds.floor_min IS NULL AND ds.floor_max IS NULL)
              OR (COALESCE(o.floor, 0) >= COALESCE(ds.floor_min, 0)
                  AND COALESCE(o.floor, 0) <= COALESCE(ds.floor_max, 100))
          )
        GROUP BY ds.client_id
        """


def run_benchmark():
    print("# Matcher Benchmark (Raw Engine)\n")

    TEST_AGENCY_ID = 55555

    # ---- Admin setup (non-tenant table) -----------------------------------
    # accounts_agency is NOT tenant-scoped by RLS. Create it using admin creds.
    with admin_transaction() as admin:
        admin.execute(f"""
            INSERT INTO accounts_agency (
                id, legal_name, display_name, agency_code, kbis_number,
                phone_number, email, address_line1, address_line2, city,
                postal_code, country, is_active, max_users, max_managers,
                max_agents_per_manager, created_at, updated_at
            )
            VALUES (
                {TEST_AGENCY_ID}, 'Benchmark Agency', 'Benchmark', 'BENCH01', '123456789',
                '555-555', 'test@example.com', 'Street 1', 'Street 2', 'City',
                '16000', 'Algeria', true, 10, 5, 20, NOW(), NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                legal_name = EXCLUDED.legal_name,
                display_name = EXCLUDED.display_name,
                agency_code = EXCLUDED.agency_code,
                kbis_number = EXCLUDED.kbis_number,
                phone_number = EXCLUDED.phone_number,
                email = EXCLUDED.email,
                address_line1 = EXCLUDED.address_line1,
                address_line2 = EXCLUDED.address_line2,
                city = EXCLUDED.city,
                postal_code = EXCLUDED.postal_code,
                country = EXCLUDED.country,
                is_active = EXCLUDED.is_active,
                max_users = EXCLUDED.max_users,
                max_managers = EXCLUDED.max_managers,
                max_agents_per_manager = EXCLUDED.max_agents_per_manager,
                updated_at = NOW()
            """)
        # Hard cleanup for benchmark agency (bypass RLS to avoid visibility edge cases)
        admin.execute(f"DELETE FROM offer_locations WHERE agency_id = {TEST_AGENCY_ID}")
        admin.execute(f"DELETE FROM demande_locations WHERE agency_id = {TEST_AGENCY_ID}")
        admin.execute(f"DELETE FROM offers WHERE agency_id = {TEST_AGENCY_ID}")
        admin.execute(f"DELETE FROM demandes WHERE agency_id = {TEST_AGENCY_ID}")
        admin.execute(f"DELETE FROM listings WHERE agency_id = {TEST_AGENCY_ID}")
        admin.execute(f"DELETE FROM clients WHERE agency_id = {TEST_AGENCY_ID}")

    # ---- Tenant-scoped benchmark (THIS is what we want to prove) ----------
    # IMPORTANT:
    # - Run as non-superuser (is_superuser=False)
    # - Rely on agency_id DEFAULT (do NOT insert agency_id explicitly)
    persist = bool(int(os.environ.get("BENCH_PERSIST", "0")))
    with use_security_context(agency_id=TEST_AGENCY_ID, is_superuser=False):
        # Use session() (rollback) by default. If BENCH_PERSIST=1, commit data for diagnostics.
        ctx = get_uow().transaction() if persist else get_uow().session()
        with ctx as session:
            # Explicit transaction block so SET LOCAL works
            session.execute("BEGIN")
            # Benchmark-friendly settings (avoid misleading disk spills)
            session.execute("SET LOCAL statement_timeout TO 600000")
            session.execute("SET LOCAL work_mem = '256MB'")
            session.execute("SET LOCAL jit = off")

            # 1) Cleanup tenant tables (best-effort, admin already wiped)
            session.execute("DELETE FROM offers")
            session.execute("DELETE FROM demandes")
            session.execute("DELETE FROM listings")
            session.execute("DELETE FROM clients")
            session.execute("DELETE FROM demande_locations")
            session.execute("DELETE FROM offer_locations")

            # NOTE: locations is a GLOBAL lookup table (no agency_id). For benchmark safety:
            # - Insert benchmark-only rows with a prefix and reuse them (ON CONFLICT DO NOTHING).
            # - Do NOT delete all locations; just rely on the prefix.

            needed = int(os.environ.get("BENCH_NUM_ROWS", "1000"))
            num_locations = int(os.environ.get("BENCH_NUM_LOCATIONS", str(needed)))
            print(
                f"Injecting {needed} offers + {needed} demandes (DEFAULT agency_id) with {num_locations} locations "
                f"for Agency {TEST_AGENCY_ID} as NON-SUPERUSER..."
            )

            # 2) Create 5,000 active clients + 5,000 active listings (avoid seq-scan-per-loop artifacts)
            session.execute(f"""
                INSERT INTO clients (family_name, phone, status, created_at, updated_at)
                SELECT
                    'Benchmark_' || gs::text,
                    lpad(gs::text, 10, '0'),
                    'active',
                    NOW(), NOW()
                FROM generate_series(1, {needed}) AS gs
                """)
            session.execute(f"""
                INSERT INTO listings (family_name, phone, status, created_at, updated_at)
                SELECT
                    'Benchmark_' || gs::text,
                    'L' || lpad(gs::text, 10, '0'),
                    'available',
                    NOW(), NOW()
                FROM generate_series(1, {needed}) AS gs
                """)

            # 3) Ensure benchmark locations exist (global lookup table)
            session.execute(f"""
                INSERT INTO locations (location_norm)
                SELECT 'bench_loc_' || gs::text
                FROM generate_series(1, {num_locations}) AS gs
                ON CONFLICT (location_norm) DO NOTHING
                """)

            action_id = int(os.environ.get("BENCH_ACTION_ID", "1"))
            type_id = int(os.environ.get("BENCH_TYPE_ID", "1"))
            offer_action_id = os.environ.get("BENCH_OFFER_ACTION_ID")
            if offer_action_id is None:
                if action_id == 1:
                    offer_action_id = "3"
                elif action_id == 2:
                    offer_action_id = "2"
                else:
                    offer_action_id = str(action_id)
            offer_action_id = int(offer_action_id)

            # 4) Create demandes: 1 per client (no agency_id provided -> DEFAULT from GUC)
            #    Use ranges that can match, but let LOCATION distribution make it selective.
            session.execute(f"""
                INSERT INTO demandes (
                    client_id, type_id, action_id, wilaya_id,
                    budget_min, budget_max, surface_min, surface_max, beds_min,
                    floor_min, floor_max,
                    budget_range, surface_range, beds_range,
                    created_at, updated_at
                )
                SELECT
                    c.id,
                    {type_id},
                    {action_id},
                    1,
                    100,
                    200,
                    50,
                    100,
                    2,
                    0,
                    100,
                    numrange(100, 200, '[]'),
                    numrange(50, 100, '[]'),
                    int4range(2, 4, '[]'),
                    NOW(), NOW()
                FROM clients c
                WHERE c.deleted_at IS NULL
                ORDER BY c.id
                LIMIT {needed}
                """)

            wildcard_pct = int(os.environ.get("BENCH_WILDCARD_PCT", "10"))
            wilaya_pct = int(os.environ.get("BENCH_WILAYA_PCT", "10"))
            nationwide_pct = int(os.environ.get("BENCH_NATIONWIDE_PCT", "10"))
            if wildcard_pct + wilaya_pct + nationwide_pct > 100:
                raise ValueError("Wildcard/wilaya/nationwide percentages must sum to <= 100")
            wildcard_count = needed * wildcard_pct // 100
            wilaya_count = needed * wilaya_pct // 100
            nationwide_count = needed * nationwide_pct // 100

            # 5) Create offers: 1 per listing (no agency_id provided -> DEFAULT from GUC)
            session.execute(f"""
                INSERT INTO offers (
                    listing_id, type_id, action_id, status,
                    wilaya_id, location,
                    price_range, beds, surface, budget,
                    floor, elevator, accessibility_supported,
                    created_at, updated_at
                )
                SELECT
                    l.id,
                    {type_id},
                    {offer_action_id},
                    'available',
                    1,
                    'bench_loc_' || ((l.id - 1) %% {num_locations}) + 1,
                    numrange(100, 200, '[]'),
                    3,
                    75.0,
                    150,
                    0,
                    1,
                    1,
                    NOW(), NOW()
                FROM listings l
                WHERE l.deleted_at IS NULL
                ORDER BY l.id
                LIMIT {needed}
                """)

            # 6) Attach exactly 1 location per demande and 1 location per offer.
            #    Uniform distribution over num_locations makes expected matches ~ N^2/num_locations
            #    (e.g., 25M/200 ≈ 125k) so indexes can actually matter.
            session.execute(f"""
                WITH locs AS (
                    SELECT location_id,
                           row_number() OVER (ORDER BY location_id) AS rn
                    FROM locations
                    WHERE location_norm LIKE 'bench_loc_%%'
                    ORDER BY location_id
                    LIMIT {num_locations}
                ),
                d AS (
                    SELECT id AS demande_id,
                           row_number() OVER (ORDER BY id) AS rn
                    FROM demandes
                    ORDER BY id
                    LIMIT {needed}
                )
                INSERT INTO demande_locations (demande_id, location_id)
                SELECT d.demande_id, locs.location_id
                FROM d
                JOIN locs
                  ON locs.rn = ((d.rn - 1) %% {num_locations}) + 1
                """)

            if wildcard_count:
                session.execute(f"""
                    WITH pick AS (
                        SELECT id FROM demandes ORDER BY id LIMIT {wildcard_count}
                    )
                    UPDATE demandes
                    SET type_id = NULL
                    WHERE id IN (SELECT id FROM pick)
                    """)

            if wilaya_count:
                session.execute(f"""
                    WITH pick AS (
                        SELECT id FROM demandes ORDER BY id OFFSET {wildcard_count} LIMIT {wilaya_count}
                    )
                    DELETE FROM demande_locations
                    WHERE demande_id IN (SELECT id FROM pick)
                    """)

            if nationwide_count:
                offset = wildcard_count + wilaya_count
                session.execute(f"""
                    WITH pick AS (
                        SELECT id FROM demandes ORDER BY id OFFSET {offset} LIMIT {nationwide_count}
                    )
                    DELETE FROM demande_locations
                    WHERE demande_id IN (SELECT id FROM pick)
                    """)
                session.execute(f"""
                    WITH pick AS (
                        SELECT id FROM demandes ORDER BY id OFFSET {offset} LIMIT {nationwide_count}
                    )
                    UPDATE demandes
                    SET wilaya_id = NULL
                    WHERE id IN (SELECT id FROM pick)
                    """)
            session.execute(f"""
                WITH locs AS (
                    SELECT location_id,
                           row_number() OVER (ORDER BY location_id) AS rn
                    FROM locations
                    WHERE location_norm LIKE 'bench_loc_%%'
                    ORDER BY location_id
                    LIMIT {num_locations}
                ),
                o AS (
                    SELECT id AS offer_id,
                           row_number() OVER (ORDER BY id) AS rn
                    FROM offers
                    ORDER BY id
                    LIMIT {needed}
                )
                INSERT INTO offer_locations (offer_id, location_id)
                SELECT o.offer_id, locs.location_id
                FROM o
                JOIN locs
                  ON locs.rn = ((o.rn - 1) %% {num_locations}) + 1
                """)

            session.execute("ANALYZE offers")
            session.execute("ANALYZE demandes")
            session.execute("ANALYZE offer_locations")
            session.execute("ANALYZE demande_locations")

            # 3) Compare CTE vs single-query with EXPLAIN ANALYZE
            run_analyze = True  # Force ANALYZE for timing on strict queries
            mode = "EXPLAIN (ANALYZE, BUFFERS)" if run_analyze else "EXPLAIN (plan only)"
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

            if int(os.environ.get("BENCH_RUN_CTE", "1")):
                print(f"\nRunning {mode} for CTE-based benchmark query...")
                cte_query = match_queries.build_client_counts_query(agency_id=None)
                cte_plan_lines = _explain_analyze_buffers(
                    session, sql=cte_query.sql, params=cte_query.params, run_analyze=run_analyze
                )
                cte_out = Path("scripts/benchmark_outputs") / (
                    f"client_counts_explain_cte_{TEST_AGENCY_ID}_{stamp}.txt"
                )
                _write_explain_output(lines=cte_plan_lines, out_path=cte_out)
                print(f"Saved CTE plan output to: {cte_out}")

                print("\n--- CTE Plan snippet (first 40 lines) ---")
                for line in cte_plan_lines[:40]:
                    print(line)

            print(f"\nRunning {mode} for single-query benchmark (strict)...")
            single_sql = _build_single_query_counts_sql()
            single_plan_lines = _explain_analyze_buffers(
                session, sql=single_sql, params=[], run_analyze=run_analyze
            )
            single_out = Path("scripts/benchmark_outputs") / (
                f"client_counts_explain_single_{TEST_AGENCY_ID}_{stamp}.txt"
            )
            _write_explain_output(lines=single_plan_lines, out_path=single_out)
            print(f"Saved single-query plan output to: {single_out}")

            print("\n--- Single-query Plan snippet (first 40 lines) ---")
            for line in single_plan_lines[:40]:
                print(line)

            fallback_analyze = bool(int(os.environ.get("BENCH_FALLBACK_ANALYZE", "0")))
            fallback_mode = (
                "EXPLAIN (ANALYZE, BUFFERS)" if fallback_analyze else "EXPLAIN (plan only)"
            )
            print(f"\nRunning {fallback_mode} for single-query benchmark (fallback + wildcard)...")
            fallback_sql = _build_single_query_fallback_sql()
            fallback_plan_lines = _explain_analyze_buffers(
                session, sql=fallback_sql, params=[], run_analyze=fallback_analyze
            )
            fallback_out = Path("scripts/benchmark_outputs") / (
                f"client_counts_explain_fallback_{TEST_AGENCY_ID}_{stamp}.txt"
            )
            _write_explain_output(lines=fallback_plan_lines, out_path=fallback_out)
            print(f"Saved fallback plan output to: {fallback_out}")

            print("\n--- Fallback Plan snippet (first 40 lines) ---")
            for line in fallback_plan_lines[:40]:
                print(line)


if __name__ == "__main__":
    try:
        run_benchmark()
    except Exception as e:
        print(f"Benchmark failed: {e}")
        import traceback

        traceback.print_exc()
