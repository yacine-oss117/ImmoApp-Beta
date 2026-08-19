"""
Create/update operations for demandes.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from core.contracts.import_batch_refs import CreatedRowRef
from core.data.errors import ConflictError, NotFoundError
from core.data.location_junctions import populate_location_links, populate_location_links_batch
from core.data.surface_cache_generation import (
    CLIENTS_SURFACE,
    agency_scope_key,
    bump_generation,
    bump_generations,
)
from core.data.types import DemandeInput
from core.matcher.ports.db import DbSession
from core.models_cast import as_int, as_optional_float, as_optional_int
from core.utils.time import normalize_timestamp, utc_now_iso

logger = logging.getLogger(__name__)


def _normalize_source_ordinals(
    *,
    source_ordinals: Sequence[int] | None,
    expected_count: int,
    context: str,
) -> list[int]:
    if source_ordinals is None:
        return list(range(max(0, int(expected_count))))
    normalized = [int(value) for value in source_ordinals]
    if len(normalized) != max(0, int(expected_count)):
        raise ValueError(
            f"{context} received {len(normalized)} source ordinals for "
            f"{int(expected_count)} input rows."
        )
    if any(value < 0 for value in normalized):
        raise ValueError(f"{context} requires non-negative source ordinals.")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{context} requires unique source ordinals.")
    return normalized


def _allocate_created_row_refs(
    session: DbSession,
    *,
    table_name: str,
    source_ordinals: Sequence[int],
    context: str,
) -> list[CreatedRowRef]:
    normalized_ordinals = _normalize_source_ordinals(
        source_ordinals=source_ordinals,
        expected_count=len(source_ordinals),
        context=context,
    )
    if not normalized_ordinals:
        return []
    rows = session.execute(
        """
        SELECT nextval(pg_get_serial_sequence(%s, %s)) AS id
        FROM generate_series(1, %s::integer)
        """,
        (table_name, "id", len(normalized_ordinals)),
    ).fetchall()
    if len(rows) != len(normalized_ordinals):
        raise ValueError(
            f"{context} allocated {len(rows)} ids for {len(normalized_ordinals)} input rows."
        )
    return [
        CreatedRowRef(
            source_ordinal=normalized_ordinals[index],
            created_id=as_int(row["id"]),
        )
        for index, row in enumerate(rows)
    ]


def _materialize_demande_range_values(
    *,
    budget_min: float | None,
    budget_max: float | None,
    surface_min: float | None,
    surface_max: float | None,
    beds_min: int | None,
) -> tuple[float, float, float, float, int]:
    if budget_min is None and budget_max is None:
        raise ValueError("At least one budget bound is required for demandes")
    if surface_min is None and surface_max is None:
        raise ValueError("At least one surface bound is required for demandes")

    resolved_budget_min = 0.0 if budget_min is None else budget_min
    resolved_budget_max = resolved_budget_min if budget_max is None else budget_max
    resolved_surface_min = surface_min
    if resolved_surface_min is None:
        resolved_surface_min = surface_max
    if resolved_surface_min is None:
        raise ValueError("At least one surface bound is required for demandes")
    resolved_surface_max = resolved_surface_min if surface_max is None else surface_max
    resolved_beds_min = 0 if beds_min is None else int(beds_min)

    if resolved_beds_min < 0:
        raise ValueError("beds_min cannot be negative")
    if resolved_budget_min > resolved_budget_max:
        raise ValueError("budget_min cannot exceed budget_max")
    if resolved_surface_min > resolved_surface_max:
        raise ValueError("surface_min cannot exceed surface_max")

    return (
        float(resolved_budget_min),
        float(resolved_budget_max),
        float(resolved_surface_min),
        float(resolved_surface_max),
        resolved_beds_min,
    )


def _prepare_demande_values(data: Mapping[str, object]) -> dict[str, object]:
    now = normalize_timestamp(data.get("created_at")) or utc_now_iso()
    locations_raw = str(data.get("locations") or "")

    type_id = as_optional_int(data.get("type_id"))
    action_id = as_optional_int(data.get("action_id"))
    wilaya_id = as_optional_int(data.get("wilaya_id"))

    if action_id is None or action_id <= 0:
        raise ValueError("action_id is required for demandes")
    if type_id is None or type_id <= 0:
        raise ValueError("type_id is required for demandes")
    if wilaya_id is None or wilaya_id <= 0:
        raise ValueError("wilaya_id is required for demandes")

    bmin = as_optional_float(data.get("budget_min"))
    bmax = as_optional_float(data.get("budget_max"))
    smin = as_optional_float(data.get("surface_min"))
    smax = as_optional_float(data.get("surface_max"))
    bed_min = as_optional_int(data.get("beds_min"))

    resolved_bmin, resolved_bmax, resolved_smin, resolved_smax, resolved_beds_min = (
        _materialize_demande_range_values(
            budget_min=bmin,
            budget_max=bmax,
            surface_min=smin,
            surface_max=smax,
            beds_min=bed_min,
        )
    )

    client_id = as_optional_int(data.get("client_id"))
    if client_id is None or client_id <= 0:
        raise ValueError("client_id is required for demandes")

    return {
        "client_id": client_id,
        "type": str(data.get("type", "")),
        "type_id": type_id,
        "action": str(data.get("action", "")),
        "action_id": action_id,
        "wilaya": str(data.get("wilaya", "")),
        "wilaya_id": wilaya_id,
        "locations": locations_raw,
        "beds_min": resolved_beds_min,
        "surface_min": resolved_smin,
        "surface_max": resolved_smax,
        "budget_min": resolved_bmin,
        "budget_max": resolved_bmax,
        "furnished": str(data.get("furnished", "")),
        "floor_min": data.get("floor_min", 0),
        "floor_max": data.get("floor_max", 100),
        "elevator": 1 if data.get("elevator") else None,
        "accessibility_required": 1 if data.get("accessibility_required") else None,
        "tags": data.get("tags", ""),
        "remarks": data.get("remarks", ""),
        "remarks_enc": data.get("remarks_enc", ""),
        "locations_enc": data.get("locations_enc", ""),
        "created_at": now,
        "updated_at": now,
        "budget_range_start": resolved_bmin,
        "budget_range_end": resolved_bmax,
        "surface_range_start": resolved_smin,
        "surface_range_end": resolved_smax,
        "beds_range_start": resolved_beds_min,
    }


def create_demande(session: DbSession, data: DemandeInput) -> int:
    """Create a new demande. Returns the demande ID."""
    prepared = _prepare_demande_values(data)

    inserted_row = session.execute(
        """
        INSERT INTO demandes
        (agency_id, client_id, type, type_id, action, action_id, wilaya, wilaya_id, locations,
         beds_min, surface_min, surface_max,
         budget_min, budget_max, furnished, floor_min, floor_max, elevator,
         accessibility_required, tags, remarks, remarks_enc, locations_enc, created_at, updated_at,
         budget_range, surface_range, beds_range)
        SELECT
            c.agency_id,
            c.id,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            numrange(%s::numeric, %s::numeric, '[]'),
            numrange(%s::numeric, %s::numeric, '[]'),
            int4range(%s, NULL, '[]')
        FROM clients c
        WHERE c.id = %s
          AND c.deleted_at IS NULL
        RETURNING id, agency_id
    """,
        (
            prepared["type"],
            prepared["type_id"],
            prepared["action"],
            prepared["action_id"],
            prepared["wilaya"],
            prepared["wilaya_id"],
            prepared["locations"],
            prepared["beds_min"],
            prepared["surface_min"],
            prepared["surface_max"],
            prepared["budget_min"],
            prepared["budget_max"],
            prepared["furnished"],
            prepared["floor_min"],
            prepared["floor_max"],
            prepared["elevator"],
            prepared["accessibility_required"],
            prepared["tags"],
            prepared["remarks"],
            prepared["remarks_enc"],
            prepared["locations_enc"],
            prepared["created_at"],
            prepared["updated_at"],
            prepared["budget_range_start"],
            prepared["budget_range_end"],
            prepared["surface_range_start"],
            prepared["surface_range_end"],
            prepared["beds_range_start"],
            prepared["client_id"],
        ),
    ).fetchone()
    demande_id = as_int((inserted_row or {}).get("id"), default=0)
    demande_agency_id = as_int((inserted_row or {}).get("agency_id"), default=0)
    if not demande_id:
        raise NotFoundError("Client not found")

    populate_location_links(
        session,
        entity="demande",
        entity_id=demande_id,
        locations_str=str(prepared["locations"]),
    )
    if demande_agency_id > 0:
        bump_generation(
            session,
            surface=CLIENTS_SURFACE,
            scope_key=agency_scope_key(demande_agency_id),
            agency_id=demande_agency_id,
        )

    logger.debug("Created demande %s for client %s", demande_id, prepared["client_id"])
    return int(demande_id or 0)


def insert_demandes_batch(session: DbSession, rows: Sequence[DemandeInput]) -> list[int]:
    """Insert demandes in one multi-row statement, then populate locations in bulk.

    Returns one new ID per input row in input order.
    """
    if not rows:
        return []

    prepared_rows = [_prepare_demande_values(row) for row in rows]
    value_placeholders: list[str] = []
    params: list[object] = []
    for ordinal, prepared in enumerate(prepared_rows):
        value_placeholders.append(
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        )
        params.extend(
            [
                ordinal,
                prepared["client_id"],
                prepared["type"],
                prepared["type_id"],
                prepared["action"],
                prepared["action_id"],
                prepared["wilaya"],
                prepared["wilaya_id"],
                prepared["locations"],
                prepared["beds_min"],
                prepared["surface_min"],
                prepared["surface_max"],
                prepared["budget_min"],
                prepared["budget_max"],
                prepared["furnished"],
                prepared["floor_min"],
                prepared["floor_max"],
                prepared["elevator"],
                prepared["accessibility_required"],
                prepared["tags"],
                prepared["remarks"],
                prepared["remarks_enc"],
                prepared["locations_enc"],
                prepared["created_at"],
                prepared["updated_at"],
                prepared["budget_range_start"],
                prepared["budget_range_end"],
                prepared["surface_range_start"],
                prepared["surface_range_end"],
                prepared["beds_range_start"],
            ]
        )

    rows_sql = ", ".join(value_placeholders)
    inserted_rows = session.execute(
        f"""
        WITH input_rows (
            ordinal,
            client_id,
            type,
            type_id,
            action,
            action_id,
            wilaya,
            wilaya_id,
            locations,
            beds_min,
            surface_min,
            surface_max,
            budget_min,
            budget_max,
            furnished,
            floor_min,
            floor_max,
            elevator,
            accessibility_required,
            tags,
            remarks,
            remarks_enc,
            locations_enc,
            created_at,
            updated_at,
            budget_range_start,
            budget_range_end,
            surface_range_start,
            surface_range_end,
            beds_range_start
        ) AS (
            VALUES {rows_sql}
        ),
        inserted AS (
            INSERT INTO demandes
            (
                agency_id,
                client_id,
                type,
                type_id,
                action,
                action_id,
                wilaya,
                wilaya_id,
                locations,
                beds_min,
                surface_min,
                surface_max,
                budget_min,
                budget_max,
                furnished,
                floor_min,
                floor_max,
                elevator,
                accessibility_required,
                tags,
                remarks,
                remarks_enc,
                locations_enc,
                created_at,
                updated_at,
                budget_range,
                surface_range,
                beds_range
            )
            SELECT
                c.agency_id,
                c.id,
                i.type,
                i.type_id::bigint,
                i.action,
                i.action_id::bigint,
                i.wilaya,
                i.wilaya_id::bigint,
                i.locations,
                i.beds_min::integer,
                i.surface_min::numeric,
                i.surface_max::numeric,
                i.budget_min::numeric,
                i.budget_max::numeric,
                i.furnished,
                i.floor_min::integer,
                i.floor_max::integer,
                i.elevator::smallint,
                i.accessibility_required::smallint,
                i.tags,
                i.remarks,
                i.remarks_enc,
                i.locations_enc,
                i.created_at::timestamptz,
                i.updated_at::timestamptz,
                numrange(i.budget_range_start::numeric, i.budget_range_end::numeric, '[]'),
                numrange(i.surface_range_start::numeric, i.surface_range_end::numeric, '[]'),
                int4range(i.beds_range_start, NULL, '[]')
            FROM input_rows i
            JOIN clients c ON c.id = i.client_id AND c.deleted_at IS NULL
            ORDER BY i.ordinal
            RETURNING id, client_id, locations, agency_id
        )
        SELECT id, client_id, locations, agency_id FROM inserted
        """,
        params,
    ).fetchall()

    if len(inserted_rows) != len(prepared_rows):
        raise NotFoundError("Client not found")

    location_rows: list[tuple[int | None, str]] = []
    inserted_ids: list[int] = []
    agency_ids: set[int] = set()
    for row in inserted_rows:
        demande_id = as_int(row["id"])
        inserted_ids.append(demande_id)
        location_rows.append((demande_id, str(row.get("locations") or "")))
        agency_id = as_int(row.get("agency_id"), default=0)
        if agency_id > 0:
            agency_ids.add(agency_id)

    populate_location_links_batch(
        session,
        entity="demande",
        entity_locations=location_rows,
        clear_existing=False,
    )
    if agency_ids:
        bump_generations(
            session,
            surface=CLIENTS_SURFACE,
            scopes=[(agency_scope_key(agency_id), agency_id) for agency_id in sorted(agency_ids)],
        )
    return inserted_ids


def insert_demandes_batch_refs(
    session: DbSession,
    rows: Sequence[DemandeInput],
    *,
    source_ordinals: Sequence[int] | None = None,
) -> list[CreatedRowRef]:
    """Insert demandes and return explicit source-to-created id refs."""
    if not rows:
        return []

    prepared_rows = [_prepare_demande_values(row) for row in rows]
    created_rows = _allocate_created_row_refs(
        session,
        table_name="demandes",
        source_ordinals=_normalize_source_ordinals(
            source_ordinals=source_ordinals,
            expected_count=len(prepared_rows),
            context="demande batch insert",
        ),
        context="demande batch insert",
    )
    value_placeholders: list[str] = []
    params: list[object] = []
    for created_row, prepared in zip(created_rows, prepared_rows, strict=True):
        value_placeholders.append(
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        )
        params.extend(
            [
                int(created_row.source_ordinal),
                int(created_row.created_id),
                prepared["client_id"],
                prepared["type"],
                prepared["type_id"],
                prepared["action"],
                prepared["action_id"],
                prepared["wilaya"],
                prepared["wilaya_id"],
                prepared["locations"],
                prepared["beds_min"],
                prepared["surface_min"],
                prepared["surface_max"],
                prepared["budget_min"],
                prepared["budget_max"],
                prepared["furnished"],
                prepared["floor_min"],
                prepared["floor_max"],
                prepared["elevator"],
                prepared["accessibility_required"],
                prepared["tags"],
                prepared["remarks"],
                prepared["remarks_enc"],
                prepared["locations_enc"],
                prepared["created_at"],
                prepared["updated_at"],
                prepared["budget_range_start"],
                prepared["budget_range_end"],
                prepared["surface_range_start"],
                prepared["surface_range_end"],
                prepared["beds_range_start"],
            ]
        )

    rows_sql = ", ".join(value_placeholders)
    inserted_rows = session.execute(
        f"""
        WITH input_rows (
            ordinal,
            assigned_id,
            client_id,
            type,
            type_id,
            action,
            action_id,
            wilaya,
            wilaya_id,
            locations,
            beds_min,
            surface_min,
            surface_max,
            budget_min,
            budget_max,
            furnished,
            floor_min,
            floor_max,
            elevator,
            accessibility_required,
            tags,
            remarks,
            remarks_enc,
            locations_enc,
            created_at,
            updated_at,
            budget_range_start,
            budget_range_end,
            surface_range_start,
            surface_range_end,
            beds_range_start
        ) AS (
            VALUES {rows_sql}
        ),
        inserted AS (
            INSERT INTO demandes
            (
                id,
                agency_id,
                client_id,
                type,
                type_id,
                action,
                action_id,
                wilaya,
                wilaya_id,
                locations,
                beds_min,
                surface_min,
                surface_max,
                budget_min,
                budget_max,
                furnished,
                floor_min,
                floor_max,
                elevator,
                accessibility_required,
                tags,
                remarks,
                remarks_enc,
                locations_enc,
                created_at,
                updated_at,
                budget_range,
                surface_range,
                beds_range
            )
            SELECT
                i.assigned_id::bigint,
                c.agency_id,
                c.id,
                i.type,
                i.type_id::bigint,
                i.action,
                i.action_id::bigint,
                i.wilaya,
                i.wilaya_id::bigint,
                i.locations,
                i.beds_min::integer,
                i.surface_min::numeric,
                i.surface_max::numeric,
                i.budget_min::numeric,
                i.budget_max::numeric,
                i.furnished,
                i.floor_min::integer,
                i.floor_max::integer,
                i.elevator::smallint,
                i.accessibility_required::smallint,
                i.tags,
                i.remarks,
                i.remarks_enc,
                i.locations_enc,
                i.created_at::timestamptz,
                i.updated_at::timestamptz,
                numrange(i.budget_range_start::numeric, i.budget_range_end::numeric, '[]'),
                numrange(i.surface_range_start::numeric, i.surface_range_end::numeric, '[]'),
                int4range(i.beds_range_start, NULL, '[]')
            FROM input_rows i
            JOIN clients c ON c.id = i.client_id AND c.deleted_at IS NULL
            ORDER BY i.ordinal
            RETURNING id, client_id, locations, agency_id
        )
        SELECT id, client_id, locations, agency_id FROM inserted
        """,
        params,
    ).fetchall()

    if len(inserted_rows) != len(prepared_rows):
        raise NotFoundError("Client not found")

    location_rows: list[tuple[int | None, str]] = []
    agency_ids: set[int] = set()
    returned_ids = {as_int(row["id"]) for row in inserted_rows}
    expected_ids = {int(ref.created_id) for ref in created_rows}
    if returned_ids != expected_ids:
        raise ValueError("demande batch insert returned ids that did not match the allocated ids.")
    for row in inserted_rows:
        agency_id = as_int(row.get("agency_id"), default=0)
        if agency_id > 0:
            agency_ids.add(agency_id)
    prepared_by_ordinal = {
        int(created_row.source_ordinal): prepared
        for created_row, prepared in zip(created_rows, prepared_rows, strict=True)
    }
    for created_row in created_rows:
        prepared = prepared_by_ordinal[int(created_row.source_ordinal)]
        location_rows.append((int(created_row.created_id), str(prepared["locations"])))

    populate_location_links_batch(
        session,
        entity="demande",
        entity_locations=location_rows,
        clear_existing=False,
    )
    if agency_ids:
        bump_generations(
            session,
            surface=CLIENTS_SURFACE,
            scopes=[(agency_scope_key(agency_id), agency_id) for agency_id in sorted(agency_ids)],
        )
    return created_rows


def update_demande(session: DbSession, demande_id: int, data: Mapping[str, object]) -> None:
    """Update an existing demande."""
    locations_raw = str(data.get("locations") or "")
    now = normalize_timestamp(data.get("updated_at")) or utc_now_iso()
    row_version = as_int(data.get("row_version"), default=0)
    if row_version <= 0:
        raise ValueError("row_version is required for demande updates")

    type_id = as_optional_int(data.get("type_id"))
    action_id = as_optional_int(data.get("action_id"))
    wilaya_id = as_optional_int(data.get("wilaya_id"))

    if action_id is None or action_id <= 0:
        raise ValueError("action_id is required for demandes")
    if type_id is None or type_id <= 0:
        raise ValueError("type_id is required for demandes")
    if wilaya_id is None or wilaya_id <= 0:
        raise ValueError("wilaya_id is required for demandes")

    bmin = as_optional_float(data.get("budget_min"))
    bmax = as_optional_float(data.get("budget_max"))
    smin = as_optional_float(data.get("surface_min"))
    smax = as_optional_float(data.get("surface_max"))

    bed_min = as_optional_int(data.get("beds_min"))
    bmin_eff, bmax_eff, smin_eff, smax_eff, bed_min_eff = _materialize_demande_range_values(
        budget_min=bmin,
        budget_max=bmax,
        surface_min=smin,
        surface_max=smax,
        beds_min=bed_min,
    )

    updated = session.execute(
        """
        UPDATE demandes SET
            type = %s, type_id = %s, action = %s, action_id = %s, wilaya = %s, wilaya_id = %s,
            locations = %s, beds_min = %s,
            surface_min = %s, surface_max = %s, budget_min = %s, budget_max = %s,
            furnished = %s, floor_min = %s, floor_max = %s, elevator = %s,
            accessibility_required = %s,
            tags = %s, remarks = %s, remarks_enc = %s, locations_enc = %s, updated_at = %s,
            budget_range = numrange(%s::numeric, %s::numeric, '[]'),
            surface_range = numrange(%s::numeric, %s::numeric, '[]'),
            beds_range = int4range(%s, NULL, '[]'),
            row_version = row_version + 1
        WHERE id = %s AND deleted_at IS NULL AND row_version = %s
        RETURNING agency_id
    """,
        (
            str(data.get("type", "")),
            type_id,
            str(data.get("action", "")),
            action_id,
            str(data.get("wilaya", "")),
            wilaya_id,
            locations_raw,
            bed_min_eff,
            smin_eff,
            smax_eff,
            bmin_eff,
            bmax_eff,
            str(data.get("furnished", "")),
            data.get("floor_min", 0),
            data.get("floor_max", 100),
            1 if data.get("elevator") else None,
            1 if data.get("accessibility_required") else None,
            data.get("tags", ""),
            data.get("remarks", ""),
            data.get("remarks_enc", ""),
            data.get("locations_enc", ""),
            now,
            bmin_eff,
            bmax_eff,
            smin_eff,
            smax_eff,
            bed_min_eff,
            demande_id,
            row_version,
        ),
    ).fetchone()
    if not updated:
        row = session.execute("SELECT * FROM demandes WHERE id = %s", (demande_id,)).fetchone()
        if row and row.get("deleted_at") is None:
            raise ConflictError("Demande was updated by another user.")
        raise NotFoundError("Demande not found")

    populate_location_links(
        session, entity="demande", entity_id=demande_id, locations_str=locations_raw
    )
    updated_agency_id = as_int(updated.get("agency_id"), default=0)
    if updated_agency_id > 0:
        bump_generation(
            session,
            surface=CLIENTS_SURFACE,
            scope_key=agency_scope_key(updated_agency_id),
            agency_id=updated_agency_id,
        )
