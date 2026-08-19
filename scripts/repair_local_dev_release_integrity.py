from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import verify_release_backup_integrity as integrity  # noqa: E402

EXPECTED_LOCAL_DB_NAME = "immoapp"


@dataclass(frozen=True)
class RepairStep:
    name: str
    sql: str


REPAIR_STEPS: tuple[RepairStep, ...] = (
    RepairStep(
        name="auth_security_events.user_id_null_orphan",
        sql="""
            UPDATE auth_security_events t
            SET user_id = NULL
            WHERE t.user_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM accounts_user p WHERE p.id = t.user_id)
        """,
    ),
    RepairStep(
        name="auth_security_events.agency_id_null_orphan",
        sql="""
            UPDATE auth_security_events t
            SET agency_id = NULL
            WHERE t.agency_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
        """,
    ),
    RepairStep(
        name="task_failures.delete_missing_agency",
        sql="""
            DELETE FROM task_failures t
            WHERE t.agency_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
        """,
    ),
    RepairStep(
        name="imports_importreviewitem.delete_missing_job",
        sql="""
            DELETE FROM imports_importreviewitem t
            WHERE NOT EXISTS (SELECT 1 FROM imports_importjob p WHERE p.id = t.job_id)
        """,
    ),
    RepairStep(
        name="imports_importreviewgroup.delete_missing_job",
        sql="""
            DELETE FROM imports_importreviewgroup t
            WHERE NOT EXISTS (SELECT 1 FROM imports_importjob p WHERE p.id = t.job_id)
        """,
    ),
    RepairStep(
        name="imports_importworkflowstate.delete_missing_job",
        sql="""
            DELETE FROM imports_importworkflowstate t
            WHERE NOT EXISTS (SELECT 1 FROM imports_importjob p WHERE p.id = t.job_id)
        """,
    ),
    RepairStep(
        name="imports_importagencyprofile.delete_missing_agency",
        sql="""
            DELETE FROM imports_importagencyprofile t
            WHERE NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
        """,
    ),
    RepairStep(
        name="imports_importchunkphase.delete_missing_chunk",
        sql="""
            DELETE FROM imports_importchunkphase t
            WHERE NOT EXISTS (SELECT 1 FROM imports_importchunk p WHERE p.id = t.chunk_id)
        """,
    ),
    RepairStep(
        name="custom_locations.delete_missing_agency",
        sql="""
            DELETE FROM custom_locations t
            WHERE t.agency_id IS NULL
               OR NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
        """,
    ),
    RepairStep(
        name="demande_locations.delete_orphan",
        sql="""
            DELETE FROM demande_locations t
            WHERE t.agency_id IS NULL
               OR NOT EXISTS (SELECT 1 FROM demandes p WHERE p.id = t.demande_id)
               OR NOT EXISTS (SELECT 1 FROM locations p WHERE p.location_id = t.location_id)
               OR NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
        """,
    ),
    RepairStep(
        name="offer_locations.delete_orphan",
        sql="""
            DELETE FROM offer_locations t
            WHERE t.agency_id IS NULL
               OR NOT EXISTS (SELECT 1 FROM offers p WHERE p.id = t.offer_id)
               OR NOT EXISTS (SELECT 1 FROM locations p WHERE p.location_id = t.location_id)
               OR NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
        """,
    ),
    RepairStep(
        name="match_counts_cache.delete_orphan_or_mismatch",
        sql="""
            DELETE FROM match_counts_cache t
            WHERE t.agency_id IS NULL
               OR NOT EXISTS (SELECT 1 FROM clients p WHERE p.id = t.client_id)
               OR NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
               OR EXISTS (
                   SELECT 1
                   FROM clients c
                   WHERE c.id = t.client_id
                     AND t.agency_id IS DISTINCT FROM c.agency_id
               )
        """,
    ),
    RepairStep(
        name="surface_cache_generation.delete_missing_agency",
        sql="""
            DELETE FROM surface_cache_generation t
            WHERE t.agency_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
        """,
    ),
)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _environment_name() -> str:
    for name in (
        "IMMOAPP_ENVIRONMENT",
        "IMMOAPP_DEPLOY_ENV",
        "DJANGO_ENV",
        "ENVIRONMENT",
        "APP_ENV",
    ):
        value = os.environ.get(name)
        if value:
            return value.strip().lower()
    return ""


def _db_host() -> str:
    integrity._load_env()  # noqa: SLF001 - shared script-local env loader
    return (os.environ.get("POSTGRES_HOST") or "127.0.0.1").strip().lower()


def _db_name() -> str:
    integrity._load_env()  # noqa: SLF001 - shared script-local env loader
    return (os.environ.get("POSTGRES_DB") or EXPECTED_LOCAL_DB_NAME).strip().lower()


def _is_local_db_host(host: str) -> bool:
    return host in {
        "",
        "localhost",
        "127.0.0.1",
        "::1",
        "db",
        "postgres",
        "host.docker.internal",
        "projectc22-db-1",
    } or host.endswith(".docker.internal")


def _assert_apply_allowed(
    *,
    apply: bool,
    confirmed: bool,
    allow_non_default_local_database: bool,
    missing_schema: list[str],
) -> None:
    if not apply:
        return
    if not confirmed:
        raise RuntimeError(
            "Refusing to mutate without --confirm-disposable-local-data and --apply."
        )
    if missing_schema:
        raise RuntimeError("Refusing to repair because required schema is missing.")
    if _truthy(os.environ.get("IMMOAPP_PROD_CONFIG_STRICT")):
        raise RuntimeError("Refusing local-dev repair when IMMOAPP_PROD_CONFIG_STRICT is enabled.")
    if _environment_name() in {"prod", "production", "staging", "stage"}:
        raise RuntimeError("Refusing local-dev repair for production/staging environment.")
    host = _db_host()
    if not _is_local_db_host(host):
        raise RuntimeError(f"Refusing local-dev repair for non-local DB host: {host}")
    db_name = _db_name()
    if db_name != EXPECTED_LOCAL_DB_NAME and not allow_non_default_local_database:
        raise RuntimeError(
            "Refusing local-dev repair for non-default local DB "
            f"{db_name!r}; expected {EXPECTED_LOCAL_DB_NAME!r}. "
            "Pass --allow-non-default-local-database only for disposable local data."
        )


def _results_to_counts(results: list[integrity.IntegrityResult]) -> dict[str, int]:
    return {item.name: item.count for item in results}


def _run_integrity_checks(conn: psycopg.Connection[Any]) -> list[integrity.IntegrityResult]:
    return [*integrity.run_checks(conn), *integrity.run_storage_object_checks(conn)]


def _print_counts(title: str, results: list[integrity.IntegrityResult]) -> None:
    print(title)
    for result in results:
        print(f"{result.name}={result.count}")


def _apply_repairs(conn: psycopg.Connection[Any]) -> dict[str, int]:
    rowcounts: dict[str, int] = {}
    missing_storage_ids = [row["id"] for row in integrity.missing_ready_storage_objects(conn)]
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE auth_security_events DISABLE TRIGGER auth_security_events_no_mod"
            )
            try:
                for step in REPAIR_STEPS:
                    cur.execute(step.sql)
                    rowcounts[step.name] = int(cur.rowcount or 0)
                if missing_storage_ids:
                    cur.execute(
                        """
                        UPDATE offer_photos
                        SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                            delete_origin = COALESCE(delete_origin, 'manual'),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE storage_id = ANY(%s::uuid[])
                          AND deleted_at IS NULL
                        """,
                        (missing_storage_ids,),
                    )
                    rowcounts["offer_photos.soft_delete_missing_storage_bytes"] = int(
                        cur.rowcount or 0
                    )
                    cur.execute(
                        """
                        UPDATE storage_objects
                        SET status = 'deleted',
                            deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ANY(%s::uuid[])
                          AND status = 'ready'
                          AND deleted_at IS NULL
                        """,
                        (missing_storage_ids,),
                    )
                    rowcounts["storage_objects.soft_delete_missing_ready_bytes"] = int(
                        cur.rowcount or 0
                    )
                else:
                    rowcounts["offer_photos.soft_delete_missing_storage_bytes"] = 0
                    rowcounts["storage_objects.soft_delete_missing_ready_bytes"] = 0
            finally:
                cur.execute(
                    "ALTER TABLE auth_security_events ENABLE TRIGGER auth_security_events_no_mod"
                )
    return rowcounts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Explicit disposable-local repair for release backup integrity residue."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-disposable-local-data", action="store_true")
    parser.add_argument("--allow-non-default-local-database", action="store_true")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)

    integrity._load_env()  # noqa: SLF001 - shared script-local env loader
    db_host = _db_host()
    db_name = _db_name()
    env_name = _environment_name() or "local"
    print(f"db_host={db_host}")
    print(f"db_name={db_name}")
    print(f"environment={env_name}")

    with integrity.connect() as conn:
        missing_schema = integrity.validate_schema(conn)
        before = [] if missing_schema else _run_integrity_checks(conn)
        _assert_apply_allowed(
            apply=args.apply,
            confirmed=args.confirm_disposable_local_data,
            allow_non_default_local_database=args.allow_non_default_local_database,
            missing_schema=missing_schema,
        )
        if missing_schema:
            integrity.print_table([], missing_schema)
            return 1

        _print_counts("before", before)
        rowcounts: dict[str, int] = {}
        if args.apply:
            rowcounts = _apply_repairs(conn)
            print("repair_applied=1")
            for name, count in rowcounts.items():
                print(f"{name}.rows={count}")
        else:
            print("repair_applied=0")
            print("dry_run=1")
        after = _run_integrity_checks(conn)
        _print_counts("after", after)

    report = {
        "mode": "apply" if args.apply else "dry-run",
        "before": _results_to_counts(before),
        "after": _results_to_counts(after),
        "repair_rowcounts": rowcounts,
        "ok": all(item.count == 0 for item in after),
    }
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if args.apply and not report["ok"]:
        print("release_integrity_repair=failed: dirty checks remain", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
