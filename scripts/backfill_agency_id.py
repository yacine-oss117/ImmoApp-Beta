"""
Backfill NULL agency_id values in all tenant tables.
Run: python scripts/backfill_agency_id.py
"""

from __future__ import annotations

import os
import sys

# Setup paths
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")

import django

django.setup()

from server.pg.uow import admin_transaction

TENANT_TABLES = [
    "clients",
    "listings",
    "visits",
    "contracts",
    "demandes",
    "offers",
    "custom_locations",
    "wa_templates",
    "agency_settings",
    "audit_logs",
    "contract_articles",
    "match_counts_cache",
    "demande_locations",
    "offer_locations",
    "match_pairs",
    "match_candidates",
    "task_failures",
    "imports_importjob",
    "imports_importrowaudit",
    "imports_importchunk",
    "imports_importartifactmanifest",
]


def backfill_null_agency_ids() -> dict[str, int]:
    """Backfill NULL agency_id values using the first available agency."""
    counts: dict[str, int] = {}

    with admin_transaction() as session:
        # Get first agency
        row = session.execute("SELECT id FROM accounts_agency ORDER BY id LIMIT 1").fetchone()
        if not row:
            print("ERROR: No agency found in accounts_agency!")
            return counts

        agency_id = int(row["id"])
        print(f"Using agency_id: {agency_id}")
        print("-" * 50)

        for table in TENANT_TABLES:
            # Check if table exists
            exists = session.execute(
                "SELECT to_regclass('public.' || %s) AS name", (table,)
            ).fetchone()
            if not exists or not exists.get("name"):
                print(f"{table}: SKIPPED (table does not exist)")
                continue

            # Check if agency_id column exists
            col_check = session.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s AND column_name = 'agency_id'
                """,
                (table,),
            ).fetchone()
            if not col_check:
                print(f"{table}: SKIPPED (no agency_id column)")
                continue

            # Count NULLs
            count_row = session.execute(
                f"SELECT COUNT(*) as c FROM {table} WHERE agency_id IS NULL"  # noqa: S608
            ).fetchone()
            null_count = int(count_row["c"]) if count_row else 0

            if null_count > 0:
                session.execute(
                    f"UPDATE {table} SET agency_id = %s WHERE agency_id IS NULL",  # noqa: S608
                    (agency_id,),
                )
                print(f"{table}: {null_count} NULL rows -> BACKFILLED")
                counts[table] = null_count
            else:
                print(f"{table}: OK (no NULLs)")
                counts[table] = 0

    print("-" * 50)
    print("SUMMARY:")
    total = sum(counts.values())
    if total > 0:
        print(f"  Total backfilled: {total} rows")
    else:
        print("  All tables clean - no NULL agency_id values found!")

    return counts


if __name__ == "__main__":
    backfill_null_agency_ids()
