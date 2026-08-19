"""
Helpers for populating location junction tables for indexed matching.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from core.data.schema_registry import TABLE_COLUMNS
from core.data.sql_identifiers import validate_identifier
from core.matcher.ports.db import DbSession
from core.models_cast import as_int, as_str, row_at
from core.utils.common import norm_text, split_location_tokens

LocationEntity = Literal["demande", "offer"]

_LOCATION_TABLES: dict[LocationEntity, tuple[str, str]] = {
    "demande": ("demande_locations", "demande_id"),
    "offer": ("offer_locations", "offer_id"),
}
_ALLOWED_TABLES = {table for table, _ in _LOCATION_TABLES.values()}
_ALLOWED_ID_COLUMNS = {column for _, column in _LOCATION_TABLES.values()}
_PARENT_TABLES: dict[LocationEntity, str] = {
    "demande": "demandes",
    "offer": "offers",
}


def _normalize_location_tokens(locations_str: str) -> list[str]:
    raw_tokens = split_location_tokens(locations_str)
    normalized = [norm_text(token) for token in raw_tokens]
    return sorted({token for token in normalized if token})


def _load_location_ids(session: DbSession, unique_norms: Sequence[str]) -> dict[str, int]:
    if not unique_norms:
        return {}
    session.executemany(
        "INSERT INTO locations (location_norm) VALUES (%s) "
        "ON CONFLICT (location_norm) DO NOTHING",
        [(token,) for token in unique_norms],
    )
    placeholders = ",".join("%s" for _ in unique_norms)
    rows = session.execute(
        f"SELECT location_id, location_norm FROM locations WHERE location_norm IN ({placeholders})",
        list(unique_norms),
    ).fetchall()
    location_ids: dict[str, int] = {}
    for row in rows:
        location_id = row_at(row, 0)
        location_norm = row_at(row, 1)
        if location_id is None or location_norm is None:
            continue
        location_ids[as_str(location_norm)] = as_int(location_id)
    return location_ids


def _bulk_insert_links(
    session: DbSession,
    *,
    entity: LocationEntity,
    links: Sequence[tuple[int, int]],
) -> None:
    if not links:
        return
    table, id_column = _LOCATION_TABLES[entity]
    parent_table = _PARENT_TABLES[entity]
    validate_identifier(table, allowed=_ALLOWED_TABLES, kind="table")
    validate_identifier(id_column, allowed=_ALLOWED_ID_COLUMNS, kind="column")
    value_placeholders: list[str] = []
    params: list[int] = []
    for entity_id, location_id in links:
        value_placeholders.append("(%s, %s)")
        params.extend([int(entity_id), int(location_id)])
    session.execute(
        f"""
        INSERT INTO {table} (agency_id, {id_column}, location_id)
        SELECT parent.agency_id, input_rows.entity_id, input_rows.location_id
        FROM (VALUES {', '.join(value_placeholders)}) AS input_rows(entity_id, location_id)
        JOIN {parent_table} parent ON parent.id = input_rows.entity_id
        ON CONFLICT ({id_column}, location_id) DO NOTHING
        """,
        params,
    )


def populate_location_links_batch(
    session: DbSession,
    *,
    entity: LocationEntity,
    entity_locations: Sequence[tuple[int | None, str]],
    clear_existing: bool = False,
) -> None:
    valid_rows = [
        (int(entity_id), str(locations_str or ""))
        for entity_id, locations_str in entity_locations
        if entity_id
    ]
    if not valid_rows:
        return

    table, id_column = _LOCATION_TABLES[entity]
    validate_identifier(table, allowed=_ALLOWED_TABLES, kind="table")
    allowed_cols = TABLE_COLUMNS.get(table)
    if allowed_cols is None:
        raise ValueError(f"Unknown location table: {table!r}")
    validate_identifier(id_column, allowed=allowed_cols, kind="column")
    validate_identifier("location_id", allowed=allowed_cols, kind="column")

    entity_ids = sorted({entity_id for entity_id, _ in valid_rows})
    if clear_existing:
        session.execute(
            f"DELETE FROM {table} WHERE {id_column} = ANY(%s)",
            (entity_ids,),
        )

    tokens_by_entity: list[tuple[int, list[str]]] = [
        (entity_id, _normalize_location_tokens(locations_str))
        for entity_id, locations_str in valid_rows
    ]
    unique_norms = sorted({token for _entity_id, tokens in tokens_by_entity for token in tokens})
    if not unique_norms:
        return

    location_ids = _load_location_ids(session, unique_norms)
    links = sorted(
        {
            (entity_id, location_ids[token])
            for entity_id, tokens in tokens_by_entity
            for token in tokens
            if token in location_ids
        }
    )
    _bulk_insert_links(session, entity=entity, links=links)


def populate_location_links(
    session: DbSession,
    *,
    entity: LocationEntity,
    entity_id: int | None,
    locations_str: str,
) -> None:
    """
    Populate the junction table for a demande/offer using normalized locations.

    This clears existing links for the entity, inserts unique normalized locations,
    then links them through the junction table.
    """
    if not entity_id:
        return
    populate_location_links_batch(
        session,
        entity=entity,
        entity_locations=[(entity_id, locations_str)],
        clear_existing=True,
    )
