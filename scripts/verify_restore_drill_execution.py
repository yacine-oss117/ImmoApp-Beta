from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql

from repo_layout import COMPOSE_WINDOWS_YML, COMPOSE_YML

_RESTORE_DRILL_EXCLUDE_TABLE_DATA = ("public.auth_security_events",)


def _compose_files() -> list[str]:
    raw = os.environ.get("IMMOAPP_COMPOSE_FILES", "").strip()
    if raw:
        return [p.strip() for p in raw.split(";") if p.strip()]
    files = [str(COMPOSE_YML)]
    if os.name == "nt" and COMPOSE_WINDOWS_YML.exists():
        files.append(str(COMPOSE_WINDOWS_YML))
    return files


def _compose_base_cmd() -> list[str]:
    cmd = ["docker", "compose", "--project-directory", str(Path(__file__).resolve().parents[1])]
    for compose_file in _compose_files():
        cmd.extend(["-f", compose_file])
    return cmd


def _require_env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name)
    if not value and default is not None:
        value = default
    if not value:
        raise SystemExit(f"verify_restore_drill_execution: missing required env var {name}")
    return value


def _resolve_pg_tool(name: str) -> str | None:
    override = os.environ.get(f"IMMOAPP_{name.upper()}_PATH")
    if override:
        override_path = Path(override)
        if override_path.exists():
            return str(override_path)

    found = shutil.which(name)
    if found:
        return found

    if os.name == "nt":
        roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
        for root in [r for r in roots if r]:
            pg_root = Path(root) / "PostgreSQL"
            if not pg_root.exists():
                continue
            # Prefer newest installed PostgreSQL client.
            for bin_dir in sorted(pg_root.glob("*/bin"), reverse=True):
                exe = bin_dir / f"{name}.exe"
                if exe.exists():
                    return str(exe)
    return None


def _ensure_pg_tools() -> tuple[str, str] | None:
    pg_dump = _resolve_pg_tool("pg_dump")
    pg_restore = _resolve_pg_tool("pg_restore")
    if not pg_dump or not pg_restore:
        return None
    return pg_dump, pg_restore


def _run(cmd: list[str], *, env: dict[str, str]) -> None:
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise SystemExit(
            "verify_restore_drill_execution failed:\n"
            + "CMD: "
            + " ".join(cmd)
            + "\nSTDOUT:\n"
            + result.stdout
            + "\nSTDERR:\n"
            + result.stderr
        )


def _run_binary(
    cmd: list[str],
    *,
    env: dict[str, str],
    stdin_bytes: bytes | None = None,
) -> bytes:
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        env=env,
        input=stdin_bytes,
    )
    if result.returncode != 0:
        raise SystemExit(
            "verify_restore_drill_execution failed:\n"
            + "CMD: "
            + " ".join(cmd)
            + "\nSTDOUT(bytes):\n"
            + result.stdout.decode(errors="replace")
            + "\nSTDERR(bytes):\n"
            + result.stderr.decode(errors="replace")
        )
    return result.stdout


def _dump_via_docker(*, user: str, db_name: str, password: str, out_file: Path) -> None:
    env = os.environ.copy()
    cmd = _compose_base_cmd() + [
        "exec",
        "-T",
        "-e",
        f"PGPASSWORD={password}",
        "db",
        "pg_dump",
        "-U",
        user,
        "-d",
        db_name,
        "-Fc",
    ]
    for table_name in _RESTORE_DRILL_EXCLUDE_TABLE_DATA:
        cmd.append(f"--exclude-table-data={table_name}")
    data = _run_binary(cmd, env=env)
    out_file.write_bytes(data)


def _restore_via_docker(
    *,
    user: str,
    db_name: str,
    password: str,
    backup_file: Path,
) -> None:
    env = os.environ.copy()
    cmd = _compose_base_cmd() + [
        "exec",
        "-T",
        "-e",
        f"PGPASSWORD={password}",
        "db",
        "pg_restore",
        "-U",
        user,
        "-d",
        db_name,
        "--clean",
        "--if-exists",
    ]
    _run_binary(cmd, env=env, stdin_bytes=backup_file.read_bytes())


def _admin_conn_params() -> dict[str, str | int]:
    return {
        "host": _require_env("POSTGRES_HOST", "127.0.0.1"),
        "port": int(_require_env("POSTGRES_PORT", "5432")),
        "user": _require_env("POSTGRES_ADMIN_USER", "immoapp"),
        "password": _require_env("POSTGRES_ADMIN_PASSWORD", "immoapp_admin_password"),
        "dbname": "postgres",
    }


def _drop_database_if_exists(db_name: str) -> None:
    params = _admin_conn_params()
    with psycopg.connect(**params, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s
                  AND pid <> pg_backend_pid()
                """,
                (db_name,),
            )
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name)))


def _create_database(db_name: str) -> None:
    params = _admin_conn_params()
    owner = _require_env("POSTGRES_ADMIN_USER", "immoapp")
    with psycopg.connect(**params, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(db_name),
                    sql.Identifier(owner),
                )
            )


def _sanitize_auth_event_fk_orphans(db_name: str) -> None:
    params = {
        "host": _require_env("POSTGRES_HOST", "127.0.0.1"),
        "port": int(_require_env("POSTGRES_PORT", "5432")),
        "user": _require_env("POSTGRES_ADMIN_USER", "immoapp"),
        "password": _require_env("POSTGRES_ADMIN_PASSWORD", "immoapp_admin_password"),
        "dbname": db_name,
    }
    with psycopg.connect(**params) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.auth_security_events')")
            if cur.fetchone()[0] is None:
                return

            cur.execute("""
                UPDATE auth_security_events ase
                SET agency_id = NULL
                WHERE ase.agency_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM accounts_agency a
                      WHERE a.id = ase.agency_id
                  )
                """)
            agency_fixed = max(cur.rowcount, 0)

            cur.execute("""
                UPDATE auth_security_events ase
                SET user_id = NULL
                WHERE ase.user_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM accounts_user u
                      WHERE u.id = ase.user_id
                  )
                """)
            user_fixed = max(cur.rowcount, 0)

        conn.commit()

    if agency_fixed or user_fixed:
        print(
            "verify_restore_drill_execution: sanitized auth event FK orphans "
            f"(agency={agency_fixed}, user={user_fixed})"
        )


def _verify_restored_db(
    db_name: str,
    *,
    app_user: str,
    app_password: str,
) -> None:
    params = {
        "host": _require_env("POSTGRES_HOST", "127.0.0.1"),
        "port": int(_require_env("POSTGRES_PORT", "5432")),
        "user": _require_env("POSTGRES_ADMIN_USER", "immoapp"),
        "password": _require_env("POSTGRES_ADMIN_PASSWORD", "immoapp_admin_password"),
        "dbname": db_name,
    }
    with psycopg.connect(**params) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.alembic_version')")
            row = cur.fetchone()
            if not row or row[0] is None:
                raise SystemExit(
                    "verify_restore_drill_execution: restored DB missing alembic_version table"
                )
            cur.execute("SELECT COUNT(*) FROM alembic_version")
            count = int(cur.fetchone()[0])
            if count <= 0:
                raise SystemExit(
                    "verify_restore_drill_execution: alembic_version has no rows after restore"
                )

    app_params = {
        "host": _require_env("POSTGRES_HOST", "127.0.0.1"),
        "port": int(_require_env("POSTGRES_PORT", "5432")),
        "user": app_user,
        "password": app_password,
        "dbname": db_name,
    }
    with psycopg.connect(**app_params) as conn:
        with conn.cursor() as cur:
            _verify_tenant_smoke(cur)


def _verify_tenant_smoke(cur: psycopg.Cursor) -> None:
    suffix = uuid4().hex[:8]
    code_a = f"RDA{suffix}"
    code_b = f"RDB{suffix}"
    marker = f"RESTORE_SMOKE_{suffix}"

    cur.execute(
        """
        INSERT INTO accounts_agency (
            legal_name, display_name, agency_code,
            kbis_number, phone_number, email,
            address_line1, address_line2, city, postal_code, country,
            phone_number_enc, address_line1_enc, address_line2_enc, city_enc,
            is_active, max_users, max_managers, max_agents_per_manager,
            created_at, updated_at
        )
        VALUES (
            %s, %s, %s,
            '', '', '',
            '', '', '', '', '',
            '', '', '', '',
            true, 3, 1, 2,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        RETURNING id
        """,
        (f"Restore Drill A {suffix}", f"Restore Drill A {suffix}", code_a),
    )
    agency_a = int(cur.fetchone()[0])

    cur.execute(
        """
        INSERT INTO accounts_agency (
            legal_name, display_name, agency_code,
            kbis_number, phone_number, email,
            address_line1, address_line2, city, postal_code, country,
            phone_number_enc, address_line1_enc, address_line2_enc, city_enc,
            is_active, max_users, max_managers, max_agents_per_manager,
            created_at, updated_at
        )
        VALUES (
            %s, %s, %s,
            '', '', '',
            '', '', '', '', '',
            '', '', '', '',
            true, 3, 1, 2,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        RETURNING id
        """,
        (f"Restore Drill B {suffix}", f"Restore Drill B {suffix}", code_b),
    )
    agency_b = int(cur.fetchone()[0])

    cur.execute("SELECT set_config('app.is_superuser', 'false', false)")
    cur.execute("SELECT set_config('app.current_agency_id', %s, false)", (str(agency_a),))
    cur.execute(
        """
        INSERT INTO clients (family_name, phone, created_at, updated_at)
        VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (marker, "213777000111"),
    )
    client_id = int(cur.fetchone()[0])

    cur.execute("SELECT COUNT(*) FROM clients WHERE id = %s", (client_id,))
    visible_in_a = int(cur.fetchone()[0])
    if visible_in_a != 1:
        raise SystemExit(
            "verify_restore_drill_execution: tenant smoke write/read failed for agency A"
        )

    cur.execute("SELECT set_config('app.current_agency_id', %s, false)", (str(agency_b),))
    cur.execute("SELECT COUNT(*) FROM clients WHERE id = %s", (client_id,))
    visible_in_b = int(cur.fetchone()[0])
    if visible_in_b != 0:
        raise SystemExit(
            "verify_restore_drill_execution: RLS isolation failed in restored DB smoke"
        )


def main() -> None:
    run_drill = os.environ.get("IMMOAPP_RUN_RESTORE_DRILL", "0").strip() == "1"
    if not run_drill:
        print("verify_restore_drill_execution: skipped (IMMOAPP_RUN_RESTORE_DRILL != 1)")
        return

    pg_tools = _ensure_pg_tools()

    host = _require_env("POSTGRES_HOST", "127.0.0.1")
    port = _require_env("POSTGRES_PORT", "5432")
    db_name = _require_env("POSTGRES_DB", "immoapp")
    app_user = _require_env("POSTGRES_USER", "immoapp_app")
    app_password = _require_env("POSTGRES_PASSWORD", "immoapp_app_password")
    admin_user = _require_env("POSTGRES_ADMIN_USER", "immoapp")
    admin_password = _require_env("POSTGRES_ADMIN_PASSWORD", "immoapp_admin_password")

    restore_db = f"{db_name}_restore_drill_{int(time.time())}"

    with tempfile.TemporaryDirectory(prefix="immoapp_restore_") as tmp:
        backup = Path(tmp) / "backup.dump"
        _sanitize_auth_event_fk_orphans(db_name)

        if pg_tools is None:
            _dump_via_docker(
                user=admin_user,
                db_name=db_name,
                password=admin_password,
                out_file=backup,
            )
        else:
            pg_dump, pg_restore = pg_tools
            env_user = os.environ.copy()
            env_user["PGPASSWORD"] = admin_password
            _run(
                [
                    pg_dump,
                    "-h",
                    host,
                    "-p",
                    port,
                    "-U",
                    admin_user,
                    "-d",
                    db_name,
                    "-Fc",
                    *[f"--exclude-table-data={name}" for name in _RESTORE_DRILL_EXCLUDE_TABLE_DATA],
                    "-f",
                    str(backup),
                ],
                env=env_user,
            )

        try:
            _drop_database_if_exists(restore_db)
            _create_database(restore_db)

            if pg_tools is None:
                _restore_via_docker(
                    user=admin_user,
                    db_name=restore_db,
                    password=admin_password,
                    backup_file=backup,
                )
            else:
                _, pg_restore = pg_tools
                env_admin = os.environ.copy()
                env_admin["PGPASSWORD"] = admin_password
                _run(
                    [
                        pg_restore,
                        "-h",
                        host,
                        "-p",
                        port,
                        "-U",
                        admin_user,
                        "-d",
                        restore_db,
                        "--clean",
                        "--if-exists",
                        str(backup),
                    ],
                    env=env_admin,
                )

            _verify_restored_db(
                restore_db,
                app_user=app_user,
                app_password=app_password,
            )
        finally:
            _drop_database_if_exists(restore_db)

    print("verify_restore_drill_execution: OK")


if __name__ == "__main__":
    main()
