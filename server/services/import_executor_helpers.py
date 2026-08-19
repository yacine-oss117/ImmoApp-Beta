"""Helper functions shared by import executor paths."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from core.data import client_repo_write as client_write
from core.data import demande_repo_write as demande_write
from core.data import listing_repo_write as listing_write
from core.data import offer_repo_write as offer_write
from core.data.match_cache import mark_client_dirty, mark_clients_in_wilaya_dirty
from core.data.types import DemandeInput, OfferInput
from server.pg.lookup_resolver import resolve_lookup_fields
from server.services.demandes import _enforce_strict_demande_fields
from server.services.import_constants import (
    ENTITY_TYPE_CLIENT,
    ENTITY_TYPE_DEMANDE,
    ENTITY_TYPE_LISTING,
    ENTITY_TYPE_OFFER,
)
from server.services.import_review_duplicates import append_db_duplicate_reviews
from server.services.import_rows import (
    normalize_client_batch,
    normalize_demande_batch,
    normalize_listing_batch,
    normalize_offer_batch,
)
from server.services.offers import _enforce_required_offer_fields

LookupCache = dict[tuple[object, ...], dict[str, object]]


def _lookup_cache_key(row: Mapping[str, object]) -> tuple[object, ...]:
    return (
        row.get("type_id"),
        str(row.get("type", "") or "").strip().lower(),
        row.get("action_id"),
        str(row.get("action", "") or "").strip().lower(),
        row.get("wilaya_id"),
        str(row.get("wilaya", "") or "").strip().lower(),
    )


def _resolve_lookup_fields_cached(
    session: Any,
    row: Mapping[str, object],
    *,
    cache: LookupCache,
) -> dict[str, object]:
    key = _lookup_cache_key(row)
    cached = cache.get(key)
    if cached is not None:
        resolved = dict(row)
        resolved.update(cached)
        return resolved
    resolved = resolve_lookup_fields(session, row)
    cache[key] = {
        "type_id": resolved.get("type_id"),
        "type": resolved.get("type"),
        "action_id": resolved.get("action_id"),
        "action": resolved.get("action"),
        "wilaya_id": resolved.get("wilaya_id"),
        "wilaya": resolved.get("wilaya"),
    }
    return resolved


def collect_listing_wilaya_ids(row: Mapping[str, object], target: set[int]) -> None:
    wilaya_raw = row.get("wilaya_id")
    if isinstance(wilaya_raw, int) and wilaya_raw > 0:
        target.add(wilaya_raw)
        return
    if isinstance(wilaya_raw, str) and wilaya_raw.strip().isdigit():
        value = int(wilaya_raw.strip())
        if value > 0:
            target.add(value)


def _as_demande_write_input(row: Mapping[str, object]) -> DemandeInput:
    return cast(DemandeInput, dict(row))


def _as_offer_write_input(row: Mapping[str, object]) -> OfferInput:
    return cast(OfferInput, dict(row))


def insert_batch(
    *,
    write_session: Any,
    entity_type: str,
    batch_rows: list[dict[str, Any]],
    demande_ids: set[int] | None = None,
    demande_client_ids: set[int] | None = None,
    offer_ids: set[int] | None = None,
    listing_wilaya_ids: set[int] | None = None,
) -> list[int]:
    if not batch_rows:
        return []

    if entity_type == ENTITY_TYPE_CLIENT:
        normalized_clients = normalize_client_batch(batch_rows)
        batch_ids = client_write.insert_clients_batch(write_session, normalized_clients)
        for obj_id in batch_ids:
            mark_client_dirty(write_session, obj_id)
        return batch_ids

    if entity_type == ENTITY_TYPE_LISTING:
        normalized_listings = normalize_listing_batch(batch_rows)
        return listing_write.insert_listings_batch(write_session, normalized_listings)

    if entity_type == ENTITY_TYPE_DEMANDE:
        normalized_demandes = normalize_demande_batch(batch_rows)
        demande_lookup_cache: LookupCache = {}
        resolved_demandes: list[DemandeInput] = []
        dirty_client_ids: set[int] = set()
        for demande_row in normalized_demandes:
            resolved_demande = _resolve_lookup_fields_cached(
                write_session,
                demande_row,
                cache=demande_lookup_cache,
            )
            _enforce_strict_demande_fields(resolved_demande)
            resolved_demande_input = _as_demande_write_input(resolved_demande)
            resolved_demandes.append(resolved_demande_input)
            client_id = int(resolved_demande_input["client_id"])
            dirty_client_ids.add(client_id)
            if demande_client_ids is not None:
                demande_client_ids.add(client_id)
        inserted_ids = demande_write.insert_demandes_batch(write_session, resolved_demandes)
        if demande_ids is not None:
            demande_ids.update(inserted_ids)
        for client_id in sorted(dirty_client_ids):
            mark_client_dirty(write_session, client_id)
        return inserted_ids

    if entity_type == ENTITY_TYPE_OFFER:
        normalized_offers = normalize_offer_batch(batch_rows)
        offer_lookup_cache: LookupCache = {}
        resolved_offers: list[OfferInput] = []
        dirty_wilaya_ids: set[int] = set()
        for offer_row in normalized_offers:
            resolved_offer = _resolve_lookup_fields_cached(
                write_session,
                offer_row,
                cache=offer_lookup_cache,
            )
            _enforce_required_offer_fields(resolved_offer)
            resolved_offers.append(_as_offer_write_input(resolved_offer))
            wilaya_id = resolved_offer.get("wilaya_id")
            if isinstance(wilaya_id, int) and wilaya_id > 0:
                dirty_wilaya_ids.add(wilaya_id)
                if listing_wilaya_ids is not None:
                    listing_wilaya_ids.add(wilaya_id)
        inserted_ids = offer_write.insert_offers_batch(write_session, resolved_offers)
        if offer_ids is not None:
            offer_ids.update(inserted_ids)
        for wilaya_id in sorted(dirty_wilaya_ids):
            mark_clients_in_wilaya_dirty(write_session, wilaya_id)
        return inserted_ids

    raise ValueError(f"Unsupported entity_type: {entity_type}")


__all__ = [
    "append_db_duplicate_reviews",
    "collect_listing_wilaya_ids",
    "insert_batch",
]
