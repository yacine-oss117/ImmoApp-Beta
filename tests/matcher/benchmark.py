import sys
import time
from pathlib import Path

# Add repo root to sys.path
repo_root = Path(__file__).resolve().parents[2]
sys.path.append(str(repo_root))

from core.matcher.match_queries import build_match_cte  # noqa: E402
from server.pg.uow import admin_transaction  # noqa: E402


def run_performance_test():
    with admin_transaction() as session:
        # Get count to ensure data exists
        offers_count = session.execute("SELECT COUNT(*) FROM offers").fetchone()
        demandes_count = session.execute("SELECT COUNT(*) FROM demandes").fetchone()
        print(
            f"Dataset: {list(offers_count.values())[0]} offers, {list(demandes_count.values())[0]} demandes."
        )

        # Test Case 1: Matching all demands (Batch test)
        cte = build_match_cte(select_cols="d.id, o.id")

        print("\n--- Running EXPLAIN (ANALYZE, BUFFERS) on full matching CTE ---")
        explain_sql = f"EXPLAIN (ANALYZE, BUFFERS) {cte.sql} SELECT * FROM matched_pairs"
        explain_results = session.execute(explain_sql, cte.params).fetchall()

        for row in explain_results:
            print(list(row.values())[0])

        # Test Case 2: P95 Latency for single random demand
        print("\n--- Measuring P95 Latency for single-demande matching ---")
        random_demande = session.execute(
            "SELECT id FROM demandes ORDER BY random() LIMIT 1"
        ).fetchone()
        if not random_demande:
            print("No demandes found to test.")
            return

        did = list(random_demande.values())[0]
        latencies = []
        for _ in range(50):
            single_cte = build_match_cte(demande_ids=[did], select_cols="o.id")
            full_sql = f"{single_cte.sql} SELECT * FROM matched_pairs"
            start = time.monotonic()
            session.execute(full_sql, single_cte.params)
            latencies.append((time.monotonic() - start) * 1000)  # ms

        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]

        print(f"Single Demande Match (ID: {did}):")
        print(f"  P50: {p50:.2f}ms")
        print(f"  P95: {p95:.2f}ms")
        print(f"  P99: {p99:.2f}ms")


if __name__ == "__main__":
    run_performance_test()
