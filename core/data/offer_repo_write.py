from __future__ import annotations

from collections.abc import Mapping, Sequence

from core.contracts.import_batch_refs import CreatedRowRef
from core.data.errors import NotFoundError
from core.data.location_junctions import populate_location_links, populate_location_links_batch
from core.data.surface_cache_generation import (
    LISTINGS_SURFACE,
    agency_scope_key,
    bump_generation,
    bump_generations,
)
from core.data.types import OfferInput
from core.matcher.ports.db import DbSession
from core.models_cast import as_int, as_optional_float, null_if_zero
from core.utils.time import normalize_timestamp, utc_now_iso


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


def _first_row(result: object) -> dict[str, object] | None:
    fetchone = getattr(result, "fetchone", None)
    if callable(fetchone):
        row = fetchone()
        if row is None:
            return None
        return dict(row)

    fetchall = getattr(result, "fetchall", None)
    if callable(fetchall):
        rows = fetchall()
        if not rows:
            return None
        return dict(rows[0])

    return None


def _flex_ratio(price_flex_pct: object) -> float:
    flex_pct = as_optional_float(price_flex_pct) or 0.0
    return max(0.0, flex_pct) / 100.0


def _prepare_offer_values(listing_id: int, data: Mapping[str, object]) -> dict[str, object]:
    now = normalize_timestamp(data.get("created_at")) or utc_now_iso()
    raw_location = str(data.get("location") or "")
    type_id = null_if_zero(as_int(data.get("type_id")))
    action_id = null_if_zero(as_int(data.get("action_id")))
    wilaya_id = null_if_zero(as_int(data.get("wilaya_id")))
    budget = as_int(data.get("budget"), 0)
    flex_pct = as_optional_float(data.get("price_flex_pct")) or 0.0
    negotiable = bool(data.get("price_negotiable")) or flex_pct > 0

    if type_id is None:
        raise ValueError("type_id is required for offers")
    if action_id is None:
        raise ValueError("action_id is required for offers")
    if wilaya_id is None:
        raise ValueError("wilaya_id is required for offers")
    if raw_location == "":
        raise ValueError("location is required for offers")
    if data.get("beds") is None:
        raise ValueError("beds is required for offers")
    if data.get("surface") is None:
        raise ValueError("surface is required for offers")
    if budget <= 0:
        raise ValueError("budget is required for offers")
    if data.get("floor") is None:
        raise ValueError("floor is required for offers")

    return {
        "listing_id": int(listing_id),
        "type": str(data.get("type", "")),
        "type_id": type_id,
        "action": str(data.get("action", "")),
        "action_id": action_id,
        "status": str(data.get("status", "available")),
        "wilaya": str(data.get("wilaya", "")),
        "wilaya_id": wilaya_id,
        "location": raw_location,
        "beds": data.get("beds", 0),
        "surface": data.get("surface", 0),
        "budget": budget,
        "furnished": str(data.get("furnished", "")),
        "floor": data.get("floor", 0),
        "elevator": 1 if data.get("elevator") else 0,
        "accessibility_supported": 1 if data.get("accessibility_supported") else 0,
        "link": data.get("link", ""),
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "remarks": data.get("remarks", ""),
        "remarks_enc": data.get("remarks_enc", ""),
        "location_enc": data.get("location_enc", ""),
        "created_at": now,
        "updated_at": now,
        "price_negotiable": 1 if negotiable else 0,
        "price_flex_pct": flex_pct,
    }


def create_offer(session: DbSession, listing_id: int, data: OfferInput) -> int:
    """Create a new offer for a listing."""
    prepared = _prepare_offer_values(listing_id, data)

    inserted_row = _first_row(
        session.execute(
            """
        INSERT INTO offers
        (agency_id, listing_id, type, type_id, action, action_id, status, wilaya, wilaya_id, location, beds,
         surface, budget, furnished, floor, elevator, accessibility_supported, link, latitude, longitude, remarks, remarks_enc, location_enc,
         created_at, updated_at, price_negotiable, price_flex_pct, price_range)
        SELECT
            l.agency_id,
            l.id,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            numrange((%s * (1 - %s))::numeric, (%s * (1 + %s))::numeric, '[]')
        FROM listings l
        WHERE l.id = %s
          AND l.deleted_at IS NULL
        RETURNING id, agency_id
    """,
            (
                prepared["type"],
                prepared["type_id"],
                prepared["action"],
                prepared["action_id"],
                prepared["status"],
                prepared["wilaya"],
                prepared["wilaya_id"],
                prepared["location"],
                prepared["beds"],
                prepared["surface"],
                prepared["budget"],
                prepared["furnished"],
                prepared["floor"],
                prepared["elevator"],
                prepared["accessibility_supported"],
                prepared["link"],
                prepared["latitude"],
                prepared["longitude"],
                prepared["remarks"],
                prepared["remarks_enc"],
                prepared["location_enc"],
                prepared["created_at"],
                prepared["updated_at"],
                prepared["price_negotiable"],
                prepared["price_flex_pct"],
                prepared["budget"],
                _flex_ratio(prepared["price_flex_pct"]),
                prepared["budget"],
                _flex_ratio(prepared["price_flex_pct"]),
                prepared["listing_id"],
            ),
        )
    )
    offer_id = as_int(
        (inserted_row or {}).get("id"),
        default=as_int(getattr(session, "lastrowid", None), default=0),
    )
    offer_agency_id = as_int((inserted_row or {}).get("agency_id"), default=0)
    if not offer_id:
        raise NotFoundError("Listing not found")

    populate_location_links(
        session,
        entity="offer",
        entity_id=offer_id,
        locations_str=str(prepared["location"]),
    )
    if offer_agency_id > 0:
        bump_generation(
            session,
            surface=LISTINGS_SURFACE,
            scope_key=agency_scope_key(offer_agency_id),
            agency_id=offer_agency_id,
        )

    return int(offer_id or 0)


def insert_offers_batch(session: DbSession, rows: Sequence[OfferInput]) -> list[int]:
    """Insert offers in one multi-row statement, then populate locations in bulk.

    Returns one new ID per input row in input order.
    """
    if not rows:
        return []

    prepared_rows = [_prepare_offer_values(as_int(row["listing_id"]), row) for row in rows]
    value_placeholders: list[str] = []
    params: list[object] = []
    for ordinal, prepared in enumerate(prepared_rows):
        value_placeholders.append(
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        )
        params.extend(
            [
                ordinal,
                prepared["listing_id"],
                prepared["type"],
                prepared["type_id"],
                prepared["action"],
                prepared["action_id"],
                prepared["status"],
                prepared["wilaya"],
                prepared["wilaya_id"],
                prepared["location"],
                prepared["beds"],
                prepared["surface"],
                prepared["budget"],
                prepared["furnished"],
                prepared["floor"],
                prepared["elevator"],
                prepared["accessibility_supported"],
                prepared["link"],
                prepared["latitude"],
                prepared["longitude"],
                prepared["remarks"],
                prepared["remarks_enc"],
                prepared["location_enc"],
                prepared["created_at"],
                prepared["updated_at"],
                prepared["price_negotiable"],
                prepared["price_flex_pct"],
            ]
        )

    rows_sql = ", ".join(value_placeholders)
    inserted_rows = session.execute(
        f"""
        WITH input_rows (
            ordinal,
            listing_id,
            type,
            type_id,
            action,
            action_id,
            status,
            wilaya,
            wilaya_id,
            location,
            beds,
            surface,
            budget,
            furnished,
            floor,
            elevator,
            accessibility_supported,
            link,
            latitude,
            longitude,
            remarks,
            remarks_enc,
            location_enc,
            created_at,
            updated_at,
            price_negotiable,
            price_flex_pct
        ) AS (
            VALUES {rows_sql}
        ),
        inserted AS (
            INSERT INTO offers
            (
                agency_id,
                listing_id,
                type,
                type_id,
                action,
                action_id,
                status,
                wilaya,
                wilaya_id,
                location,
                beds,
                surface,
                budget,
                furnished,
                floor,
                elevator,
                accessibility_supported,
                link,
                latitude,
                longitude,
                remarks,
                remarks_enc,
                location_enc,
                created_at,
                updated_at,
                price_negotiable,
                price_flex_pct,
                price_range
            )
            SELECT
                l.agency_id,
                l.id,
                i.type,
                i.type_id::bigint,
                i.action,
                i.action_id::bigint,
                i.status,
                i.wilaya,
                i.wilaya_id::bigint,
                i.location,
                i.beds::integer,
                i.surface::numeric,
                i.budget::numeric,
                i.furnished,
                i.floor::integer,
                i.elevator::smallint,
                i.accessibility_supported::smallint,
                i.link,
                i.latitude::double precision,
                i.longitude::double precision,
                i.remarks,
                i.remarks_enc,
                i.location_enc,
                i.created_at::timestamptz,
                i.updated_at::timestamptz,
                i.price_negotiable::smallint,
                i.price_flex_pct::double precision,
                numrange(
                    (i.budget::numeric * (1 - (i.price_flex_pct::double precision / 100.0)))::numeric,
                    (i.budget::numeric * (1 + (i.price_flex_pct::double precision / 100.0)))::numeric,
                    '[]'
                )
            FROM input_rows i
            JOIN listings l ON l.id = i.listing_id AND l.deleted_at IS NULL
            ORDER BY i.ordinal
            RETURNING id, wilaya_id, location, agency_id
        )
        SELECT id, wilaya_id, location, agency_id FROM inserted
        """,
        params,
    ).fetchall()

    if len(inserted_rows) != len(prepared_rows):
        raise NotFoundError("Listing not found")

    location_rows: list[tuple[int | None, str]] = []
    inserted_ids: list[int] = []
    agency_ids: set[int] = set()
    for row in inserted_rows:
        offer_id = as_int(row["id"])
        inserted_ids.append(offer_id)
        location_rows.append((offer_id, str(row.get("location") or "")))
        agency_id = as_int(row.get("agency_id"), default=0)
        if agency_id > 0:
            agency_ids.add(agency_id)

    populate_location_links_batch(
        session,
        entity="offer",
        entity_locations=location_rows,
        clear_existing=False,
    )
    if agency_ids:
        bump_generations(
            session,
            surface=LISTINGS_SURFACE,
            scopes=[(agency_scope_key(agency_id), agency_id) for agency_id in sorted(agency_ids)],
        )
    return inserted_ids


def insert_offers_batch_refs(
    session: DbSession,
    rows: Sequence[OfferInput],
    *,
    source_ordinals: Sequence[int] | None = None,
) -> list[CreatedRowRef]:
    """Insert offers and return explicit source-to-created id refs."""
    if not rows:
        return []

    prepared_rows = [_prepare_offer_values(as_int(row["listing_id"]), row) for row in rows]
    created_rows = _allocate_created_row_refs(
        session,
        table_name="offers",
        source_ordinals=_normalize_source_ordinals(
            source_ordinals=source_ordinals,
            expected_count=len(prepared_rows),
            context="offer batch insert",
        ),
        context="offer batch insert",
    )
    value_placeholders: list[str] = []
    params: list[object] = []
    for created_row, prepared in zip(created_rows, prepared_rows, strict=True):
        value_placeholders.append(
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        )
        params.extend(
            [
                int(created_row.source_ordinal),
                int(created_row.created_id),
                prepared["listing_id"],
                prepared["type"],
                prepared["type_id"],
                prepared["action"],
                prepared["action_id"],
                prepared["status"],
                prepared["wilaya"],
                prepared["wilaya_id"],
                prepared["location"],
                prepared["beds"],
                prepared["surface"],
                prepared["budget"],
                prepared["furnished"],
                prepared["floor"],
                prepared["elevator"],
                prepared["accessibility_supported"],
                prepared["link"],
                prepared["latitude"],
                prepared["longitude"],
                prepared["remarks"],
                prepared["remarks_enc"],
                prepared["location_enc"],
                prepared["created_at"],
                prepared["updated_at"],
                prepared["price_negotiable"],
                prepared["price_flex_pct"],
            ]
        )

    rows_sql = ", ".join(value_placeholders)
    inserted_rows = session.execute(
        f"""
        WITH input_rows (
            ordinal,
            assigned_id,
            listing_id,
            type,
            type_id,
            action,
            action_id,
            status,
            wilaya,
            wilaya_id,
            location,
            beds,
            surface,
            budget,
            furnished,
            floor,
            elevator,
            accessibility_supported,
            link,
            latitude,
            longitude,
            remarks,
            remarks_enc,
            location_enc,
            created_at,
            updated_at,
            price_negotiable,
            price_flex_pct
        ) AS (
            VALUES {rows_sql}
        ),
        inserted AS (
            INSERT INTO offers
            (
                id,
                agency_id,
                listing_id,
                type,
                type_id,
                action,
                action_id,
                status,
                wilaya,
                wilaya_id,
                location,
                beds,
                surface,
                budget,
                furnished,
                floor,
                elevator,
                accessibility_supported,
                link,
                latitude,
                longitude,
                remarks,
                remarks_enc,
                location_enc,
                created_at,
                updated_at,
                price_negotiable,
                price_flex_pct,
                price_range
            )
            SELECT
                i.assigned_id::bigint,
                l.agency_id,
                l.id,
                i.type,
                i.type_id::bigint,
                i.action,
                i.action_id::bigint,
                i.status,
                i.wilaya,
                i.wilaya_id::bigint,
                i.location,
                i.beds::integer,
                i.surface::numeric,
                i.budget::numeric,
                i.furnished,
                i.floor::integer,
                i.elevator::smallint,
                i.accessibility_supported::smallint,
                i.link,
                i.latitude::double precision,
                i.longitude::double precision,
                i.remarks,
                i.remarks_enc,
                i.location_enc,
                i.created_at::timestamptz,
                i.updated_at::timestamptz,
                i.price_negotiable::smallint,
                i.price_flex_pct::double precision,
                numrange(
                    (i.budget::numeric * (1 - (i.price_flex_pct::double precision / 100.0)))::numeric,
                    (i.budget::numeric * (1 + (i.price_flex_pct::double precision / 100.0)))::numeric,
                    '[]'
                )
            FROM input_rows i
            JOIN listings l ON l.id = i.listing_id AND l.deleted_at IS NULL
            ORDER BY i.ordinal
            RETURNING id, wilaya_id, location, agency_id
        )
        SELECT id, wilaya_id, location, agency_id FROM inserted
        """,
        params,
    ).fetchall()

    if len(inserted_rows) != len(prepared_rows):
        raise NotFoundError("Listing not found")

    location_rows: list[tuple[int | None, str]] = []
    agency_ids: set[int] = set()
    returned_ids = {as_int(row["id"]) for row in inserted_rows}
    expected_ids = {int(ref.created_id) for ref in created_rows}
    if returned_ids != expected_ids:
        raise ValueError("offer batch insert returned ids that did not match the allocated ids.")
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
        location_rows.append((int(created_row.created_id), str(prepared["location"])))

    populate_location_links_batch(
        session,
        entity="offer",
        entity_locations=location_rows,
        clear_existing=False,
    )
    if agency_ids:
        bump_generations(
            session,
            surface=LISTINGS_SURFACE,
            scopes=[(agency_scope_key(agency_id), agency_id) for agency_id in sorted(agency_ids)],
        )
    return created_rows


def update_offer(session: DbSession, offer_id: int, data: OfferInput) -> None:
    """Update an existing offer."""
    raw_location = str(data.get("location") or "")
    row_version = as_int(data.get("row_version"), default=0)
    if row_version <= 0:
        raise ValueError("row_version is required for offer updates")

    type_id = null_if_zero(as_int(data.get("type_id")))
    action_id = null_if_zero(as_int(data.get("action_id")))
    wilaya_id = null_if_zero(as_int(data.get("wilaya_id")))
    budget = as_int(data.get("budget"), 0)
    flex_pct = as_optional_float(data.get("price_flex_pct")) or 0.0
    negotiable = bool(data.get("price_negotiable")) or flex_pct > 0

    if type_id is None:
        raise ValueError("type_id is required for offers")
    if action_id is None:
        raise ValueError("action_id is required for offers")
    if wilaya_id is None:
        raise ValueError("wilaya_id is required for offers")
    if raw_location == "":
        raise ValueError("location is required for offers")
    if data.get("beds") is None:
        raise ValueError("beds is required for offers")
    if data.get("surface") is None:
        raise ValueError("surface is required for offers")
    if budget <= 0:
        raise ValueError("budget is required for offers")
    if data.get("floor") is None:
        raise ValueError("floor is required for offers")

    updated = session.execute(
        """
        UPDATE offers SET
            type = %s, type_id = %s, action = %s, action_id = %s, status = %s, wilaya = %s, wilaya_id = %s,
            location = %s, beds = %s,
            surface = %s, budget = %s, furnished = %s, floor = %s, elevator = %s,
            accessibility_supported = %s,
            link = %s, latitude = %s, longitude = %s, remarks = %s, remarks_enc = %s, location_enc = %s, updated_at = %s,
            price_negotiable = %s, price_flex_pct = %s,
            price_range = numrange((%s * (1 - %s))::numeric, (%s * (1 + %s))::numeric, '[]'),
            row_version = row_version + 1
        WHERE id = %s AND deleted_at IS NULL AND row_version = %s
        RETURNING agency_id
    """,
        (
            str(data.get("type", "")),
            type_id,
            str(data.get("action", "")),
            action_id,
            str(data.get("status", "available")),
            str(data.get("wilaya", "")),
            wilaya_id,
            raw_location,
            data.get("beds", 0),
            data.get("surface", 0),
            budget,
            str(data.get("furnished", "")),
            data.get("floor", 0),
            1 if data.get("elevator") else 0,
            1 if data.get("accessibility_supported") else 0,
            data.get("link", ""),
            data.get("latitude"),
            data.get("longitude"),
            data.get("remarks", ""),
            data.get("remarks_enc", ""),
            data.get("location_enc", ""),
            normalize_timestamp(data.get("updated_at")) or utc_now_iso(),
            1 if negotiable else 0,
            flex_pct,
            budget,
            _flex_ratio(flex_pct),
            budget,
            _flex_ratio(flex_pct),
            offer_id,
            row_version,
        ),
    ).fetchone()
    if not updated:
        raise NotFoundError("Offer not found or conflict")

    populate_location_links(session, entity="offer", entity_id=offer_id, locations_str=raw_location)
    updated_agency_id = as_int(updated.get("agency_id"), default=0)
    if updated_agency_id > 0:
        bump_generation(
            session,
            surface=LISTINGS_SURFACE,
            scope_key=agency_scope_key(updated_agency_id),
            agency_id=updated_agency_id,
        )


def delete_offer(session: DbSession, offer_id: int) -> None:
    now = utc_now_iso()
    deleted = session.execute(
        "UPDATE offers SET deleted_at = %s, updated_at = %s WHERE id = %s RETURNING agency_id",
        (now, now, offer_id),
    ).fetchone()
    deleted_agency_id = as_int((deleted or {}).get("agency_id"), default=0)
    if deleted_agency_id > 0:
        bump_generation(
            session,
            surface=LISTINGS_SURFACE,
            scope_key=agency_scope_key(deleted_agency_id),
            agency_id=deleted_agency_id,
        )


def restore_offer(session: DbSession, offer_id: int) -> None:
    restored = session.execute(
        "UPDATE offers SET deleted_at = NULL, updated_at = %s WHERE id = %s RETURNING agency_id",
        (utc_now_iso(), offer_id),
    ).fetchone()
    restored_agency_id = as_int((restored or {}).get("agency_id"), default=0)
    if restored_agency_id > 0:
        bump_generation(
            session,
            surface=LISTINGS_SURFACE,
            scope_key=agency_scope_key(restored_agency_id),
            agency_id=restored_agency_id,
        )


def purge_offer(session: DbSession, offer_id: int) -> None:
    purged = session.execute(
        "DELETE FROM offers WHERE id = %s RETURNING agency_id",
        (offer_id,),
    ).fetchone()
    purged_agency_id = as_int((purged or {}).get("agency_id"), default=0)
    if purged_agency_id > 0:
        bump_generation(
            session,
            surface=LISTINGS_SURFACE,
            scope_key=agency_scope_key(purged_agency_id),
            agency_id=purged_agency_id,
        )
