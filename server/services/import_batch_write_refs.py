"""Importer-only identity-aware batch write seam."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from core.contracts.import_batch_refs import CreatedRowRef
from core.data import client_repo_write as client_write
from core.data import demande_repo_write as demande_write
from core.data import listing_repo_write as listing_write
from core.data import offer_repo_write as offer_write
from core.data.match_cache import mark_client_dirty, mark_clients_in_wilaya_dirty
from server.services.demandes import _enforce_strict_demande_fields
from server.services.import_constants import (
    ENTITY_TYPE_CLIENT,
    ENTITY_TYPE_DEMANDE,
    ENTITY_TYPE_LISTING,
    ENTITY_TYPE_OFFER,
)
from server.services.import_executor_helpers import (
    LookupCache,
    _as_demande_write_input,
    _as_offer_write_input,
    _resolve_lookup_fields_cached,
)
from server.services.import_rows import (
    normalize_client_batch,
    normalize_demande_batch,
    normalize_listing_batch,
    normalize_offer_batch,
)
from server.services.offers import _enforce_required_offer_fields


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
            f"{int(expected_count)} batch rows."
        )
    if any(value < 0 for value in normalized):
        raise ValueError(f"{context} requires non-negative source ordinals.")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{context} requires unique source ordinals.")
    return normalized


def _require_created_row_refs(
    *,
    created_rows: Sequence[CreatedRowRef],
    expected_source_ordinals: Sequence[int],
    context: str,
) -> list[CreatedRowRef]:
    normalized = [
        CreatedRowRef(
            source_ordinal=int(ref.source_ordinal),
            created_id=int(ref.created_id),
        )
        for ref in created_rows
    ]
    if len(normalized) != len(expected_source_ordinals):
        raise ValueError(
            f"{context} returned {len(normalized)} created-row refs for "
            f"{len(expected_source_ordinals)} batch rows."
        )
    actual_ordinals = [ref.source_ordinal for ref in normalized]
    if any(ref.created_id <= 0 for ref in normalized):
        raise ValueError(f"{context} returned a non-positive created id.")
    if any(ordinal < 0 for ordinal in actual_ordinals):
        raise ValueError(f"{context} returned a negative source ordinal.")
    if len(set(actual_ordinals)) != len(actual_ordinals):
        raise ValueError(f"{context} returned duplicate source ordinals.")
    if set(actual_ordinals) != {int(value) for value in expected_source_ordinals}:
        raise ValueError(f"{context} returned source ordinals that did not match the batch.")
    return normalized


def insert_batch_refs(
    *,
    write_session: Any,
    entity_type: str,
    batch_rows: list[dict[str, Any]],
    source_ordinals: Sequence[int] | None = None,
    demande_ids: set[int] | None = None,
    demande_client_ids: set[int] | None = None,
    offer_ids: set[int] | None = None,
    listing_wilaya_ids: set[int] | None = None,
) -> list[CreatedRowRef]:
    if not batch_rows:
        return []

    expected_source_ordinals = _normalize_source_ordinals(
        source_ordinals=source_ordinals,
        expected_count=len(batch_rows),
        context=f"{entity_type} batch insert",
    )

    if entity_type == ENTITY_TYPE_CLIENT:
        normalized_clients = normalize_client_batch(batch_rows)
        created_rows = _require_created_row_refs(
            created_rows=client_write.insert_clients_batch_refs(
                write_session,
                normalized_clients,
                source_ordinals=expected_source_ordinals,
            ),
            expected_source_ordinals=expected_source_ordinals,
            context="client batch insert",
        )
        for created_row in created_rows:
            mark_client_dirty(write_session, int(created_row.created_id))
        return created_rows

    if entity_type == ENTITY_TYPE_LISTING:
        normalized_listings = normalize_listing_batch(batch_rows)
        return _require_created_row_refs(
            created_rows=listing_write.insert_listings_batch_refs(
                write_session,
                normalized_listings,
                source_ordinals=expected_source_ordinals,
            ),
            expected_source_ordinals=expected_source_ordinals,
            context="listing batch insert",
        )

    if entity_type == ENTITY_TYPE_DEMANDE:
        normalized_demandes = normalize_demande_batch(batch_rows)
        demande_lookup_cache: LookupCache = {}
        resolved_demandes = []
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
        created_rows = _require_created_row_refs(
            created_rows=demande_write.insert_demandes_batch_refs(
                write_session,
                resolved_demandes,
                source_ordinals=expected_source_ordinals,
            ),
            expected_source_ordinals=expected_source_ordinals,
            context="demande batch insert",
        )
        if demande_ids is not None:
            demande_ids.update(int(ref.created_id) for ref in created_rows)
        for client_id in sorted(dirty_client_ids):
            mark_client_dirty(write_session, client_id)
        return created_rows

    if entity_type == ENTITY_TYPE_OFFER:
        normalized_offers = normalize_offer_batch(batch_rows)
        offer_lookup_cache: LookupCache = {}
        resolved_offers = []
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
        created_rows = _require_created_row_refs(
            created_rows=offer_write.insert_offers_batch_refs(
                write_session,
                resolved_offers,
                source_ordinals=expected_source_ordinals,
            ),
            expected_source_ordinals=expected_source_ordinals,
            context="offer batch insert",
        )
        if offer_ids is not None:
            offer_ids.update(int(ref.created_id) for ref in created_rows)
        for wilaya_id in sorted(dirty_wilaya_ids):
            mark_clients_in_wilaya_dirty(write_session, wilaya_id)
        return created_rows

    raise ValueError(f"Unsupported entity_type: {entity_type}")
