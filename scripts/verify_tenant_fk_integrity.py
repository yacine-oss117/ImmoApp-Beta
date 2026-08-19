from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from core.env_files import resolve_env_file
from server.pg.tenant_fk_hardening import audit_tenant_integrity, report_summary

_ENV_LOADED = False


def _load_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    repo_root = Path(__file__).resolve().parents[1]
    base_dir = repo_root / "server"
    env_path = resolve_env_file(repo_root, base_dir)
    if env_path.exists():
        load_dotenv(env_path)
    _load_db_credentials_from_openbao()
    _ENV_LOADED = True


def _load_db_credentials_from_openbao() -> None:
    required = ("POSTGRES_DB", "POSTGRES_ADMIN_USER", "POSTGRES_ADMIN_PASSWORD")
    if all(os.environ.get(name) for name in required):
        return
    try:
        from server.secret_store.loader import load_secrets
    except Exception:
        return

    previous_allowlist = os.environ.get("IMMOAPP_SECRETS_ALLOWLIST")
    if not previous_allowlist:
        os.environ["IMMOAPP_SECRETS_ALLOWLIST"] = "ALE_,DJANGO_,IMMOAPP_,POSTGRES_"
    try:
        load_secrets()
    except Exception:
        return
    finally:
        if previous_allowlist is None:
            os.environ.pop("IMMOAPP_SECRETS_ALLOWLIST", None)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _local_db_default(name: str) -> str:
    defaults = {
        "POSTGRES_DB": "immoapp",
        "POSTGRES_ADMIN_USER": "immoapp",
        "POSTGRES_ADMIN_PASSWORD": "immoapp_admin_password",
    }
    host = (os.environ.get("POSTGRES_HOST") or "localhost").strip().lower()
    if host in {"localhost", "127.0.0.1"} and name in defaults:
        return defaults[name]
    raise RuntimeError(f"{name} is required")


def _admin_conn() -> psycopg.Connection:
    _load_env()
    return psycopg.connect(
        (
            f"host={os.environ.get('POSTGRES_HOST', 'localhost')} "
            f"port={os.environ.get('POSTGRES_PORT', '5432')} "
            f"dbname={os.environ.get('POSTGRES_DB') or _local_db_default('POSTGRES_DB')} "
            f"user={os.environ.get('POSTGRES_ADMIN_USER') or _local_db_default('POSTGRES_ADMIN_USER')} "
            f"password={os.environ.get('POSTGRES_ADMIN_PASSWORD') or _local_db_default('POSTGRES_ADMIN_PASSWORD')}"
        ),
        row_factory=dict_row,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("report", "fail-on-issue", "post-migration-verify"),
        default="report",
    )
    args = parser.parse_args(argv)

    conn = _admin_conn()
    try:
        report = audit_tenant_integrity(conn)
    finally:
        conn.close()

    print(report_summary(report))
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))

    if args.mode == "report":
        return 0
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
