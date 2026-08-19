"""
Sync-friendly change feeds for core tables.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.data.sql_identifiers import validate_identifier
from core.matcher.ports.db import DbSession


@dataclass(frozen=True)
class SyncTable:
    name: str
    changed_expr: str
    order_by: str
    pk: str | None = "id"


SYNC_TABLES: dict[str, SyncTable] = {
    "clients": SyncTable(
        name="clients",
        changed_expr="COALESCE(updated_at, created_at, deleted_at)",
        order_by="changed_at, id",
    ),
    "listings": SyncTable(
        name="listings",
        changed_expr="COALESCE(updated_at, created_at, deleted_at)",
        order_by="changed_at, id",
    ),
    "demandes": SyncTable(
        name="demandes",
        changed_expr="COALESCE(updated_at, created_at, deleted_at)",
        order_by="changed_at, id",
    ),
    "offers": SyncTable(
        name="offers",
        changed_expr="COALESCE(updated_at, created_at, deleted_at)",
        order_by="changed_at, id",
    ),
    "offer_photos": SyncTable(
        name="offer_photos",
        changed_expr="COALESCE(updated_at, created_at, deleted_at)",
        order_by="changed_at, id",
    ),
    "visits": SyncTable(
        name="visits",
        changed_expr="COALESCE(updated_at, created_at, deleted_at)",
        order_by="changed_at, id",
    ),
    "contracts": SyncTable(
        name="contracts",
        changed_expr="COALESCE(updated_at, created_at, deleted_at)",
        order_by="changed_at, id",
    ),
    "contract_articles": SyncTable(
        name="contract_articles",
        changed_expr="COALESCE(updated_at, created_at, deleted_at)",
        order_by="changed_at, id",
    ),
    "custom_locations": SyncTable(
        name="custom_locations",
        changed_expr="COALESCE(updated_at, created_at, deleted_at)",
        order_by="changed_at, id",
    ),
    "wa_templates": SyncTable(
        name="wa_templates",
        changed_expr="COALESCE(updated_at, created_at, deleted_at)",
        order_by="changed_at, id",
    ),
    "agency_settings": SyncTable(
        name="agency_settings",
        changed_expr="updated_at",
        order_by="updated_at, key",
        pk=None,
    ),
}


def fetch_changes(
    session: DbSession,
    *,
    table: str,
    since: str,
    limit: int = 1000,
    after_id: int | None = None,
) -> tuple[list[dict[str, object]], str | None, int | None]:
    """Fetch rows changed since a timestamp with a stable cursor."""
    config = SYNC_TABLES.get(table)
    if config is None:
        raise ValueError(f"Unknown sync table: {table!r}")
    validate_identifier(config.name, allowed=set(SYNC_TABLES.keys()), kind="table")
    if config.pk:
        validate_identifier(config.pk, kind="column")

    params: list[object] = [since]
    where = f"{config.changed_expr} > %s"
    if config.pk and after_id is not None:
        where = f"({config.changed_expr} > %s OR ({config.changed_expr} = %s AND {config.pk} > %s))"
        params = [since, since, after_id]

    sql = (
        f"SELECT *, {config.changed_expr} AS changed_at "
        f"FROM {config.name} "
        f"WHERE {where} "
        f"ORDER BY {config.order_by} "
        f"LIMIT %s"
    )
    params.append(limit)
    rows = session.execute(sql, params).fetchall()
    items = [dict(row) for row in rows]
    last_changed: str | None = None
    last_id: int | None = None
    if items:
        last = items[-1]
        if isinstance(last, dict):
            changed_value = last.get("changed_at")
            last_changed = str(changed_value) if changed_value is not None else None
        if config.pk and isinstance(last, dict):
            last_id_value = last.get(config.pk)
            if isinstance(last_id_value, int):
                last_id = last_id_value
            elif isinstance(last_id_value, str) and last_id_value.isdigit():
                last_id = int(last_id_value)
    for item in items:
        item.pop("changed_at", None)
    return items, last_changed, last_id
