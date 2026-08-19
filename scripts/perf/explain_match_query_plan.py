from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django

    django.setup()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run EXPLAIN ANALYZE on the legacy matcher SQL or direct artifact pipeline.",
    )
    parser.add_argument("--agency-id", type=int, default=0)
    parser.add_argument("--tag", default="", help="Optional PERF_<tag> agency prefix resolver.")
    parser.add_argument("--sample-demandes", type=int, default=200)
    parser.add_argument(
        "--pipeline",
        choices=("legacy", "direct"),
        default="legacy",
        help="Pipeline to analyze.",
    )
    parser.add_argument(
        "--output-file",
        default="",
        help="Optional explicit output path. Defaults to scripts/perf_outputs/explain_match_query_<pipeline>_<id>.json",
    )
    return parser.parse_args()


def _resolve_agency_id(*, agency_id: int, tag: str) -> int:
    if agency_id > 0:
        return int(agency_id)
    if not tag:
        raise SystemExit("Provide --agency-id or --tag.")
    from server.pg.uow import admin_transaction

    with admin_transaction() as session:
        row = session.execute(
            """
            SELECT id
            FROM accounts_agency
            WHERE agency_code LIKE %s
            ORDER BY id
            LIMIT 1
            """,
            (f"PERF_{tag}_%",),
        ).fetchone()
    resolved = int((row or {}).get("id") or 0)
    if resolved <= 0:
        raise SystemExit(f"No agency found for tag={tag}.")
    return resolved


def _sample_demande_ids(*, agency_id: int, sample_size: int) -> list[int]:
    from server.pg.uow import admin_transaction

    with admin_transaction() as session:
        rows = session.execute(
            """
                SELECT d.id
                FROM demandes d
                WHERE d.agency_id = %s
                  AND d.deleted_at IS NULL
                ORDER BY d.id
                LIMIT %s
                """,
            (int(agency_id), max(1, int(sample_size))),
        ).fetchall()
    ids = [int((row or {}).get("id") or 0) for row in rows]
    return [item for item in ids if item > 0]


def _first_value(row: dict[str, Any] | None) -> Any:
    if not row:
        return None
    if "QUERY PLAN" in row:
        return row["QUERY PLAN"]
    for value in row.values():
        return value
    return None


def _run_explain_legacy(*, agency_id: int, demande_ids: list[int]) -> dict[str, Any]:
    from core.matcher.match_queries import build_match_cte
    from server.pg.uow import admin_transaction

    cte = build_match_cte(
        demande_ids=demande_ids,
        include_numeric=True,
        select_cols="d.id AS demande_id, o.id AS offer_id",
    )
    sql = f"""
        EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
        {cte.sql}
        SELECT COUNT(*) AS total_pairs
        FROM matched_pairs
    """
    with admin_transaction() as session:
        row = session.execute(sql, list(cte.params)).fetchone()
    raw_plan = _first_value(row)
    if isinstance(raw_plan, list) and raw_plan:
        first = raw_plan[0]
        if isinstance(first, dict):
            return first
    if isinstance(raw_plan, dict):
        return raw_plan
    return {}


def _run_explain_direct(*, agency_id: int, demande_ids: list[int]) -> dict[str, Any]:
    from core.data.match_artifact_pipeline import explain_match_artifacts_for_demandes
    from server.pg.uow import admin_transaction

    with admin_transaction() as session:
        session.execute(
            "SELECT set_config('app.current_agency_id', %s, true)",
            (str(int(agency_id)),),
        )
        return explain_match_artifacts_for_demandes(
            session,
            demande_ids,
            limit=100,
        )


def _walk_plan_nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if not isinstance(current, dict):
            continue
        out.append(current)
        plans = current.get("Plans")
        if isinstance(plans, list):
            for child in plans:
                if isinstance(child, dict):
                    stack.append(child)
    return out


def _root_metric(root: dict[str, Any], key: str) -> int:
    value = root.get(key)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _summarize(*, pipeline: str, plan_json: dict[str, Any]) -> dict[str, Any]:
    root = plan_json.get("Plan")
    if not isinstance(root, dict):
        return {
            "ok": False,
            "reason": "No plan payload returned.",
            "pipeline": pipeline,
            "recommendation": "UNKNOWN",
        }
    nodes = _walk_plan_nodes(root)
    offer_seq_scan_count = 0
    offer_scan_nodes: list[str] = []
    used_surface_index = False
    used_beds_index = False
    used_budget_gist = False
    sort_spill_nodes = 0
    hash_spill_nodes = 0

    for node in nodes:
        relation = str(node.get("Relation Name") or "")
        node_type = str(node.get("Node Type") or "")
        index_name = str(node.get("Index Name") or "")
        if relation == "offers":
            offer_scan_nodes.append(node_type)
            if node_type == "Seq Scan":
                offer_seq_scan_count += 1
        lowered_index = index_name.lower()
        if "idx_offers_surface" in lowered_index:
            used_surface_index = True
        if "idx_offers_beds" in lowered_index:
            used_beds_index = True
        if "idx_offers_budget_range_gist" in lowered_index:
            used_budget_gist = True
        if str(node.get("Sort Space Type") or "").lower() == "disk":
            sort_spill_nodes += 1
        try:
            if int(node.get("Hash Batches") or 1) > 1:
                hash_spill_nodes += 1
        except (TypeError, ValueError):
            continue

    shared_hit_blocks = _root_metric(root, "Shared Hit Blocks")
    shared_read_blocks = _root_metric(root, "Shared Read Blocks")
    shared_dirtied_blocks = _root_metric(root, "Shared Dirtied Blocks")
    temp_read_blocks = _root_metric(root, "Temp Read Blocks")
    temp_written_blocks = _root_metric(root, "Temp Written Blocks")

    if (
        temp_written_blocks > 0
        or temp_read_blocks > 0
        or sort_spill_nodes > 0
        or hash_spill_nodes > 0
    ):
        recommendation = "REDUCE_BATCH_SIZE_OR_FULL_SQL_THRESHOLD"
        decision_basis = (
            "The plan spilled to temp storage or batched hashes. Reduce demande batch size or "
            "full-SQL threshold before considering database-level memory tuning."
        )
    elif offer_seq_scan_count > 0 and not (used_surface_index or used_beds_index):
        recommendation = "TRIAL_REWRITE_TO_BETWEEN_OR_TRIAL_GIST"
        decision_basis = (
            "Planner fell back to sequential offers scans for the numeric match path. "
            "Run a controlled rewrite/index experiment before rollout."
        )
    elif pipeline == "direct":
        recommendation = "DIRECT_READY"
        decision_basis = (
            "Direct pipeline completed without spill indicators in this sample. "
            "Proceed to benchmark comparison before rollout."
        )
    else:
        recommendation = "KEEP_BTREE_AND_CURRENT_PREDICATE"
        decision_basis = "Legacy matcher plan does not show a new index/regression signal."

    execution_ms = float(plan_json.get("Execution Time") or 0.0)
    planning_ms = float(plan_json.get("Planning Time") or 0.0)
    return {
        "ok": True,
        "pipeline": pipeline,
        "recommendation": recommendation,
        "decision_basis": decision_basis,
        "execution_time_ms": round(execution_ms, 3),
        "planning_time_ms": round(planning_ms, 3),
        "offer_seq_scan_count": int(offer_seq_scan_count),
        "offer_scan_nodes": offer_scan_nodes,
        "used_surface_index": bool(used_surface_index),
        "used_beds_index": bool(used_beds_index),
        "used_budget_range_gist": bool(used_budget_gist),
        "shared_hit_blocks": shared_hit_blocks,
        "shared_read_blocks": shared_read_blocks,
        "shared_dirtied_blocks": shared_dirtied_blocks,
        "temp_read_blocks": temp_read_blocks,
        "temp_written_blocks": temp_written_blocks,
        "sort_spill_nodes": int(sort_spill_nodes),
        "hash_spill_nodes": int(hash_spill_nodes),
    }


def main() -> None:
    _bootstrap()
    args = _parse_args()
    pipeline = str(args.pipeline)
    agency_id = _resolve_agency_id(agency_id=int(args.agency_id), tag=str(args.tag))
    demande_ids = _sample_demande_ids(
        agency_id=agency_id,
        sample_size=max(1, int(args.sample_demandes)),
    )
    if not demande_ids:
        raise SystemExit(f"No demandes found for agency_id={agency_id}.")

    if pipeline == "direct":
        plan_json = _run_explain_direct(agency_id=agency_id, demande_ids=demande_ids)
    else:
        plan_json = _run_explain_legacy(agency_id=agency_id, demande_ids=demande_ids)
    summary = _summarize(pipeline=pipeline, plan_json=plan_json)

    if args.output_file:
        output_path = Path(args.output_file)
    else:
        output_path = (
            Path("scripts/perf_outputs") / f"explain_match_query_{pipeline}_{agency_id}.json"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "agency_id": agency_id,
        "pipeline": pipeline,
        "sample_demandes": len(demande_ids),
        "generated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "summary": summary,
        "plan": plan_json,
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        "explain_match_query_plan: "
        f"pipeline={pipeline} agency_id={agency_id} sample={len(demande_ids)} "
        f"recommendation={summary.get('recommendation')} "
        f"execution_ms={summary.get('execution_time_ms')} "
        f"output={output_path}"
    )


if __name__ == "__main__":
    main()
