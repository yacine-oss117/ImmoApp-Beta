"""Internal plumbing for Postgres unit-of-work."""

from __future__ import annotations

import atexit
import logging
import os
from collections.abc import Callable

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from core.runtime.hub_runtime_profile import resolve_hub_runtime_profile

from .uow_internal_ale import (
    _resolve_ale_search_secret,
    _resolve_ale_trigram_limit,
    _resolve_search_key_versions,
)
from .uow_internal_env import _load_env, _require_env

RowMapping = dict[str, object]
PgConn = psycopg.Connection[RowMapping]
PgCursor = psycopg.Cursor[RowMapping]
DbSession = "PgSession"

logger = logging.getLogger(__name__)
_POOL_CLOSE_REGISTERED = False


def _set_config_values(
    conn: PgConn,
    settings: list[tuple[str, str, bool]],
) -> None:
    """Apply multiple set_config calls in a single roundtrip."""
    if not settings:
        return
    placeholders: list[str] = []
    params: list[object] = []
    for key, value, is_local in settings:
        placeholders.append("set_config(%s, %s, %s)")
        params.extend([key, value, is_local])
    sql = "SELECT " + ", ".join(placeholders)
    conn.execute(sql, tuple(params))


def _build_conn_options() -> str:
    statement_ms = int(os.environ.get("PG_STATEMENT_TIMEOUT_MS", "30000"))
    lock_ms = int(os.environ.get("PG_LOCK_TIMEOUT_MS", "5000"))
    idle_ms = int(os.environ.get("PG_IDLE_TX_TIMEOUT_MS", "60000"))
    options: list[str] = []
    if statement_ms > 0:
        options.append(f"-c statement_timeout={statement_ms}")
    if lock_ms > 0:
        options.append(f"-c lock_timeout={lock_ms}")
    if idle_ms > 0:
        options.append(f"-c idle_in_transaction_session_timeout={idle_ms}")
    if not options:
        return ""
    opts = " ".join(options)
    return f" options='{opts}'"


def _build_dsn() -> str:
    _load_env()
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = _require_env("POSTGRES_DB")
    user = _require_env("POSTGRES_USER")
    password = _require_env("POSTGRES_PASSWORD")
    base = f"host={host} port={port} dbname={dbname} user={user} password={password}"
    return f"{base}{_build_conn_options()}"


def _build_admin_dsn() -> str:
    _load_env()
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = _require_env("POSTGRES_DB")
    user = _require_env("POSTGRES_ADMIN_USER")
    password = _require_env("POSTGRES_ADMIN_PASSWORD")
    base = f"host={host} port={port} dbname={dbname} user={user} password={password}"
    return f"{base}{_build_conn_options()}"


def _run_in_autocommit(conn: PgConn, action: Callable[[], object]) -> None:
    """Run a small setup query without leaving the connection in a transaction."""
    autocommit = conn.autocommit
    try:
        conn.autocommit = True
        action()
    finally:
        conn.autocommit = autocommit


def _check_connection(conn: PgConn) -> None:
    _run_in_autocommit(conn, lambda: conn.execute("SELECT 1"))


def _clear_session_context(conn: PgConn) -> None:
    """Reset RLS session variables before returning a pooled connection."""
    _set_config_values(
        conn,
        [
            ("app.current_agency_id", "", False),
            ("app.is_superuser", "", False),
            ("app.audit_actor", "", False),
            ("app.actor_id", "", False),
            ("app.actor_email", "", False),
            ("app.actor_role", "", False),
            ("app.actor_is_owner", "", False),
            ("app.ale_search_secret", "", False),
            ("app.ale_search_secret_version", "", False),
            ("app.ale_search_secret_prev_version", "", False),
            ("app.ale_search_secrets", "", False),
            ("app.ale_trigram_limit", "", False),
        ],
    )


def _configure_pool_connection(conn: PgConn) -> None:
    """Initialize new pooled connections with safe defaults."""
    try:

        def _apply() -> None:
            conn.execute("RESET ROLE")
            conn.execute("SET search_path TO public")
            _clear_session_context(conn)

        _run_in_autocommit(conn, _apply)
    except psycopg.Error:
        logger.exception("Failed to configure pooled connection")


def _reset_pool_connection(conn: PgConn) -> None:
    """Reset pooled connections to safe defaults on return."""
    try:
        try:
            conn.rollback()
        except Exception:
            pass

        def _apply() -> None:
            conn.execute("RESET ROLE")
            conn.execute("SET search_path TO public")
            _clear_session_context(conn)

        _run_in_autocommit(conn, _apply)
    except psycopg.Error:
        logger.exception("Failed to reset pooled connection")


def _register_pool_close() -> None:
    """Ensure the pool is closed before interpreter shutdown."""
    global _POOL_CLOSE_REGISTERED
    if _POOL_CLOSE_REGISTERED:
        return
    atexit.register(close_pool)
    _POOL_CLOSE_REGISTERED = True


def _get_pool() -> ConnectionPool[PgConn]:
    from . import uow as uow_mod

    pool = uow_mod._POOL
    if pool is None:
        hub_limits = resolve_hub_runtime_profile().limits
        min_size = int(os.environ.get("PG_POOL_MIN", "1"))
        max_size = int(os.environ.get("PG_POOL_MAX", str(hub_limits.db_pool_size)))
        pool_timeout = float(os.environ.get("PG_POOL_TIMEOUT", "10"))
        pool = ConnectionPool(
            conninfo=_build_dsn(),
            min_size=min_size,
            max_size=max_size,
            timeout=pool_timeout,
            connection_class=psycopg.Connection[RowMapping],
            kwargs={"row_factory": dict_row},
            configure=_configure_pool_connection,
            check=_check_connection,
            reset=_reset_pool_connection,
            open=True,
        )
        uow_mod._POOL = pool
        logger.info("Postgres pool initialized (min=%s max=%s)", min_size, max_size)
        _register_pool_close()
    return pool


def warmup_pool() -> None:
    """Pre-create pooled connections to avoid cold-start latency spikes."""
    if not resolve_hub_runtime_profile().limits.startup_warmup_enabled:
        logger.info("Postgres pool warmup skipped by Hub runtime profile")
        return
    pool = _get_pool()
    try:
        pool.wait(timeout=float(os.environ.get("PG_POOL_WARMUP_TIMEOUT", "10")))
    except Exception:
        logger.warning("Postgres pool warmup failed", exc_info=True)


def get_pool_stats() -> dict[str, object]:
    """Expose lightweight pool statistics for observability."""
    pool = _get_pool()
    if not hasattr(pool, "get_stats"):
        return {}
    stats = pool.get_stats()
    if isinstance(stats, dict):
        return dict(stats)
    if hasattr(stats, "_asdict"):
        return dict(stats._asdict())
    if hasattr(stats, "__dict__"):
        return dict(stats.__dict__)
    return {}


def close_pool() -> None:
    """Close the shared pool to avoid background thread warnings in scripts."""
    from . import uow as uow_mod

    pool = uow_mod._POOL
    if pool is None:
        return
    try:
        pool.close()
    finally:
        uow_mod._POOL = None


def _set_session_context(
    conn: PgConn,
    *,
    agency_id: int | None,
    is_superuser: bool,
    actor: str | None,
    actor_id: int | None,
    actor_email: str | None,
    actor_role: str | None,
    actor_is_owner: bool,
) -> None:
    current_version, prev_version = _resolve_search_key_versions(conn)
    current_secret = _resolve_ale_search_secret(agency_id, version=current_version)
    secret_values = [current_secret]
    if prev_version:
        secret_values.append(_resolve_ale_search_secret(agency_id, version=prev_version))
    _set_config_values(
        conn,
        [
            ("app.current_agency_id", str(agency_id or ""), True),
            ("app.is_superuser", "true" if is_superuser else "false", True),
            ("app.audit_actor", str(actor or ""), True),
            ("app.actor_id", str(actor_id or ""), True),
            ("app.actor_email", str(actor_email or ""), True),
            ("app.actor_role", str(actor_role or ""), True),
            ("app.actor_is_owner", "true" if actor_is_owner else "false", True),
            ("app.ale_search_secret", current_secret, True),
            ("app.ale_search_secret_version", current_version, True),
            ("app.ale_search_secret_prev_version", prev_version or "", True),
            ("app.ale_search_secrets", ";".join(secret_values), True),
            ("app.ale_trigram_limit", _resolve_ale_trigram_limit(), True),
        ],
    )


def _apply_search_path(conn: PgConn, schema: str) -> None:
    if schema == "public":
        conn.execute("SET search_path TO public")
    else:
        conn.execute(f"SET search_path TO {schema}, public")


def _apply_admin_search_path(conn: PgConn, schema: str) -> None:
    _apply_search_path(conn, schema)


def _reset_connection(conn: PgConn) -> None:
    """Restore connection defaults before returning it to the pool."""
    try:
        conn.rollback()
        _clear_session_context(conn)
        conn.execute("SET search_path TO public")
        conn.execute("RESET ROLE")
    except psycopg.Error:
        logger.exception("Failed to reset pooled connection state")
        try:
            conn.close()
        except psycopg.Error:
            logger.exception("Failed to close pooled connection after reset failure")


def _require_tenant_context_for_transaction(*, agency_id: int | None, is_superuser: bool) -> None:
    """
    Hard fail for write transactions without tenant context.
    Allowed when is_superuser is true (admin/schema operations).
    """
    if is_superuser:
        return
    if agency_id is None:
        raise RuntimeError("Missing tenant context: agency_id is required for PgUow.transaction()")
