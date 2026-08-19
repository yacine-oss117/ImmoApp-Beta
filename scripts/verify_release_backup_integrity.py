from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import psycopg
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from psycopg.rows import dict_row

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.env_files import resolve_env_file  # noqa: E402


@dataclass(frozen=True)
class IntegrityCheck:
    name: str
    table: str
    issue: str
    count_sql: str
    sample_sql: str


@dataclass(frozen=True)
class IntegrityResult:
    name: str
    table: str
    issue: str
    count: int
    sample_ids: list[str]


REQUIRED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("auth_security_events", "user_id"),
    ("auth_security_events", "agency_id"),
    ("accounts_user", "id"),
    ("accounts_agency", "id"),
    ("task_failures", "agency_id"),
    ("demande_locations", "demande_id"),
    ("demande_locations", "location_id"),
    ("demande_locations", "agency_id"),
    ("demandes", "id"),
    ("demandes", "agency_id"),
    ("locations", "location_id"),
    ("offer_locations", "offer_id"),
    ("offer_locations", "location_id"),
    ("offer_locations", "agency_id"),
    ("offers", "id"),
    ("offers", "agency_id"),
    ("match_counts_cache", "client_id"),
    ("match_counts_cache", "agency_id"),
    ("clients", "id"),
    ("clients", "agency_id"),
    ("surface_cache_generation", "agency_id"),
    ("imports_importworkflowstate", "job_id"),
    ("imports_importreviewgroup", "job_id"),
    ("imports_importreviewitem", "job_id"),
    ("imports_importjob", "id"),
    ("imports_importagencyprofile", "agency_id"),
    ("imports_importchunkphase", "chunk_id"),
    ("imports_importchunk", "id"),
    ("custom_locations", "id"),
    ("custom_locations", "agency_id"),
    ("storage_objects", "id"),
    ("storage_objects", "bucket"),
    ("storage_objects", "object_key"),
    ("storage_objects", "status"),
    ("storage_objects", "deleted_at"),
)


CHECKS: tuple[IntegrityCheck, ...] = (
    IntegrityCheck(
        name="auth_security_events.user_id",
        table="auth_security_events",
        issue="missing_accounts_user",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM auth_security_events t
            WHERE t.user_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM accounts_user p WHERE p.id = t.user_id)
        """,
        sample_sql="""
            SELECT t.id::text AS sample_id
            FROM auth_security_events t
            WHERE t.user_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM accounts_user p WHERE p.id = t.user_id)
            ORDER BY t.id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="auth_security_events.agency_id",
        table="auth_security_events",
        issue="missing_accounts_agency",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM auth_security_events t
            WHERE t.agency_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
        """,
        sample_sql="""
            SELECT t.id::text AS sample_id
            FROM auth_security_events t
            WHERE t.agency_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
            ORDER BY t.id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="task_failures.agency_id",
        table="task_failures",
        issue="missing_accounts_agency",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM task_failures t
            WHERE t.agency_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
        """,
        sample_sql="""
            SELECT t.id::text AS sample_id
            FROM task_failures t
            WHERE t.agency_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
            ORDER BY t.id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="demande_locations.demande_id",
        table="demande_locations",
        issue="missing_demande",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM demande_locations t
            WHERE NOT EXISTS (SELECT 1 FROM demandes p WHERE p.id = t.demande_id)
        """,
        sample_sql="""
            SELECT (t.demande_id::text || ':' || t.location_id::text) AS sample_id
            FROM demande_locations t
            WHERE NOT EXISTS (SELECT 1 FROM demandes p WHERE p.id = t.demande_id)
            ORDER BY t.demande_id, t.location_id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="demande_locations.location_id",
        table="demande_locations",
        issue="missing_location",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM demande_locations t
            WHERE NOT EXISTS (SELECT 1 FROM locations p WHERE p.location_id = t.location_id)
        """,
        sample_sql="""
            SELECT (t.demande_id::text || ':' || t.location_id::text) AS sample_id
            FROM demande_locations t
            WHERE NOT EXISTS (SELECT 1 FROM locations p WHERE p.location_id = t.location_id)
            ORDER BY t.demande_id, t.location_id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="demande_locations.agency_id",
        table="demande_locations",
        issue="missing_accounts_agency",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM demande_locations t
            WHERE t.agency_id IS NULL
               OR NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
        """,
        sample_sql="""
            SELECT (t.demande_id::text || ':' || t.location_id::text) AS sample_id
            FROM demande_locations t
            WHERE t.agency_id IS NULL
               OR NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
            ORDER BY t.demande_id, t.location_id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="offer_locations.offer_id",
        table="offer_locations",
        issue="missing_offer",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM offer_locations t
            WHERE NOT EXISTS (SELECT 1 FROM offers p WHERE p.id = t.offer_id)
        """,
        sample_sql="""
            SELECT (t.offer_id::text || ':' || t.location_id::text) AS sample_id
            FROM offer_locations t
            WHERE NOT EXISTS (SELECT 1 FROM offers p WHERE p.id = t.offer_id)
            ORDER BY t.offer_id, t.location_id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="offer_locations.location_id",
        table="offer_locations",
        issue="missing_location",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM offer_locations t
            WHERE NOT EXISTS (SELECT 1 FROM locations p WHERE p.location_id = t.location_id)
        """,
        sample_sql="""
            SELECT (t.offer_id::text || ':' || t.location_id::text) AS sample_id
            FROM offer_locations t
            WHERE NOT EXISTS (SELECT 1 FROM locations p WHERE p.location_id = t.location_id)
            ORDER BY t.offer_id, t.location_id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="offer_locations.agency_id",
        table="offer_locations",
        issue="missing_accounts_agency",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM offer_locations t
            WHERE t.agency_id IS NULL
               OR NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
        """,
        sample_sql="""
            SELECT (t.offer_id::text || ':' || t.location_id::text) AS sample_id
            FROM offer_locations t
            WHERE t.agency_id IS NULL
               OR NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
            ORDER BY t.offer_id, t.location_id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="match_counts_cache.client_id",
        table="match_counts_cache",
        issue="missing_client",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM match_counts_cache t
            WHERE NOT EXISTS (SELECT 1 FROM clients p WHERE p.id = t.client_id)
        """,
        sample_sql="""
            SELECT (COALESCE(t.agency_id::text, 'null') || ':' || t.client_id::text) AS sample_id
            FROM match_counts_cache t
            WHERE NOT EXISTS (SELECT 1 FROM clients p WHERE p.id = t.client_id)
            ORDER BY t.agency_id, t.client_id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="match_counts_cache.agency_id",
        table="match_counts_cache",
        issue="missing_accounts_agency",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM match_counts_cache t
            WHERE t.agency_id IS NULL
               OR NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
        """,
        sample_sql="""
            SELECT (COALESCE(t.agency_id::text, 'null') || ':' || t.client_id::text) AS sample_id
            FROM match_counts_cache t
            WHERE t.agency_id IS NULL
               OR NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
            ORDER BY t.agency_id, t.client_id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="match_counts_cache.client_agency_pair",
        table="match_counts_cache",
        issue="tenant_pair_mismatch",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM match_counts_cache t
            JOIN clients c ON c.id = t.client_id
            WHERE t.agency_id IS DISTINCT FROM c.agency_id
        """,
        sample_sql="""
            SELECT (t.agency_id::text || ':' || t.client_id::text) AS sample_id
            FROM match_counts_cache t
            JOIN clients c ON c.id = t.client_id
            WHERE t.agency_id IS DISTINCT FROM c.agency_id
            ORDER BY t.agency_id, t.client_id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="surface_cache_generation.agency_id",
        table="surface_cache_generation",
        issue="missing_accounts_agency",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM surface_cache_generation t
            WHERE t.agency_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
        """,
        sample_sql="""
            SELECT t.agency_id::text AS sample_id
            FROM surface_cache_generation t
            WHERE t.agency_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
            ORDER BY t.agency_id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="imports_importworkflowstate.job_id",
        table="imports_importworkflowstate",
        issue="missing_import_job",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM imports_importworkflowstate t
            WHERE NOT EXISTS (SELECT 1 FROM imports_importjob p WHERE p.id = t.job_id)
        """,
        sample_sql="""
            SELECT t.job_id::text AS sample_id
            FROM imports_importworkflowstate t
            WHERE NOT EXISTS (SELECT 1 FROM imports_importjob p WHERE p.id = t.job_id)
            ORDER BY t.job_id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="imports_importreviewgroup.job_id",
        table="imports_importreviewgroup",
        issue="missing_import_job",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM imports_importreviewgroup t
            WHERE NOT EXISTS (SELECT 1 FROM imports_importjob p WHERE p.id = t.job_id)
        """,
        sample_sql="""
            SELECT t.job_id::text AS sample_id
            FROM imports_importreviewgroup t
            WHERE NOT EXISTS (SELECT 1 FROM imports_importjob p WHERE p.id = t.job_id)
            ORDER BY t.job_id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="imports_importreviewitem.job_id",
        table="imports_importreviewitem",
        issue="missing_import_job",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM imports_importreviewitem t
            WHERE NOT EXISTS (SELECT 1 FROM imports_importjob p WHERE p.id = t.job_id)
        """,
        sample_sql="""
            SELECT t.job_id::text AS sample_id
            FROM imports_importreviewitem t
            WHERE NOT EXISTS (SELECT 1 FROM imports_importjob p WHERE p.id = t.job_id)
            ORDER BY t.job_id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="imports_importagencyprofile.agency_id",
        table="imports_importagencyprofile",
        issue="missing_accounts_agency",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM imports_importagencyprofile t
            WHERE NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
        """,
        sample_sql="""
            SELECT t.agency_id::text AS sample_id
            FROM imports_importagencyprofile t
            WHERE NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
            ORDER BY t.agency_id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="imports_importchunkphase.chunk_id",
        table="imports_importchunkphase",
        issue="missing_import_chunk",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM imports_importchunkphase t
            WHERE NOT EXISTS (SELECT 1 FROM imports_importchunk p WHERE p.id = t.chunk_id)
        """,
        sample_sql="""
            SELECT t.chunk_id::text AS sample_id
            FROM imports_importchunkphase t
            WHERE NOT EXISTS (SELECT 1 FROM imports_importchunk p WHERE p.id = t.chunk_id)
            ORDER BY t.chunk_id
            LIMIT 5
        """,
    ),
    IntegrityCheck(
        name="custom_locations.agency_id",
        table="custom_locations",
        issue="missing_accounts_agency",
        count_sql="""
            SELECT COUNT(*) AS total
            FROM custom_locations t
            WHERE t.agency_id IS NULL
               OR NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
        """,
        sample_sql="""
            SELECT t.id::text AS sample_id
            FROM custom_locations t
            WHERE t.agency_id IS NULL
               OR NOT EXISTS (SELECT 1 FROM accounts_agency p WHERE p.id = t.agency_id)
            ORDER BY t.id
            LIMIT 5
        """,
    ),
)


def _s3_client() -> Any:
    endpoint = os.environ.get("STORAGE_ENDPOINT_URL") or "http://127.0.0.1:9000"
    access_key = os.environ.get("STORAGE_ACCESS_KEY") or os.environ.get("MINIO_ROOT_USER", "")
    secret_key = os.environ.get("STORAGE_SECRET_KEY") or os.environ.get("MINIO_ROOT_PASSWORD", "")
    if not access_key or not secret_key:
        raise RuntimeError("STORAGE_ACCESS_KEY/STORAGE_SECRET_KEY or MINIO_ROOT_* required")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=os.environ.get("STORAGE_REGION") or None,
        config=Config(signature_version="s3v4", connect_timeout=3, read_timeout=10),
    )


def _load_local_seed_defaults() -> None:
    appdata_root = Path(os.environ.get("IMMOAPP_APPDATA_ROOT", "C:/ProgramData/ImmoApp"))
    seed_path = appdata_root / "secrets" / "immoapp-dev-secrets.json"
    if not seed_path.exists():
        return
    try:
        payload = json.loads(seed_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str) and isinstance(value, str):
                os.environ.setdefault(key, value)


def _load_env() -> None:
    env_path = resolve_env_file(REPO_ROOT, REPO_ROOT / "server")
    if env_path.exists():
        load_dotenv(env_path)
    _load_local_seed_defaults()
    if (os.environ.get("POSTGRES_HOST") or "").strip().lower() == "db":
        os.environ["POSTGRES_HOST"] = "127.0.0.1"


def _local_db_default(name: str) -> str:
    defaults = {
        "POSTGRES_DB": "immoapp",
        "POSTGRES_ADMIN_USER": "immoapp",
        "POSTGRES_ADMIN_PASSWORD": "immoapp_admin_password",
    }
    host = (os.environ.get("POSTGRES_HOST") or "127.0.0.1").strip().lower()
    if host in {"localhost", "127.0.0.1", "::1"} and name in defaults:
        return defaults[name]
    raise RuntimeError(f"{name} is required")


def conninfo() -> str:
    _load_env()
    host = os.environ.get("POSTGRES_HOST") or "127.0.0.1"
    port = os.environ.get("POSTGRES_PORT") or "5432"
    dbname = os.environ.get("POSTGRES_DB") or _local_db_default("POSTGRES_DB")
    user = os.environ.get("POSTGRES_ADMIN_USER") or _local_db_default("POSTGRES_ADMIN_USER")
    password = os.environ.get("POSTGRES_ADMIN_PASSWORD") or _local_db_default(
        "POSTGRES_ADMIN_PASSWORD"
    )
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


def connect() -> psycopg.Connection[Any]:
    return psycopg.connect(conninfo(), row_factory=dict_row)


def validate_schema(conn: psycopg.Connection[Any]) -> list[str]:
    missing: list[str] = []
    with conn.cursor() as cur:
        for table, column in REQUIRED_COLUMNS:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = %s
                  AND column_name = %s
                """,
                (table, column),
            )
            if cur.fetchone() is None:
                missing.append(f"{table}.{column}")
    return missing


def run_checks(conn: psycopg.Connection[Any]) -> list[IntegrityResult]:
    results: list[IntegrityResult] = []
    with conn.cursor() as cur:
        for check in CHECKS:
            cur.execute(check.count_sql)
            count_row = cur.fetchone()
            if count_row is None:
                raise RuntimeError(f"Integrity check returned no count: {check.name}")
            count = int(count_row["total"])
            cur.execute(check.sample_sql)
            samples = [str(row["sample_id"]) for row in cur.fetchall()]
            results.append(
                IntegrityResult(
                    name=check.name,
                    table=check.table,
                    issue=check.issue,
                    count=count,
                    sample_ids=samples,
                )
            )
    return results


def missing_ready_storage_objects(conn: psycopg.Connection[Any]) -> list[dict[str, str]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT id::text AS id, bucket, object_key
            FROM storage_objects
            WHERE status = 'ready'
              AND deleted_at IS NULL
            ORDER BY created_at DESC, id
            """)
        rows = [dict(row) for row in cur.fetchall()]

    print(f"storage_object_check_total={len(rows)}")
    client = _s3_client()
    missing: list[dict[str, str]] = []
    for index, row in enumerate(rows, start=1):
        if index == 1 or index % 100 == 0 or index == len(rows):
            print(f"storage_object_check_progress={index}/{len(rows)}")
        bucket = str(row.get("bucket") or "").strip()
        key = str(row.get("object_key") or "").strip()
        if not bucket or not key:
            missing.append(
                {"id": str(row["id"]), "bucket": bucket, "object_key": key, "error": "blank"}
            )
            continue
        try:
            client.head_object(Bucket=bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            missing.append(
                {
                    "id": str(row["id"]),
                    "bucket": bucket,
                    "object_key": key,
                    "error": exc.__class__.__name__,
                }
            )
    return missing


def run_storage_object_checks(conn: psycopg.Connection[Any]) -> list[IntegrityResult]:
    missing = missing_ready_storage_objects(conn)
    return [
        IntegrityResult(
            name="storage_objects.ready_object_bytes",
            table="storage_objects",
            issue="missing_ready_object_bytes",
            count=len(missing),
            sample_ids=[
                f"{item['id']}:{item['bucket']}/{item['object_key']}" for item in missing[:5]
            ],
        )
    ]


def build_report(results: list[IntegrityResult], missing_schema: list[str]) -> dict[str, object]:
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "kind": "immoapp_release_backup_integrity_report",
        "schema_ok": not missing_schema,
        "missing_schema": missing_schema,
        "ok": not missing_schema and all(item.count == 0 for item in results),
        "checks": [asdict(item) for item in results],
    }


def print_table(results: list[IntegrityResult], missing_schema: list[str]) -> None:
    if missing_schema:
        print("release_backup_integrity=schema_failed")
        print("Missing required schema item(s):")
        for item in missing_schema:
            print(f"- {item}")
        return
    print(
        "release_backup_integrity=ok"
        if all(r.count == 0 for r in results)
        else "release_backup_integrity=failed"
    )
    print(f"{'check':46} {'count':>10} samples")
    print(f"{'-' * 46} {'-' * 10} {'-' * 20}")
    for result in results:
        samples = ", ".join(result.sample_ids)
        print(f"{result.name:46} {result.count:10d} {samples}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify release-critical DB integrity before producing a backup bundle."
    )
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)

    with connect() as conn:
        missing_schema = validate_schema(conn)
        results = [] if missing_schema else [*run_checks(conn), *run_storage_object_checks(conn)]

    report = build_report(results, missing_schema)
    print_table(results, missing_schema)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if bool(report["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
