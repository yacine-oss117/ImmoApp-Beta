"""Postgres unit-of-work public API."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from core.data.sql_identifiers import validate_identifier

from .observability import record_query
from .uow_internal import (
    DbSession,
    PgConn,
    PgCursor,
    RowMapping,
    _apply_admin_search_path,
    _apply_search_path,
    _build_admin_dsn,
    _build_conn_options,
    _build_dsn,
    _check_connection,
    _clear_session_context,
    _configure_pool_connection,
    _get_pool,
    _load_env,
    _require_env,
    _require_tenant_context_for_transaction,
    _reset_connection,
    _reset_pool_connection,
    _run_in_autocommit,
    _set_session_context,
    close_pool,
    get_pool_stats,
    warmup_pool,
)

_SCHEMA_CTX: ContextVar[str] = ContextVar("schema", default="public")
_AGENCY_ID_CTX: ContextVar[int | None] = ContextVar("agency_id", default=None)
_IS_SUPERUSER_CTX: ContextVar[bool] = ContextVar("is_superuser", default=False)
_ACTOR_ID_CTX: ContextVar[int | None] = ContextVar("actor_id", default=None)
_ACTOR_EMAIL_CTX: ContextVar[str | None] = ContextVar("actor_email", default=None)
_ACTOR_ROLE_CTX: ContextVar[str | None] = ContextVar("actor_role", default=None)
_ACTOR_IS_OWNER_CTX: ContextVar[bool] = ContextVar("actor_is_owner", default=False)
_ALLOWED_SCHEMAS = {"public", "sim"}

logger = logging.getLogger(__name__)
_POOL: ConnectionPool[PgConn] | None = None


def _normalize_schema(schema: str | None) -> str:
    if not schema:
        return "public"
    schema = schema.strip()
    if not schema:
        return "public"
    validate_identifier(schema, allowed=_ALLOWED_SCHEMAS, kind="schema")
    return schema


def set_schema(schema: str | None) -> None:
    _SCHEMA_CTX.set(_normalize_schema(schema))


def _pool_connection(*, timeout: float | None = None) -> AbstractContextManager[PgConn]:
    pool = _get_pool()
    if timeout is None:
        return pool.connection()
    return pool.connection(timeout=timeout)


@contextmanager
def use_schema(schema: str | None) -> Iterator[None]:
    token = _SCHEMA_CTX.set(_normalize_schema(schema))
    try:
        yield
    finally:
        _SCHEMA_CTX.reset(token)


def get_current_schema() -> str:
    return _SCHEMA_CTX.get()


def get_current_agency_id() -> int | None:
    return _AGENCY_ID_CTX.get()


def is_current_user_superuser() -> bool:
    return _IS_SUPERUSER_CTX.get()


def get_current_actor_id() -> int | None:
    return _ACTOR_ID_CTX.get()


def get_current_actor_email() -> str | None:
    return _ACTOR_EMAIL_CTX.get()


def get_current_actor_role() -> str | None:
    return _ACTOR_ROLE_CTX.get()


def is_current_actor_owner() -> bool:
    return _ACTOR_IS_OWNER_CTX.get()


def set_actor_context(
    *,
    actor_id: int | None = None,
    actor_email: str | None = None,
    actor_role: str | None = None,
    actor_is_owner: bool = False,
) -> None:
    _ACTOR_ID_CTX.set(actor_id)
    _ACTOR_EMAIL_CTX.set(actor_email)
    _ACTOR_ROLE_CTX.set(actor_role)
    _ACTOR_IS_OWNER_CTX.set(actor_is_owner)


@contextmanager
def use_actor_context(
    *,
    actor_id: int | None = None,
    actor_email: str | None = None,
    actor_role: str | None = None,
    actor_is_owner: bool = False,
) -> Iterator[None]:
    token_id = _ACTOR_ID_CTX.set(actor_id)
    token_email = _ACTOR_EMAIL_CTX.set(actor_email)
    token_role = _ACTOR_ROLE_CTX.set(actor_role)
    token_owner = _ACTOR_IS_OWNER_CTX.set(actor_is_owner)
    try:
        yield
    finally:
        _ACTOR_ID_CTX.reset(token_id)
        _ACTOR_EMAIL_CTX.reset(token_email)
        _ACTOR_ROLE_CTX.reset(token_role)
        _ACTOR_IS_OWNER_CTX.reset(token_owner)


def set_security_context(*, agency_id: int | None = None, is_superuser: bool = False) -> None:
    _AGENCY_ID_CTX.set(agency_id)
    _IS_SUPERUSER_CTX.set(is_superuser)


@contextmanager
def use_security_context(
    *, agency_id: int | None = None, is_superuser: bool = False
) -> Iterator[None]:
    token_agency = _AGENCY_ID_CTX.set(agency_id)
    token_super = _IS_SUPERUSER_CTX.set(is_superuser)
    try:
        yield
    finally:
        _AGENCY_ID_CTX.reset(token_agency)
        _IS_SUPERUSER_CTX.reset(token_super)


class PgSession:
    """Postgres implementation of DbSession with native SQL."""

    def __init__(self, conn: PgConn, *, on_commit_enabled: bool = False) -> None:
        self._conn = conn
        self._cursor: PgCursor | None = None
        self._lastrowid: int | None = None
        self._lastrow: RowMapping | None = None
        self._on_commit_enabled = on_commit_enabled
        self._on_commit_callbacks: list[Callable[[], None]] = []

    def execute(self, sql: str, params: Sequence[object] = ()) -> PgSession:
        self._lastrowid = None
        self._lastrow = None
        sql_text = sql
        start = time.monotonic()
        self._cursor = self._conn.execute(sql_text, params)
        record_query(
            sql_text,
            time.monotonic() - start,
            self._cursor.rowcount if self._cursor else None,
        )
        if (
            self._cursor
            and sql_text.lstrip().upper().startswith("INSERT")
            and "RETURNING" in sql_text.upper()
        ):
            row = self._cursor.fetchone()
            if row:
                self._lastrow = row
                row_id = row.get("id")
                if isinstance(row_id, int):
                    self._lastrowid = row_id
        return self

    def executemany(self, sql: str, params: Iterable[Sequence[object]]) -> PgSession:
        start = time.monotonic()
        self._cursor = self._conn.cursor()
        self._cursor.executemany(sql, params)
        record_query(
            sql,
            time.monotonic() - start,
            self._cursor.rowcount if self._cursor else None,
        )
        return self

    def fetchone(self) -> RowMapping | None:
        if self._lastrow is not None:
            row = self._lastrow
            self._lastrow = None
            return row
        if self._cursor is None:
            return None
        return self._cursor.fetchone()

    def fetchall(self) -> list[RowMapping]:
        if self._cursor is None:
            if self._lastrow is None:
                return []
            row = self._lastrow
            self._lastrow = None
            return [row]
        if self._lastrow is None:
            return self._cursor.fetchall()
        first = self._lastrow
        self._lastrow = None
        rest = self._cursor.fetchall()
        return [first, *rest]

    def fetchmany(self, size: int = 1000) -> list[RowMapping]:
        if size <= 0:
            return []
        if self._cursor is None:
            if self._lastrow is None:
                return []
            row = self._lastrow
            self._lastrow = None
            return [row]
        if self._lastrow is None:
            return self._cursor.fetchmany(size)
        first = self._lastrow
        self._lastrow = None
        if size == 1:
            return [first]
        rest = self._cursor.fetchmany(size - 1)
        return [first, *rest]

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def on_commit(self, callback: Callable[[], None]) -> None:
        if not self._on_commit_enabled:
            raise RuntimeError("on_commit callbacks are only available inside transaction()")
        self._on_commit_callbacks.append(callback)

    def _run_on_commit_callbacks(self) -> None:
        callbacks = list(self._on_commit_callbacks)
        self._on_commit_callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                logger.warning("Post-commit callback failed", exc_info=True)

    def _clear_on_commit_callbacks(self) -> None:
        self._on_commit_callbacks.clear()

    @property
    def lastrowid(self) -> int | None:
        return self._lastrowid

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount if self._cursor else 0

    @property
    def connection(self) -> PgConn:
        return self._conn


@contextmanager
def admin_transaction(schema: str | None = None) -> Iterator[PgSession]:
    """Run a transaction using the admin database credentials."""
    conn: PgConn = psycopg.connect(_build_admin_dsn(), row_factory=dict_row)
    try:
        _apply_admin_search_path(conn, _normalize_schema(schema))
        _set_session_context(
            conn,
            agency_id=None,
            is_superuser=True,
            actor=None,
            actor_id=None,
            actor_email=None,
            actor_role=None,
            actor_is_owner=False,
        )
        session = PgSession(conn)
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        else:
            session.commit()
    finally:
        try:
            _reset_connection(conn)
        finally:
            conn.close()


class PgUnitOfWork:
    """Postgres UnitOfWork with optional audit actor support."""

    @contextmanager
    def session(
        self,
        *,
        actor: str | None = None,
        is_superuser: bool | None = None,
        timeout: float | None = None,
    ) -> Iterator[PgSession]:
        with _pool_connection(timeout=timeout) as conn:
            _apply_search_path(conn, _normalize_schema(_SCHEMA_CTX.get()))
            _set_session_context(
                conn,
                agency_id=_AGENCY_ID_CTX.get(),
                is_superuser=(
                    is_superuser if is_superuser is not None else _IS_SUPERUSER_CTX.get()
                ),
                actor=actor,
                actor_id=_ACTOR_ID_CTX.get(),
                actor_email=_ACTOR_EMAIL_CTX.get(),
                actor_role=_ACTOR_ROLE_CTX.get(),
                actor_is_owner=_ACTOR_IS_OWNER_CTX.get(),
            )
            try:
                yield PgSession(conn, on_commit_enabled=False)
            finally:
                try:
                    conn.rollback()
                except Exception:
                    logger.warning(
                        "Postgres session cleanup rollback failed; continuing with pool reset.",
                        exc_info=True,
                    )

    @contextmanager
    def transaction(
        self,
        *,
        actor: str | None = None,
        is_superuser: bool | None = None,
        timeout: float | None = None,
    ) -> Iterator[PgSession]:
        with _pool_connection(timeout=timeout) as conn:
            _apply_search_path(conn, _normalize_schema(_SCHEMA_CTX.get()))
            effective_superuser = (
                is_superuser if is_superuser is not None else _IS_SUPERUSER_CTX.get()
            )
            effective_agency_id = _AGENCY_ID_CTX.get()
            _set_session_context(
                conn,
                agency_id=effective_agency_id,
                is_superuser=effective_superuser,
                actor=actor,
                actor_id=_ACTOR_ID_CTX.get(),
                actor_email=_ACTOR_EMAIL_CTX.get(),
                actor_role=_ACTOR_ROLE_CTX.get(),
                actor_is_owner=_ACTOR_IS_OWNER_CTX.get(),
            )
            _require_tenant_context_for_transaction(
                agency_id=effective_agency_id,
                is_superuser=effective_superuser,
            )
            session = PgSession(conn, on_commit_enabled=True)
            try:
                yield session
            except Exception:
                logger.debug("Postgres transaction rolling back due to exception")
                session._clear_on_commit_callbacks()
                session.rollback()
                raise
            else:
                session.commit()
                session._run_on_commit_callbacks()
                logger.debug("Postgres transaction committed successfully")


def get_uow() -> PgUnitOfWork:
    return PgUnitOfWork()


__all__ = [
    "RowMapping",
    "PgConn",
    "PgCursor",
    "DbSession",
    "PgSession",
    "PgUnitOfWork",
    "admin_transaction",
    "get_uow",
    "set_schema",
    "use_schema",
    "get_current_schema",
    "get_current_agency_id",
    "is_current_user_superuser",
    "set_security_context",
    "use_security_context",
    "get_current_actor_id",
    "get_current_actor_email",
    "get_current_actor_role",
    "is_current_actor_owner",
    "set_actor_context",
    "use_actor_context",
    "warmup_pool",
    "get_pool_stats",
    "close_pool",
    "_get_pool",
    "_load_env",
    "_require_env",
    "_build_conn_options",
    "_build_dsn",
    "_build_admin_dsn",
    "_run_in_autocommit",
    "_check_connection",
    "_configure_pool_connection",
    "_reset_pool_connection",
    "_normalize_schema",
    "_SCHEMA_CTX",
    "_AGENCY_ID_CTX",
    "_IS_SUPERUSER_CTX",
    "_ACTOR_ID_CTX",
    "_ACTOR_EMAIL_CTX",
    "_ACTOR_ROLE_CTX",
    "_ACTOR_IS_OWNER_CTX",
    "_set_session_context",
    "_apply_search_path",
    "_apply_admin_search_path",
    "_clear_session_context",
    "_reset_connection",
    "_require_tenant_context_for_transaction",
]
