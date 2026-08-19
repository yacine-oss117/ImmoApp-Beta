from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")

from core.matcher.match_query_counts import build_client_counts_query  # noqa: E402
from server.pg.uow import admin_transaction, get_uow, use_security_context  # noqa: E402

_SEQ_SCAN_NODE_TYPES = {"Seq Scan", "Parallel Seq Scan"}
_HOT_RELATIONS = {"clients", "match_counts_cache", "demandes", "offers"}


def _budget(name: str, default_ms: int) -> float:
    raw = os.environ.get(name, str(default_ms)).strip()
    try:
        return float(raw)
    except ValueError as exc:
        raise SystemExit(f"Invalid {name}: {raw!r}") from exc


def _extract_plan_metrics(plan_json: list[dict[str, Any]]) -> dict[str, Any]:
    if not plan_json or not isinstance(plan_json[0], dict):
        raise SystemExit("verify_query_budgets: invalid EXPLAIN JSON payload")
    root = plan_json[0]
    plan = root.get("Plan", {})
    seq_scans: list[dict[str, str]] = []
    for node in _walk_plan_nodes(plan):
        node_type = str(node.get("Node Type", ""))
        if node_type not in _SEQ_SCAN_NODE_TYPES:
            continue
        relation_name = str(node.get("Relation Name", ""))
        if relation_name:
            seq_scans.append({"node_type": node_type, "relation": relation_name})

    shared_total = _sum_plan_counter(plan, "Shared Hit Blocks") + _sum_plan_counter(
        plan, "Shared Read Blocks"
    )
    temp_total = _sum_plan_counter(plan, "Temp Read Blocks") + _sum_plan_counter(
        plan, "Temp Written Blocks"
    )

    return {
        "execution_ms": float(root.get("Execution Time", 0.0)),
        "planning_ms": float(root.get("Planning Time", 0.0)),
        "node_type": plan.get("Node Type", ""),
        "seq_scans": seq_scans,
        "shared_blocks_total": int(shared_total),
        "temp_blocks_total": int(temp_total),
    }


def _walk_plan_nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = [node]
    for child in node.get("Plans", []) or []:
        if isinstance(child, dict):
            nodes.extend(_walk_plan_nodes(child))
    return nodes


def _sum_plan_counter(node: dict[str, Any], key: str) -> int:
    total = 0
    for entry in _walk_plan_nodes(node):
        value = entry.get(key, 0)
        if isinstance(value, (int, float)):
            total += int(value)
    return total


def _assert_no_hot_seq_scan(name: str, metrics: dict[str, Any]) -> None:
    seq_scans = metrics.get("seq_scans", [])
    if not isinstance(seq_scans, list):
        return
    hot_scans = [
        scan
        for scan in seq_scans
        if isinstance(scan, dict) and str(scan.get("relation", "")) in _HOT_RELATIONS
    ]
    if hot_scans:
        details = ", ".join(
            f"{scan.get('relation')} ({scan.get('node_type')})" for scan in hot_scans
        )
        raise SystemExit(
            f"verify_query_budgets: {name} used forbidden sequential scans on hot tables: {details}"
        )


def _assert_buffer_budget(name: str, metrics: dict[str, Any], max_shared_blocks: int) -> None:
    shared_blocks_total = int(metrics.get("shared_blocks_total", 0))
    if shared_blocks_total > max_shared_blocks:
        raise SystemExit(
            "verify_query_budgets: "
            f"{name} exceeded shared buffer budget ({shared_blocks_total} > {max_shared_blocks})"
        )


def _seed_dataset(agency_id: int, rows: int) -> None:
    with admin_transaction() as session:
        session.execute(
            """
            INSERT INTO accounts_agency (
                id,
                legal_name, display_name, agency_code,
                kbis_number, phone_number, email,
                address_line1, address_line2, city, postal_code, country,
                is_active, max_users, max_managers, max_agents_per_manager,
                created_at, updated_at
            )
            VALUES (
                %s,
                %s, %s, %s,
                '', '', '',
                '', '', '', '', '',
                true, 50, 10, 20,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT (id) DO UPDATE
            SET updated_at = EXCLUDED.updated_at
            """,
            (
                agency_id,
                f"QB Agency {agency_id}",
                f"QB Agency {agency_id}",
                f"QB{agency_id}",
            ),
        )
        session.execute("DELETE FROM match_counts_cache WHERE agency_id = %s", (agency_id,))
        session.execute("DELETE FROM demandes WHERE agency_id = %s", (agency_id,))
        session.execute("DELETE FROM offers WHERE agency_id = %s", (agency_id,))
        session.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
        session.execute("DELETE FROM listings WHERE agency_id = %s", (agency_id,))
        session.execute("DELETE FROM demande_locations WHERE agency_id = %s", (agency_id,))
        session.execute("DELETE FROM offer_locations WHERE agency_id = %s", (agency_id,))

        session.execute(
            """
            INSERT INTO locations (location_norm)
            SELECT 'qb_loc_' || i::text
            FROM generate_series(1, %s) AS i
            ON CONFLICT (location_norm) DO NOTHING
            """,
            (rows,),
        )
        session.execute(
            """
            INSERT INTO clients (family_name, phone, agency_id, status, created_at, updated_at)
            SELECT
                'QB Client ' || i::text,
                'QB' || lpad(i::text, 10, '0'),
                %s,
                'active',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM generate_series(1, %s) AS i
            """,
            (agency_id, rows),
        )
        session.execute(
            """
            INSERT INTO listings (family_name, phone, agency_id, status, created_at, updated_at)
            SELECT
                'QB Listing ' || i::text,
                'QL' || lpad(i::text, 10, '0'),
                %s,
                'available',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM generate_series(1, %s) AS i
            """,
            (agency_id, rows),
        )
        session.execute(
            """
            INSERT INTO demandes (
                client_id, type_id, action_id, wilaya_id,
                beds_min, surface_min, surface_max, budget_min, budget_max,
                floor_min, floor_max, elevator, accessibility_required,
                budget_range, surface_range, beds_range,
                agency_id, created_at, updated_at
            )
            SELECT
                c.id, 1, 1, 1,
                2, 50, 120, 100, 300,
                0, 10, NULL, NULL,
                numrange(100, 300, '[]'),
                numrange(50, 120, '[]'),
                int4range(2, 4, '[]'),
                %s,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM clients c
            WHERE c.agency_id = %s
            """,
            (agency_id, agency_id),
        )
        session.execute(
            """
            INSERT INTO offers (
                listing_id, type_id, action_id, wilaya_id, location,
                beds, surface, budget, floor, elevator, accessibility_supported,
                price_range,
                agency_id, status, created_at, updated_at
            )
            SELECT
                l.id, 1, 3, 1, 'qb_loc_' || row_number() OVER (ORDER BY l.id)::text,
                3, 75, 180, 1, 1, 1,
                numrange(150, 210, '[]'),
                %s, 'available', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM listings l
            WHERE l.agency_id = %s
            """,
            (agency_id, agency_id),
        )
        session.execute(
            """
            WITH d AS (
                SELECT id, row_number() OVER (ORDER BY id) AS rn
                FROM demandes
                WHERE agency_id = %s
            ),
            o AS (
                SELECT id, row_number() OVER (ORDER BY id) AS rn
                FROM offers
                WHERE agency_id = %s
            ),
            locs AS (
                SELECT location_id, row_number() OVER (ORDER BY location_id) AS rn
                FROM locations
                WHERE location_norm LIKE 'qb_loc_%%'
                ORDER BY location_id
                LIMIT %s
            )
            INSERT INTO demande_locations (demande_id, location_id, agency_id)
            SELECT d.id, locs.location_id, %s
            FROM d
            JOIN locs ON locs.rn = d.rn
            """,
            (agency_id, agency_id, rows, agency_id),
        )
        session.execute(
            """
            WITH o AS (
                SELECT id, row_number() OVER (ORDER BY id) AS rn
                FROM offers
                WHERE agency_id = %s
            ),
            locs AS (
                SELECT location_id, row_number() OVER (ORDER BY location_id) AS rn
                FROM locations
                WHERE location_norm LIKE 'qb_loc_%%'
                ORDER BY location_id
                LIMIT %s
            )
            INSERT INTO offer_locations (offer_id, location_id, agency_id)
            SELECT o.id, locs.location_id, %s
            FROM o
            JOIN locs ON locs.rn = o.rn
            """,
            (agency_id, rows, agency_id),
        )
        session.execute(
            """
            INSERT INTO match_counts_cache (client_id, agency_id, count, computed_at, is_dirty)
            SELECT c.id, %s, 0, CURRENT_TIMESTAMP, 0
            FROM clients c
            WHERE c.agency_id = %s
            ON CONFLICT (client_id) DO UPDATE
            SET agency_id = EXCLUDED.agency_id,
                count = EXCLUDED.count,
                computed_at = EXCLUDED.computed_at,
                is_dirty = EXCLUDED.is_dirty
            """,
            (agency_id, agency_id),
        )


def _cleanup_dataset(agency_id: int) -> None:
    with admin_transaction() as session:
        session.execute("DELETE FROM match_counts_cache WHERE agency_id = %s", (agency_id,))
        session.execute("DELETE FROM demande_locations WHERE agency_id = %s", (agency_id,))
        session.execute("DELETE FROM offer_locations WHERE agency_id = %s", (agency_id,))
        session.execute("DELETE FROM demandes WHERE agency_id = %s", (agency_id,))
        session.execute("DELETE FROM offers WHERE agency_id = %s", (agency_id,))
        session.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
        session.execute("DELETE FROM listings WHERE agency_id = %s", (agency_id,))
        session.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_id,))
        session.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        session.execute(
            "DELETE FROM locations WHERE location_norm LIKE 'qb_loc_%%' AND NOT EXISTS ("
            "SELECT 1 FROM demande_locations dl WHERE dl.location_id = locations.location_id"
            ") AND NOT EXISTS ("
            "SELECT 1 FROM offer_locations ol WHERE ol.location_id = locations.location_id"
            ")"
        )


def main() -> None:
    rows = int(os.environ.get("IMMOAPP_QUERY_BUDGET_ROWS", "300"))
    agency_id = int(os.environ.get("IMMOAPP_QUERY_BUDGET_AGENCY_ID", "899991"))
    match_budget_ms = _budget("IMMOAPP_QUERY_BUDGET_MATCH_MS", 5000)
    search_budget_ms = _budget("IMMOAPP_QUERY_BUDGET_SEARCH_MS", 500)
    delta_budget_ms = _budget("IMMOAPP_QUERY_BUDGET_DELTA_MS", 500)
    cache_budget_ms = _budget("IMMOAPP_QUERY_BUDGET_CACHE_MS", 250)
    default_match_shared_blocks = max(75_000, rows * 250)
    default_search_shared_blocks = max(10_000, rows * 60)
    default_delta_shared_blocks = max(10_000, rows * 60)
    default_cache_shared_blocks = max(5_000, rows * 40)
    match_shared_blocks_budget = int(
        os.environ.get("IMMOAPP_QUERY_BUDGET_MATCH_SHARED_BLOCKS", default_match_shared_blocks)
    )
    search_shared_blocks_budget = int(
        os.environ.get("IMMOAPP_QUERY_BUDGET_SEARCH_SHARED_BLOCKS", default_search_shared_blocks)
    )
    delta_shared_blocks_budget = int(
        os.environ.get("IMMOAPP_QUERY_BUDGET_DELTA_SHARED_BLOCKS", default_delta_shared_blocks)
    )
    cache_shared_blocks_budget = int(
        os.environ.get("IMMOAPP_QUERY_BUDGET_CACHE_SHARED_BLOCKS", default_cache_shared_blocks)
    )

    _seed_dataset(agency_id, rows)
    metrics: dict[str, Any] = {}

    try:
        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().session() as session:
                q = build_client_counts_query(agency_id=agency_id)
                plan_rows = session.execute(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + q.sql, q.params
                ).fetchone()
                if not plan_rows:
                    raise SystemExit("verify_query_budgets: missing match plan output")
                match_metrics = _extract_plan_metrics(plan_rows["QUERY PLAN"])
                metrics["match_client_counts"] = match_metrics
                if match_metrics["execution_ms"] > match_budget_ms:
                    raise SystemExit(
                        "verify_query_budgets: match_client_counts exceeded budget "
                        f"({match_metrics['execution_ms']:.2f}ms > {match_budget_ms:.2f}ms)"
                    )
                _assert_buffer_budget(
                    "match_client_counts", match_metrics, match_shared_blocks_budget
                )

                search_plan = session.execute(
                    """
                    EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                    SELECT c.id
                    FROM clients c
                    WHERE c.agency_id = %s
                      AND c.deleted_at IS NULL
                      AND c.status = 'active'
                      AND c.family_name ILIKE %s
                    ORDER BY c.id
                    LIMIT 100
                    """,
                    (agency_id, "QB%"),
                ).fetchone()
                if not search_plan:
                    raise SystemExit("verify_query_budgets: missing search plan output")
                search_metrics = _extract_plan_metrics(search_plan["QUERY PLAN"])
                metrics["search_clients"] = search_metrics
                if search_metrics["execution_ms"] > search_budget_ms:
                    raise SystemExit(
                        "verify_query_budgets: search_clients exceeded budget "
                        f"({search_metrics['execution_ms']:.2f}ms > {search_budget_ms:.2f}ms)"
                    )
                _assert_no_hot_seq_scan("search_clients", search_metrics)
                _assert_buffer_budget("search_clients", search_metrics, search_shared_blocks_budget)

                since = "1970-01-01T00:00:00+00:00"
                delta_plan = session.execute(
                    """
                    EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                    SELECT c.id, c.updated_at
                    FROM clients c
                    WHERE c.agency_id = %s
                      AND c.updated_at > %s::timestamptz
                    ORDER BY c.updated_at, c.id
                    LIMIT 100
                    """,
                    (agency_id, since),
                ).fetchone()
                if not delta_plan:
                    raise SystemExit("verify_query_budgets: missing delta plan output")
                delta_metrics = _extract_plan_metrics(delta_plan["QUERY PLAN"])
                metrics["delta_clients"] = delta_metrics
                if delta_metrics["execution_ms"] > delta_budget_ms:
                    raise SystemExit(
                        "verify_query_budgets: delta_clients exceeded budget "
                        f"({delta_metrics['execution_ms']:.2f}ms > {delta_budget_ms:.2f}ms)"
                    )
                _assert_no_hot_seq_scan("delta_clients", delta_metrics)
                _assert_buffer_budget("delta_clients", delta_metrics, delta_shared_blocks_budget)

                cache_plan = session.execute(
                    """
                    EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                    SELECT client_id, count
                    FROM match_counts_cache
                    WHERE agency_id = %s
                    ORDER BY client_id
                    LIMIT 100
                    """,
                    (agency_id,),
                ).fetchone()
                if not cache_plan:
                    raise SystemExit("verify_query_budgets: missing cache plan output")
                cache_metrics = _extract_plan_metrics(cache_plan["QUERY PLAN"])
                metrics["cache_lookup"] = cache_metrics
                if cache_metrics["execution_ms"] > cache_budget_ms:
                    raise SystemExit(
                        "verify_query_budgets: cache_lookup exceeded budget "
                        f"({cache_metrics['execution_ms']:.2f}ms > {cache_budget_ms:.2f}ms)"
                    )
                _assert_no_hot_seq_scan("cache_lookup", cache_metrics)
                _assert_buffer_budget("cache_lookup", cache_metrics, cache_shared_blocks_budget)
    finally:
        _cleanup_dataset(agency_id)

    out_dir = Path("scripts/benchmark_outputs")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"query_budget_latest_{int(time.time())}.json"
    out_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print("verify_query_budgets: OK")
    print(f"verify_query_budgets: metrics written to {out_path}")


if __name__ == "__main__":
    main()
