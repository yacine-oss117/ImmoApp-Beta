from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psycopg
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.env_files import resolve_env_file  # noqa: E402
from scripts.repo_layout import (  # noqa: E402
    ALEMBIC_CONFIG,
    ALEMBIC_ROOT,
    COMPOSE_APP_YML,
    COMPOSE_WINDOWS_YML,
    COMPOSE_YML,
)

REQUIRED_TABLES = (
    "api_idempotency_records",
    "actions",
    "agency_settings",
    "audit_logs",
    "auth_security_events",
    "clients",
    "contract_articles",
    "contracts",
    "custom_locations",
    "demande_locations",
    "demandes",
    "listings",
    "locations",
    "match_artifact_health_samples",
    "match_artifact_timeout_counters",
    "match_candidates",
    "match_counts_cache",
    "match_pairs",
    "match_rebuild_state",
    "surface_cache_generation",
    "meta",
    "notification_reads",
    "notifications",
    "offer_locations",
    "offer_photos",
    "offers",
    "property_types",
    "record_acl",
    "storage_events",
    "storage_objects",
    "storage_usage",
    "task_failures",
    "tenant_work_lease",
    "visits",
    "wa_templates",
    "wilayas",
)

TENANT_TABLES = (
    "clients",
    "listings",
    "visits",
    "contracts",
    "demandes",
    "offers",
    "demande_locations",
    "offer_locations",
    "match_counts_cache",
    "match_candidates",
    "match_pairs",
    "match_rebuild_state",
    "surface_cache_generation",
    "custom_locations",
    "contract_articles",
    "wa_templates",
    "audit_logs",
    "task_failures",
    "notifications",
    "notification_reads",
    "auth_security_events",
    "storage_objects",
    "offer_photos",
    "record_acl",
    "storage_usage",
    "storage_events",
    "agency_settings",
)


def _parse_args() -> argparse.Namespace:
    default_mode = (os.environ.get("IMMOAPP_FRESH_CHAIN_MODE", "auto") or "auto").strip().lower()
    if default_mode not in {"auto", "host", "docker"}:
        default_mode = "auto"
    default_compose_files = (os.environ.get("IMMOAPP_FRESH_CHAIN_COMPOSE_FILES", "") or "").strip()
    if not default_compose_files:
        compose_files = [COMPOSE_YML]
        if os.name == "nt" and COMPOSE_WINDOWS_YML.exists():
            compose_files.append(COMPOSE_WINDOWS_YML)
        compose_files.append(COMPOSE_APP_YML)
        default_compose_files = ",".join(str(path) for path in compose_files)
    parser = argparse.ArgumentParser(
        description="Validate Alembic fresh-chain bootstrap on a temporary database."
    )
    parser.add_argument(
        "--python", default=sys.executable, help="Python interpreter to run Alembic."
    )
    parser.add_argument(
        "--keep-db", action="store_true", help="Keep temp DB for manual inspection."
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "host", "docker"),
        default=default_mode,
        help=(
            "Execution mode: host (run locally), docker (exec inside compose service), "
            "auto (docker when POSTGRES_HOST is a docker alias)."
        ),
    )
    parser.add_argument(
        "--docker-service",
        default=(os.environ.get("IMMOAPP_FRESH_CHAIN_DOCKER_SERVICE", "web") or "web").strip(),
        help="Compose service to exec into when --mode docker/auto delegates.",
    )
    parser.add_argument(
        "--docker-compose-files",
        default=default_compose_files,
        help="Comma/semicolon-separated compose files used for docker compose commands.",
    )
    parser.add_argument(
        "--docker-env-file",
        default=(os.environ.get("IMMOAPP_FRESH_CHAIN_ENV_FILE", "") or "").strip(),
        help="Optional env file passed to docker compose.",
    )
    return parser.parse_args()


def _load_env() -> None:
    repo_root = REPO_ROOT
    base_dir = repo_root / "server"
    env_path = resolve_env_file(repo_root, base_dir)
    if env_path.exists():
        load_dotenv(env_path)
    _load_db_credentials_from_openbao()


def _load_db_credentials_from_openbao() -> None:
    required = ("POSTGRES_ADMIN_USER", "POSTGRES_ADMIN_PASSWORD")
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


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _admin_conninfo(*, dbname: str) -> str:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = _require("POSTGRES_ADMIN_USER")
    password = _require("POSTGRES_ADMIN_PASSWORD")
    connect_timeout = os.environ.get("POSTGRES_CONNECT_TIMEOUT", "8")
    return (
        f"host={host} port={port} dbname={dbname} user={user} password={password} "
        f"connect_timeout={connect_timeout}"
    )


def _is_truthy(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _should_delegate_to_docker(args: argparse.Namespace) -> bool:
    if args.mode == "host":
        return False
    if args.mode == "docker":
        return True
    if _is_truthy(os.environ.get("IMMOAPP_FRESH_CHAIN_FORCE_DOCKER")):
        return True
    host = (os.environ.get("POSTGRES_HOST", "localhost") or "").strip().lower()
    return host in {"db", "postgres", "postgresql"}


def _compose_files_from_args(raw: str) -> list[str]:
    files: list[str] = []
    for part in raw.replace(";", ",").split(","):
        candidate = part.strip()
        if not candidate:
            continue
        path = Path(candidate)
        if not path.is_absolute():
            path = REPO_ROOT / candidate
        if path.exists():
            files.append(str(path))
    return files


def _docker_compose_prefix(args: argparse.Namespace) -> list[str]:
    prefix: list[str] = ["docker", "compose", "--project-directory", str(REPO_ROOT)]
    if args.docker_env_file:
        env_path = Path(args.docker_env_file)
        if not env_path.is_absolute():
            env_path = REPO_ROOT / args.docker_env_file
        prefix += ["--env-file", str(env_path)]
    files = _compose_files_from_args(args.docker_compose_files)
    for compose_file in files:
        prefix += ["-f", compose_file]
    return prefix


def _assert_docker_service_running(*, prefix: list[str], service: str) -> None:
    proc = subprocess.run(
        prefix + ["ps", "--status", "running", "--services"],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "Unable to inspect docker compose services.\n"
            f"cmd: {' '.join(prefix + ['ps', '--status', 'running', '--services'])}\n"
            f"stdout:\n{proc.stdout[-2000:]}\n\nstderr:\n{proc.stderr[-2000:]}"
        )
    running = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    if service not in running:
        raise RuntimeError(
            f"Compose service '{service}' is not running. "
            f"Start it and retry (example: {' '.join(prefix + ['up', '-d', service])})."
        )


def _service_container_id(*, prefix: list[str], service: str) -> str:
    proc = subprocess.run(
        prefix + ["ps", "-q", service],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Unable to resolve container id for compose service '{service}'.\n"
            f"stdout:\n{proc.stdout[-2000:]}\n\nstderr:\n{proc.stderr[-2000:]}"
        )
    container_id = (proc.stdout or "").strip()
    if not container_id:
        raise RuntimeError(f"Compose service '{service}' has no running container id.")
    return container_id


def _copy_to_container(*, container_id: str, source: Path, target: str) -> None:
    copy = subprocess.run(
        ["docker", "cp", str(source), f"{container_id}:{target}"],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if copy.returncode != 0:
        raise RuntimeError(
            f"Failed to stage '{source}' into container '{container_id}:{target}'.\n"
            f"stdout:\n{copy.stdout[-2000:]}\n\nstderr:\n{copy.stderr[-2000:]}"
        )


def _stage_script_in_container(*, prefix: list[str], service: str) -> str:
    mkdir = subprocess.run(
        prefix + ["exec", "-T", service, "sh", "-lc", "mkdir -p /app/scripts /app/server/alembic"],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if mkdir.returncode != 0:
        raise RuntimeError(
            f"Unable to prepare /app/scripts inside compose service '{service}'.\n"
            f"stdout:\n{mkdir.stdout[-2000:]}\n\nstderr:\n{mkdir.stderr[-2000:]}"
        )
    container_id = _service_container_id(prefix=prefix, service=service)
    script_target = "/app/scripts/verify_alembic_fresh_chain.py"
    _copy_to_container(
        container_id=container_id,
        source=Path(__file__).resolve(),
        target=script_target,
    )
    _copy_to_container(
        container_id=container_id,
        source=ALEMBIC_ROOT,
        target="/app/server",
    )
    _copy_to_container(
        container_id=container_id,
        source=ALEMBIC_CONFIG,
        target="/app/server/alembic.ini",
    )
    return script_target


def _run_in_docker(args: argparse.Namespace) -> int:
    if not shutil.which("docker"):
        raise RuntimeError(
            "Docker CLI not found on PATH; cannot run fresh-chain verification in docker mode."
        )

    prefix = _docker_compose_prefix(args)
    _assert_docker_service_running(prefix=prefix, service=args.docker_service)
    staged_script = _stage_script_in_container(prefix=prefix, service=args.docker_service)

    cmd = prefix + [
        "exec",
        "-T",
    ]
    passthrough = (
        "POSTGRES_ADMIN_DB",
        "POSTGRES_ADMIN_USER",
        "POSTGRES_ADMIN_PASSWORD",
        "POSTGRES_CONNECT_TIMEOUT",
        "IMMOAPP_SECRETS_BACKEND",
        "IMMOAPP_SECRETS_PATH",
        "IMMOAPP_SECRETS_ALLOWLIST",
        "BAO_ADDR",
        "BAO_TOKEN",
        "BAO_TOKEN_FILE",
        "BAO_APPROLE_FILE",
        "BAO_ROLE_ID",
        "BAO_SECRET_ID",
    )
    for name in passthrough:
        value = os.environ.get(name)
        if value:
            cmd += ["-e", f"{name}={value}"]

    cmd += [
        args.docker_service,
        "python",
        staged_script,
        "--mode",
        "host",
    ]
    if args.keep_db:
        cmd.append("--keep-db")

    env = dict(os.environ)
    env["IMMOAPP_FRESH_CHAIN_DOCKER_DELEGATED"] = "1"
    print(
        "[verify_alembic_fresh_chain] delegating to docker compose service "
        f"'{args.docker_service}'"
    )
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=False,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Docker delegated fresh-chain verification failed with exit code {proc.returncode}."
        )
    return proc.returncode


def _run_alembic_upgrade(*, python_bin: str, dbname: str) -> None:
    env = dict(os.environ)
    env["POSTGRES_DB"] = dbname
    env["POSTGRES_USER"] = _require("POSTGRES_ADMIN_USER")
    env["POSTGRES_PASSWORD"] = _require("POSTGRES_ADMIN_PASSWORD")
    alembic_exe = (os.environ.get("IMMOAPP_ALEMBIC_EXE", "") or "").strip()
    config_path = "server/alembic.ini"
    if alembic_exe:
        cmd = [alembic_exe, "-c", config_path, "upgrade", "head"]
    else:
        inline = (
            "from alembic.config import Config\n"
            "from alembic import command\n"
            "cfg = Config('server/alembic.ini')\n"
            "command.upgrade(cfg, 'head')\n"
        )
        cmd = [python_bin, "-c", inline]
    timeout_sec = int(os.environ.get("IMMOAPP_ALEMBIC_UPGRADE_TIMEOUT_SEC", "240"))
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Alembic upgrade command timed out after {timeout_sec}s: {' '.join(cmd)}"
        ) from exc
    if proc.returncode != 0:
        raise RuntimeError(
            "Alembic upgrade failed on fresh DB.\n"
            f"stdout:\n{proc.stdout[-2000:]}\n\nstderr:\n{proc.stderr[-2000:]}"
        )


def _create_temp_db(*, dbname: str) -> None:
    maintenance_db = os.environ.get("POSTGRES_ADMIN_DB", "postgres")
    with psycopg.connect(_admin_conninfo(dbname=maintenance_db), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
            if cur.fetchone():
                cur.execute(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = %s AND pid <> pg_backend_pid()
                    """,
                    (dbname,),
                )
                cur.execute(f'DROP DATABASE "{dbname}"')
            cur.execute(f'CREATE DATABASE "{dbname}"')


def _drop_temp_db(*, dbname: str) -> None:
    maintenance_db = os.environ.get("POSTGRES_ADMIN_DB", "postgres")
    with psycopg.connect(_admin_conninfo(dbname=maintenance_db), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (dbname,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{dbname}"')


def _verify_fresh_db(*, dbname: str) -> None:
    missing_tables: list[str] = []
    rls_issues: list[str] = []

    with psycopg.connect(_admin_conninfo(dbname=dbname), autocommit=True) as conn:
        with conn.cursor() as cur:
            for table in REQUIRED_TABLES:
                cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
                if not cur.fetchone()[0]:
                    missing_tables.append(table)

            cur.execute("SELECT to_regprocedure('immoapp_norm_text(text)')")
            if not cur.fetchone()[0]:
                raise RuntimeError("Missing function immoapp_norm_text(text)")
            cur.execute("SELECT to_regprocedure('immoapp_hash_trigrams(text)')")
            if not cur.fetchone()[0]:
                raise RuntimeError("Missing function immoapp_hash_trigrams(text)")

            for table in TENANT_TABLES:
                cur.execute(
                    """
                    SELECT c.relrowsecurity, c.relforcerowsecurity
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relname = %s
                    """,
                    (table,),
                )
                row = cur.fetchone()
                if not row:
                    rls_issues.append(f"{table}: table missing")
                    continue
                relrowsecurity, relforcerowsecurity = row
                if not relrowsecurity:
                    rls_issues.append(f"{table}: RLS disabled")
                if not relforcerowsecurity:
                    rls_issues.append(f"{table}: FORCE RLS disabled")

                cur.execute(
                    """
                    SELECT 1
                    FROM pg_policy p
                    JOIN pg_class c ON c.oid = p.polrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relname = %s
                      AND p.polname = %s
                    """,
                    (table, f"policy_{table}_isolation"),
                )
                if not cur.fetchone():
                    rls_issues.append(f"{table}: missing policy policy_{table}_isolation")

    if missing_tables:
        raise RuntimeError(f"Fresh-chain missing required tables: {missing_tables}")
    if rls_issues:
        raise RuntimeError("Fresh-chain RLS verification issues:\n" + "\n".join(rls_issues))


def main() -> int:
    args = _parse_args()
    _load_env()
    if _should_delegate_to_docker(args):
        return _run_in_docker(args)

    suffix = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    temp_db = f"immoapp_fresh_chain_{suffix}"
    print(f"[verify_alembic_fresh_chain] creating temp db: {temp_db}")
    _create_temp_db(dbname=temp_db)
    try:
        _run_alembic_upgrade(python_bin=args.python, dbname=temp_db)
        _verify_fresh_db(dbname=temp_db)
    finally:
        if args.keep_db:
            print(f"[verify_alembic_fresh_chain] keeping temp db: {temp_db}")
        else:
            _drop_temp_db(dbname=temp_db)
            print(f"[verify_alembic_fresh_chain] dropped temp db: {temp_db}")

    print("[verify_alembic_fresh_chain] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
