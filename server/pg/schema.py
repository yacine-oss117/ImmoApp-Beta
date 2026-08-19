"""Postgres schema migration entrypoint (Alembic-only)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg

from core.data.sql_identifiers import validate_identifier

from .uow import admin_transaction

_ENSURE_SCHEMA_LOCK_ID = 924_337_119
_ALEMBIC_HEAD = "head"
_ALEMBIC_SCHEMA_ENV = "IMMOAPP_ALEMBIC_SCHEMA"
_SUPPORTED_SCHEMA_MODE = "alembic"
_PUBLIC_BOOTSTRAP_TABLES = (
    "accounts_agency",
    "accounts_user",
    "django_migrations",
)
logger = logging.getLogger(__name__)


def _acquire_schema_lock(session) -> None:
    session.execute("SELECT pg_advisory_lock(%s)", (_ENSURE_SCHEMA_LOCK_ID,))


def _release_schema_lock(session) -> None:
    try:
        session.execute("SELECT pg_advisory_unlock(%s)", (_ENSURE_SCHEMA_LOCK_ID,))
    except psycopg.errors.InFailedSqlTransaction:
        # Attempt to clear aborted transaction before unlocking.
        logger.warning(
            "Advisory unlock hit failed transaction state; attempting rollback before retry."
        )
        try:
            session.rollback()
            session.execute("SELECT pg_advisory_unlock(%s)", (_ENSURE_SCHEMA_LOCK_ID,))
        except Exception:
            logger.warning(
                "Advisory unlock retry failed after rollback; lock will release on session close.",
                exc_info=True,
            )
    except Exception:
        # If we cannot unlock cleanly, connection close will release it.
        logger.warning(
            "Advisory unlock failed; lock will release on session close.",
            exc_info=True,
        )


def _schema_mode() -> str:
    return os.environ.get("IMMOAPP_SCHEMA_MODE", _SUPPORTED_SCHEMA_MODE).strip().lower()


def _assert_schema_mode_allowed(mode: str) -> None:
    if mode != _SUPPORTED_SCHEMA_MODE:
        raise RuntimeError(
            "Unsupported IMMOAPP_SCHEMA_MODE. Alembic-only is enforced; set IMMOAPP_SCHEMA_MODE=alembic."
        )


def _alembic_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "alembic.ini"


@contextmanager
def _alembic_schema_env(schema: str) -> Iterator[None]:
    previous = os.environ.get(_ALEMBIC_SCHEMA_ENV)
    os.environ[_ALEMBIC_SCHEMA_ENV] = schema
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(_ALEMBIC_SCHEMA_ENV, None)
        else:
            os.environ[_ALEMBIC_SCHEMA_ENV] = previous


def _run_alembic_upgrade_head(*, schema: str) -> None:
    from alembic import command
    from alembic.config import Config

    with _alembic_admin_env():
        with _alembic_schema_env(schema):
            cfg = Config(str(_alembic_config_path()))
            command.upgrade(cfg, _ALEMBIC_HEAD)


def _missing_public_bootstrap_elements() -> tuple[list[str], list[str]]:
    missing_tables: list[str] = []

    with admin_transaction(schema="public") as session:
        for table in _PUBLIC_BOOTSTRAP_TABLES:
            row = session.execute("SELECT to_regclass(%s) AS rel", (f"public.{table}",)).fetchone()
            if not row or not row.get("rel"):
                missing_tables.append(table)

    return missing_tables, []


def _public_schema_bootstrap_required() -> bool:
    missing_tables, missing_columns = _missing_public_bootstrap_elements()
    return bool(missing_tables or missing_columns)


def _run_django_migrate_bootstrap() -> None:
    manage_py = Path(__file__).resolve().parents[1] / "manage.py"
    repo_root = Path(__file__).resolve().parents[2]
    cmd = [sys.executable, str(manage_py), "migrate", "--noinput"]
    with _alembic_admin_env():
        env = os.environ.copy()
        env.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
        # Guard against any startup schema hooks; schema prep is explicit here.
        env["IMMOAPP_SKIP_SCHEMA_INIT"] = "1"
        # Keep admin credentials selected in _alembic_admin_env for this bootstrap
        # subprocess. manage.py loads secrets eagerly, so disable overwrite and
        # strict "must-come-from-openbao" enforcement for this controlled path.
        env["IMMOAPP_SECRETS_OVERWRITE"] = "0"
        env["IMMOAPP_ALLOW_ENV_SECRETS"] = "1"
        env["IMMOAPP_SECRETS_REQUIRED"] = "0"
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "").strip()[-1200:]
        stdout_tail = (proc.stdout or "").strip()[-1200:]
        raise RuntimeError(
            "Django migration bootstrap failed before Alembic upgrade.\n"
            f"stdout:\n{stdout_tail}\n\nstderr:\n{stderr_tail}"
        )


def _bootstrap_public_schema_if_needed() -> None:
    if not _public_schema_bootstrap_required():
        return
    _run_django_migrate_bootstrap()
    if _public_schema_bootstrap_required():
        missing_tables, missing_columns = _missing_public_bootstrap_elements()
        raise RuntimeError(
            "Database bootstrap completed but required schema elements are still missing: "
            + ", ".join([*missing_tables, *missing_columns])
        )


def _ensure_post_alembic_primitives(*, schema: str | None = None) -> None:
    """
    Enforce critical DB primitives that older DBs may miss even when alembic
    metadata is present.

    We keep this idempotent and cheap so `ensure_schema()` remains safe.
    """
    from .schema_seed import seed_reference_data

    with admin_transaction(schema=schema) as session:
        if not hasattr(session, "execute"):
            # Unit tests may stub admin_transaction with sentinel objects.
            return
        _acquire_schema_lock(session)
        try:
            seed_reference_data(session)
        finally:
            _release_schema_lock(session)


@contextmanager
def _alembic_admin_env():
    prev_user = os.environ.get("POSTGRES_USER")
    prev_password = os.environ.get("POSTGRES_PASSWORD")
    admin_user = os.environ.get("POSTGRES_ADMIN_USER")
    admin_password = os.environ.get("POSTGRES_ADMIN_PASSWORD")
    if admin_user:
        os.environ["POSTGRES_USER"] = admin_user
    if admin_password:
        os.environ["POSTGRES_PASSWORD"] = admin_password
    try:
        yield
    finally:
        if prev_user is None:
            os.environ.pop("POSTGRES_USER", None)
        else:
            os.environ["POSTGRES_USER"] = prev_user
        if prev_password is None:
            os.environ.pop("POSTGRES_PASSWORD", None)
        else:
            os.environ["POSTGRES_PASSWORD"] = prev_password


def ensure_schema(*, schema: str | None = None) -> None:
    """Apply Alembic migrations and post-migration DB primitives."""
    mode = _schema_mode()
    _assert_schema_mode_allowed(mode)
    target_schema = "public" if schema in (None, "", "public") else schema.strip()
    validate_identifier(target_schema, kind="schema")
    if target_schema != "public":
        with admin_transaction() as session:
            session.execute(f"CREATE SCHEMA IF NOT EXISTS {target_schema}")
    else:
        _bootstrap_public_schema_if_needed()
    _run_alembic_upgrade_head(schema=target_schema)
    if target_schema == "public":
        _ensure_post_alembic_primitives(schema=schema)
