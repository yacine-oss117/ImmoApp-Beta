from __future__ import annotations

import os
import re
from logging.config import fileConfig
from typing import Any
from urllib.parse import quote_plus

from alembic import context
from sqlalchemy import engine_from_config, pool, text

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _load_db_credentials_from_secrets() -> str | None:
    """Best-effort OpenBao bootstrap for direct Alembic CLI runs.

    `python -m alembic ...` does not execute `manage.py`, so runtime secret
    bootstrap is skipped unless we explicitly invoke it here.
    """
    required = ("POSTGRES_ADMIN_USER", "POSTGRES_ADMIN_PASSWORD")
    if all(os.environ.get(name) for name in required):
        return None
    try:
        from server.secret_store.loader import load_secrets
    except Exception as exc:  # pragma: no cover - defensive import fallback
        return f"secret loader unavailable: {exc}"

    previous_allowlist = os.environ.get("IMMOAPP_SECRETS_ALLOWLIST")
    if not previous_allowlist:
        # Include DB credentials for migration-time bootstrap.
        os.environ["IMMOAPP_SECRETS_ALLOWLIST"] = "ALE_,DJANGO_,IMMOAPP_,POSTGRES_"
    try:
        load_secrets()
    except Exception as exc:  # pragma: no cover - propagated as explicit config error below
        return str(exc)
    finally:
        if previous_allowlist is None:
            os.environ.pop("IMMOAPP_SECRETS_ALLOWLIST", None)
    return None


def _require_db_env(name: str, *, bootstrap_error: str | None = None) -> str:
    value = (os.environ.get(name) or "").strip()
    if value:
        return value
    detail = f"{name} is required for Alembic database connection."
    if bootstrap_error:
        detail += f" Secrets bootstrap error: {bootstrap_error}"
    raise RuntimeError(detail)


def _db_url_from_env() -> str:
    bootstrap_error = _load_db_credentials_from_secrets()
    user = (os.environ.get("POSTGRES_ADMIN_USER") or os.environ.get("POSTGRES_USER") or "").strip()
    if not user:
        user = _require_db_env("POSTGRES_ADMIN_USER", bootstrap_error=bootstrap_error)
    password = (
        os.environ.get("POSTGRES_ADMIN_PASSWORD") or os.environ.get("POSTGRES_PASSWORD") or ""
    ).strip()
    if not password:
        password = _require_db_env("POSTGRES_ADMIN_PASSWORD", bootstrap_error=bootstrap_error)
    host = (os.environ.get("POSTGRES_HOST") or "127.0.0.1").strip()
    port = (os.environ.get("POSTGRES_PORT") or "5432").strip()
    db = _require_db_env("POSTGRES_DB", bootstrap_error=bootstrap_error)
    return f"postgresql+psycopg://{user}:{quote_plus(password)}@{host}:{port}/{db}"


config.set_main_option("sqlalchemy.url", _db_url_from_env())

target_metadata = None
_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _target_schema() -> str:
    schema = os.environ.get("IMMOAPP_ALEMBIC_SCHEMA", "public").strip() or "public"
    if not _SCHEMA_RE.fullmatch(schema):
        raise RuntimeError(f"Unsafe IMMOAPP_ALEMBIC_SCHEMA: {schema!r}")
    return schema


def _context_kwargs() -> dict[str, Any]:
    schema = _target_schema()
    kwargs: dict[str, Any] = {"target_metadata": target_metadata}
    if schema != "public":
        kwargs["version_table_schema"] = schema
    return kwargs


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, literal_binds=True, **_context_kwargs())

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        schema = _target_schema()
        if schema != "public":
            connection.execute(text(f"SET search_path TO {schema}, public"))
        context.configure(connection=connection, **_context_kwargs())

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
