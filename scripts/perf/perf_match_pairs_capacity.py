from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


def _bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django

    django.setup()


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = int(round((len(sorted_values) - 1) * p))
    return float(sorted_values[index])


@dataclass(frozen=True)
class CapacityReport:
    tag: str
    mode: str
    tenants_target: int
    demandes_per_tenant: int
    demande_batch_size: int
    tasks_enqueued: int
    tasks_success: int
    tasks_failed: int
    tasks_timed_out: int
    work_items_enqueued: int
    work_items_success: int
    work_items_failed: int
    work_items_timed_out: int
    timeout_hit: bool
    duration_seconds: float
    throughput_tasks_per_second: float
    throughput_work_items_per_second: float
    latency_p50_seconds: float
    latency_p95_seconds: float
    latency_p99_seconds: float
    latency_max_seconds: float
    generated_at_utc: str
    output_file: str


def _fetch_agency_ids(*, tag: str, limit: int) -> list[int]:
    from server.pg.uow import admin_transaction

    with admin_transaction() as session:
        rows = session.execute(
            """
            SELECT id
            FROM accounts_agency
            WHERE agency_code LIKE %s
            ORDER BY id
            LIMIT %s
            """,
            (f"PERF_{tag}_%", int(limit)),
        ).fetchall()
    return [int(row["id"] if isinstance(row, dict) else row[0]) for row in rows]


def _fetch_demande_targets(
    *,
    agency_ids: list[int],
    demandes_per_tenant: int,
) -> list[tuple[int, int]]:
    from server.pg.uow import admin_transaction

    if not agency_ids:
        return []
    with admin_transaction() as session:
        rows = session.execute(
            """
            WITH ranked AS (
                SELECT
                    d.agency_id,
                    d.id AS demande_id,
                    ROW_NUMBER() OVER (PARTITION BY d.agency_id ORDER BY d.id) AS rn
                FROM demandes d
                WHERE d.agency_id = ANY(%s)
                  AND d.deleted_at IS NULL
            )
            SELECT agency_id, demande_id
            FROM ranked
            WHERE rn <= %s
            ORDER BY agency_id, demande_id
            """,
            (agency_ids, int(demandes_per_tenant)),
        ).fetchall()
    targets: list[tuple[int, int]] = []
    for row in rows:
        if isinstance(row, dict):
            targets.append((int(row["agency_id"]), int(row["demande_id"])))
        else:
            targets.append((int(row[0]), int(row[1])))
    return targets


def _run_capacity(
    *,
    targets: list[tuple[int, int]],
    mode: str,
    demande_batch_size: int,
    timeout_seconds: int,
    poll_seconds: float,
) -> tuple[list[float], int, int, int, int, int, int, int, bool, float]:
    from server.api.tasks_match_pairs import (
        rebuild_match_pairs_for_demande,
        rebuild_match_pairs_for_demandes_batch,
    )

    if not targets:
        return [], 0, 0, 0, 0, 0, 0, 0, False, 0.0

    submitted_at: dict[str, float] = {}
    completed_at: dict[str, float] = {}
    task_work_items: dict[str, int] = {}
    task_ids: list[str] = []

    normalized_mode = str(mode or "single").strip().lower()
    batch_size = max(1, int(demande_batch_size))
    if normalized_mode == "batch":
        by_agency: dict[int, list[int]] = {}
        for agency_id, demande_id in targets:
            by_agency.setdefault(int(agency_id), []).append(int(demande_id))
        for agency_id, demande_ids in by_agency.items():
            for index in range(0, len(demande_ids), batch_size):
                demande_batch = demande_ids[index : index + batch_size]
                task = rebuild_match_pairs_for_demandes_batch.apply_async(
                    args=(demande_batch,),
                    kwargs={"agency_id": int(agency_id)},
                )
                task_id = str(task.id)
                task_ids.append(task_id)
                submitted_at[task_id] = time.perf_counter()
                task_work_items[task_id] = len(demande_batch)
    else:
        for agency_id, demande_id in targets:
            task = rebuild_match_pairs_for_demande.apply_async(
                args=(int(demande_id),),
                kwargs={"agency_id": int(agency_id)},
            )
            task_id = str(task.id)
            task_ids.append(task_id)
            submitted_at[task_id] = time.perf_counter()
            task_work_items[task_id] = 1

    from server.immoapp_server.celery import celery_app

    start = time.perf_counter()
    timeout_hit = False
    while True:
        pending = 0
        for task_id in task_ids:
            if task_id in completed_at:
                continue
            result = celery_app.AsyncResult(task_id)
            if result.ready():
                completed_at[task_id] = time.perf_counter()
            else:
                pending += 1
        if pending == 0:
            break
        if time.perf_counter() - start >= timeout_seconds:
            timeout_hit = True
            break
        time.sleep(max(0.05, float(poll_seconds)))

    duration = time.perf_counter() - start
    latencies: list[float] = []
    success = 0
    failed = 0
    timed_out = 0
    work_success = 0
    work_failed = 0
    work_timed_out = 0
    for task_id in task_ids:
        workload = max(1, int(task_work_items.get(task_id, 1)))
        completed = completed_at.get(task_id)
        if completed is None:
            timed_out += 1
            work_timed_out += workload
            continue
        result = celery_app.AsyncResult(task_id)
        if result.successful():
            success += 1
            work_success += workload
        else:
            failed += 1
            work_failed += workload
        latency = max(0.0, completed - submitted_at[task_id])
        latencies.extend([latency] * workload)
    return (
        latencies,
        success,
        failed,
        timed_out,
        work_success,
        work_failed,
        work_timed_out,
        len(task_ids),
        timeout_hit,
        duration,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure match-pairs queue throughput/latency on seeded perf tenants.",
    )
    parser.add_argument(
        "--tag", required=True, help="Perf seed tag used by perf_seed_multitenant.py"
    )
    parser.add_argument("--tenants", type=int, default=1000)
    parser.add_argument("--demandes-per-tenant", type=int, default=1)
    parser.add_argument(
        "--mode",
        choices=["single", "batch"],
        default="single",
        help="single = one demande per task, batch = chunk demandes per tenant task.",
    )
    parser.add_argument(
        "--demande-batch-size",
        type=int,
        default=100,
        help="Batch size when --mode=batch.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--poll-seconds", type=float, default=0.2)
    parser.add_argument(
        "--output-file",
        default="",
        help="Optional explicit path. Defaults to scripts/perf_outputs/match_pairs_capacity_<tag>.json",
    )
    return parser.parse_args()


def main() -> None:
    _bootstrap()
    args = _parse_args()

    agency_ids = _fetch_agency_ids(tag=str(args.tag), limit=int(args.tenants))
    if not agency_ids:
        raise SystemExit(
            f"No perf agencies found for tag={args.tag}. Seed first with scripts/perf/perf_seed_multitenant.py."
        )
    targets = _fetch_demande_targets(
        agency_ids=agency_ids,
        demandes_per_tenant=max(1, int(args.demandes_per_tenant)),
    )
    if not targets:
        raise SystemExit("No demande targets found for selected agencies.")

    (
        latencies,
        success,
        failed,
        timed_out,
        work_success,
        work_failed,
        work_timed_out,
        tasks_enqueued,
        timeout_hit,
        duration,
    ) = _run_capacity(
        targets=targets,
        mode=str(args.mode),
        demande_batch_size=max(1, int(args.demande_batch_size)),
        timeout_seconds=max(30, int(args.timeout_seconds)),
        poll_seconds=max(0.05, float(args.poll_seconds)),
    )
    throughput_tasks = float(success + failed) / duration if duration > 0 else 0.0
    throughput_work_items = float(work_success + work_failed) / duration if duration > 0 else 0.0
    p50 = _percentile(latencies, 0.50)
    p95 = _percentile(latencies, 0.95)
    p99 = _percentile(latencies, 0.99)
    pmax = max(latencies) if latencies else 0.0

    default_output = Path("scripts/perf_outputs") / f"match_pairs_capacity_{args.tag}.json"
    output_path = Path(args.output_file) if args.output_file else default_output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report = CapacityReport(
        tag=str(args.tag),
        mode=str(args.mode),
        tenants_target=int(args.tenants),
        demandes_per_tenant=max(1, int(args.demandes_per_tenant)),
        demande_batch_size=max(1, int(args.demande_batch_size)),
        work_items_enqueued=int(len(targets)),
        work_items_success=int(work_success),
        work_items_failed=int(work_failed),
        work_items_timed_out=int(work_timed_out),
        tasks_enqueued=int(tasks_enqueued),
        tasks_success=int(success),
        tasks_failed=int(failed),
        tasks_timed_out=int(timed_out),
        timeout_hit=bool(timeout_hit),
        duration_seconds=round(duration, 3),
        throughput_tasks_per_second=round(throughput_tasks, 3),
        throughput_work_items_per_second=round(throughput_work_items, 3),
        latency_p50_seconds=round(p50, 3),
        latency_p95_seconds=round(p95, 3),
        latency_p99_seconds=round(p99, 3),
        latency_max_seconds=round(pmax, 3),
        generated_at_utc=datetime.now(tz=timezone.utc).isoformat(),
        output_file=str(output_path),
    )
    output_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

    print(
        "perf_match_pairs_capacity: "
        f"mode={report.mode} batch_size={report.demande_batch_size} "
        f"tasks={report.tasks_enqueued} success={report.tasks_success} failed={report.tasks_failed} timed_out={report.tasks_timed_out} "
        f"work_items={report.work_items_enqueued} timed_out_work={report.work_items_timed_out} "
        f"throughput_tasks={report.throughput_tasks_per_second}/s "
        f"throughput_work={report.throughput_work_items_per_second}/s "
        f"p95={report.latency_p95_seconds}s p99={report.latency_p99_seconds}s "
        f"timeout_hit={report.timeout_hit} output={output_path}"
    )


if __name__ == "__main__":
    main()
