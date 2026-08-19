from __future__ import annotations

import importlib.util
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")

from server.pg.uow import _build_dsn  # noqa: E402


def _load_query_budget_module():
    module_path = _REPO_ROOT / "scripts" / "verify_query_budgets.py"
    spec = importlib.util.spec_from_file_location("verify_query_budgets", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit("verify_load_baseline: failed to load verify_query_budgets module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = int(round((len(sorted_values) - 1) * p))
    return sorted_values[index]


def _measure_query(sql: str, params: tuple[object, ...]) -> float:
    start = time.perf_counter()
    with psycopg.connect(_build_dsn(), row_factory=dict_row) as conn:
        conn.execute("SET search_path TO public")
        conn.execute("SELECT set_config('app.current_agency_id', %s, true)", (str(params[0]),))
        conn.execute("SELECT set_config('app.is_superuser', 'false', true)")
        conn.execute("SELECT set_config('app.actor_id', '', true)")
        conn.execute("SELECT set_config('app.actor_role', '', true)")
        conn.execute("SELECT set_config('app.actor_is_owner', 'false', true)")
        conn.execute(sql, params).fetchall()
    return (time.perf_counter() - start) * 1000.0


def _worker_run(*, agency_id: int, iterations: int) -> dict[str, list[float]]:
    search_times: list[float] = []
    cache_times: list[float] = []
    for _ in range(iterations):
        search_times.append(
            _measure_query(
                """
                SELECT id
                FROM clients
                WHERE agency_id = %s
                  AND deleted_at IS NULL
                  AND status = 'active'
                ORDER BY id
                LIMIT 50
                """,
                (agency_id,),
            )
        )
        cache_times.append(
            _measure_query(
                """
                SELECT client_id, count
                FROM match_counts_cache
                WHERE agency_id = %s
                ORDER BY client_id
                LIMIT 50
                """,
                (agency_id,),
            )
        )
    return {"search": search_times, "cache": cache_times}


def main() -> None:
    rows = int(os.environ.get("IMMOAPP_LOAD_ROWS", "250"))
    workers = int(os.environ.get("IMMOAPP_LOAD_WORKERS", "3"))
    iterations = int(os.environ.get("IMMOAPP_LOAD_ITERATIONS", "10"))
    agency_id = int(os.environ.get("IMMOAPP_LOAD_AGENCY_ID", "899992"))
    p95_search_budget_ms = float(os.environ.get("IMMOAPP_LOAD_P95_SEARCH_MS", "250"))
    p95_cache_budget_ms = float(os.environ.get("IMMOAPP_LOAD_P95_CACHE_MS", "200"))

    qb = _load_query_budget_module()
    qb._seed_dataset(agency_id, rows)  # noqa: SLF001
    search_samples: list[float] = []
    cache_samples: list[float] = []

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(_worker_run, agency_id=agency_id, iterations=iterations)
                for _ in range(workers)
            ]
            for future in as_completed(futures):
                result = future.result()
                search_samples.extend(result["search"])
                cache_samples.extend(result["cache"])
    finally:
        qb._cleanup_dataset(agency_id)  # noqa: SLF001

    p95_search = _percentile(search_samples, 0.95)
    p95_cache = _percentile(cache_samples, 0.95)
    mean_search = statistics.fmean(search_samples) if search_samples else 0.0
    mean_cache = statistics.fmean(cache_samples) if cache_samples else 0.0

    if p95_search > p95_search_budget_ms:
        raise SystemExit(
            "verify_load_baseline: search p95 budget exceeded "
            f"({p95_search:.2f}ms > {p95_search_budget_ms:.2f}ms)"
        )
    if p95_cache > p95_cache_budget_ms:
        raise SystemExit(
            "verify_load_baseline: cache p95 budget exceeded "
            f"({p95_cache:.2f}ms > {p95_cache_budget_ms:.2f}ms)"
        )

    print(
        "verify_load_baseline: OK "
        f"(search mean={mean_search:.2f}ms p95={p95_search:.2f}ms; "
        f"cache mean={mean_cache:.2f}ms p95={p95_cache:.2f}ms)"
    )


if __name__ == "__main__":
    main()
