from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import boto3
import psycopg
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from psycopg.rows import dict_row
from verify_release_bundle_manifest import ParsedManifest, verify_bundle_manifest

_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def _conninfo() -> str:
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = os.environ.get("POSTGRES_DB", "")
    user = os.environ.get("POSTGRES_ADMIN_USER", "")
    password = os.environ.get("POSTGRES_ADMIN_PASSWORD", "")
    if not dbname or not user or not password:
        raise RuntimeError("POSTGRES_DB / POSTGRES_ADMIN_USER / POSTGRES_ADMIN_PASSWORD required")
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


def _table_exists(conn: psycopg.Connection[Any], table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",))
        row = cur.fetchone()
        return bool(row[0]) if row is not None else False


def _count(conn: psycopg.Connection[Any], table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 - table is allowlisted by caller
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"Unable to count table: {table}")
        return int(row[0])


def _storage_rows(conn: psycopg.Connection[Any], limit: int) -> list[dict[str, object]]:
    if not _table_exists(conn, "storage_objects"):
        return []
    limit_clause = "" if limit <= 0 else "LIMIT %s"
    params: tuple[int, ...] = () if limit <= 0 else (limit,)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id::text AS id, bucket, object_key
            FROM storage_objects
            WHERE status = 'ready'
              AND deleted_at IS NULL
            ORDER BY created_at DESC
            {limit_clause}
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


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


def _restore_bucket_override() -> str:
    return str(os.environ.get("IMMOAPP_RESTORE_BUCKET_OVERRIDE") or "").strip()


def _manifest_path_for_object(parsed: ParsedManifest, object_key: str) -> str:
    key = object_key.strip()
    if not key:
        raise RuntimeError("Storage object has blank object_key")
    if "\\" in key or _DRIVE_PREFIX.match(key):
        raise RuntimeError(f"Unsafe storage object key: {object_key!r}")
    pure = PurePosixPath(key)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise RuntimeError(f"Unsafe storage object key: {object_key!r}")
    path = f"{parsed.mirror_root}/{pure.as_posix()}"
    if not path.startswith(f"minio/{parsed.source_bucket}/"):
        raise RuntimeError(f"Storage object key cannot map into bundle mirror: {object_key!r}")
    return path


def _sha256_stream(body: Any) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = body.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _verify_storage_objects(
    rows: list[dict[str, object]],
    parsed_manifest: ParsedManifest,
) -> tuple[str, int]:
    client = _s3_client()
    failures: list[str] = []
    override_bucket = _restore_bucket_override()
    for row in rows:
        row_id = str(row.get("id") or "").strip()
        db_bucket = str(row.get("bucket") or "").strip()
        bucket = override_bucket or db_bucket
        key = str(row.get("object_key") or "").strip()
        if not bucket:
            failures.append(f"{row_id}: blank bucket")
            continue
        if db_bucket != parsed_manifest.source_bucket:
            failures.append(
                f"{row_id}: db bucket {db_bucket!r} does not match bundle source bucket "
                f"{parsed_manifest.source_bucket!r}"
            )
            continue
        try:
            manifest_path = _manifest_path_for_object(parsed_manifest, key)
        except RuntimeError as exc:
            failures.append(f"{row_id}: {exc}")
            continue
        expected = parsed_manifest.files_by_path.get(manifest_path)
        if expected is None:
            failures.append(f"{row_id}: missing bundle manifest entry for {manifest_path}")
            continue
        try:
            head = client.head_object(Bucket=bucket, Key=key)
            content_length = int(head.get("ContentLength", -1))
            if content_length != expected.bytes:
                failures.append(
                    f"{row_id}: size mismatch for {bucket}/{key}: "
                    f"restored={content_length} manifest={expected.bytes}"
                )
                continue
            response = client.get_object(Bucket=bucket, Key=key)
            try:
                actual_sha = _sha256_stream(response["Body"])
            finally:
                close = getattr(response["Body"], "close", None)
                if callable(close):
                    close()
            if actual_sha != expected.sha256:
                failures.append(
                    f"{row_id}: SHA-256 mismatch for {bucket}/{key}: "
                    f"restored={actual_sha} manifest={expected.sha256}"
                )
        except (BotoCoreError, ClientError) as exc:
            db_context = f" db_bucket={db_bucket}" if override_bucket else ""
            failures.append(f"{row_id}: {bucket}/{key}:{db_context} {exc.__class__.__name__}")
    if failures:
        raise RuntimeError(
            "Restored storage objects failed manifest byte verification: " + "; ".join(failures)
        )
    return ("override" if override_bucket else "db_bucket", len(rows))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify release restore DB plus object data.")
    parser.add_argument("--bundle-path", type=Path, required=True)
    parser.add_argument("--require-storage-object", action="store_true")
    parser.add_argument("--storage-check-limit", type=int, default=0)
    args = parser.parse_args()

    parsed_manifest = verify_bundle_manifest(args.bundle_path)

    with psycopg.connect(_conninfo()) as conn:
        counts = {
            table: _count(conn, table)
            for table in (
                "clients",
                "listings",
                "offers",
                "demandes",
                "match_pairs",
                "contracts",
                "imports_importjob",
                "storage_objects",
                "offer_photos",
            )
        }
        rows = _storage_rows(conn, args.storage_check_limit)

    if args.require_storage_object and not rows:
        raise RuntimeError("Restore drill requires at least one active storage object.")
    storage_bucket_mode = "not_checked"
    hash_verified = 0
    if rows:
        storage_bucket_mode, hash_verified = _verify_storage_objects(rows, parsed_manifest)

    print("release_restore_verification=ok")
    for key, value in counts.items():
        print(f"{key}={value}")
    print(f"storage_objects_checked={len(rows)}")
    print(f"storage_objects_hash_verified={hash_verified}")
    print(f"storage_object_bucket_mode={storage_bucket_mode}")
    if _restore_bucket_override():
        print(f"restore_bucket_override={_restore_bucket_override()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"release_restore_verification=failed: {exc}", file=sys.stderr)
        raise
