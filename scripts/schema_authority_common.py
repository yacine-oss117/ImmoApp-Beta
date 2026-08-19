from __future__ import annotations

import importlib
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.repo_layout import ALEMBIC_ROOT, DOCS_REFERENCE_ROOT
from server.pg.schema_authority_registry import (
    SchemaTableContract,
    iter_state_only_mirror_contracts,
    iter_schema_table_contracts,
    schema_table_contracts_by_name,
)

_CREATE_TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+([a-zA-Z0-9_]+)", re.MULTILINE)


def configure_django() -> None:
    os.environ.setdefault("IMMOAPP_SECRETS_BACKEND", "env")
    os.environ.setdefault("IMMOAPP_ALLOW_ENV_SECRETS", "1")
    os.environ.setdefault("IMMOAPP_SECRETS_REQUIRED", "0")
    os.environ.setdefault("IMMOAPP_SECRETS_OVERWRITE", "0")
    os.environ.setdefault("IMMOAPP_SKIP_CELERY_APP", "1")
    os.environ.setdefault("IMMOAPP_ALLOW_HTTP_ONLY_ASGI_FALLBACK", "1")
    os.environ.setdefault("DJANGO_SECRET_KEY", "schema-authority-unsafe-for-prod")
    os.environ.setdefault("DJANGO_DEBUG", "1")
    os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
    os.environ.setdefault("POSTGRES_HOST", "127.0.0.1")
    os.environ.setdefault("POSTGRES_PORT", "5432")
    os.environ.setdefault("POSTGRES_DB", "immoapp")
    os.environ.setdefault("POSTGRES_USER", "immoapp_app")
    os.environ.setdefault("POSTGRES_PASSWORD", "immoapp_app_password")
    os.environ.setdefault("POSTGRES_ADMIN_USER", "immoapp")
    os.environ.setdefault("POSTGRES_ADMIN_PASSWORD", "immoapp_admin_password")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")


@lru_cache(maxsize=1)
def get_django_apps() -> Any:
    configure_django()
    import django

    django.setup()
    from django.apps import apps

    return apps


@lru_cache(maxsize=1)
def django_models_by_table() -> dict[str, Any]:
    apps = get_django_apps()
    return {str(model._meta.db_table): model for model in apps.get_models()}


@lru_cache(maxsize=1)
def django_models_by_label() -> dict[str, Any]:
    apps = get_django_apps()
    return {str(model._meta.label): model for model in apps.get_models()}


@lru_cache(maxsize=1)
def discover_alembic_table_revisions() -> dict[str, set[str]]:
    revisions: dict[str, set[str]] = {}
    for path in sorted((ALEMBIC_ROOT / "versions").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        revision_id = path.stem.split("_", 1)[0]
        for table_name in _CREATE_TABLE_RE.findall(text):
            revisions.setdefault(str(table_name), set()).add(revision_id)
    return revisions


def discover_alembic_tables() -> tuple[str, ...]:
    return tuple(sorted(discover_alembic_table_revisions()))


def local_migration_files() -> tuple[Path, ...]:
    paths = []
    for path in sorted((REPO_ROOT / "server").glob("*/migrations/[0-9][0-9][0-9][0-9]_*.py")):
        if path.name == "__init__.py":
            continue
        paths.append(path)
    return tuple(paths)


def migration_id_from_path(path: Path) -> str:
    parts = path.relative_to(REPO_ROOT).parts
    app_label = parts[1]
    return f"{app_label}.{path.stem}"


def load_migration_class(path: Path) -> type[Any]:
    get_django_apps()
    module_name = ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)
    module = importlib.import_module(module_name)
    return module.Migration


def state_only_mirror_migration_ids() -> tuple[str, ...]:
    ids = {
        contract.creating_django_migration
        for contract in iter_schema_table_contracts()
        if contract.mirror_strategy == "state_only_mirror" and contract.creating_django_migration
    }
    return tuple(sorted(ids))


def render_contract_table(contracts: tuple[SchemaTableContract, ...]) -> list[str]:
    lines = [
        "| Table | Owner | Mirror | ORM Model | Alembic Revision | Django Migration | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for contract in sorted(contracts, key=lambda item: item.table_name):
        notes = contract.notes or ""
        orm_model = contract.orm_model or "-"
        alembic_revision = contract.creating_alembic_revision or "-"
        django_migration = contract.creating_django_migration or "-"
        lines.append(
            "| "
            + f"`{contract.table_name}` | "
            + f"`{contract.owner}` | "
            + f"`{contract.mirror_strategy}` | "
            + f"`{orm_model}` | "
            + f"`{alembic_revision}` | "
            + f"`{django_migration}` | "
            + f"{notes} |"
        )
    return lines


SCHEMA_AUTHORITY_OUTPUT_PATH = DOCS_REFERENCE_ROOT / "SCHEMA_AUTHORITY.md"
