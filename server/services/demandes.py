"""
Postgres-backed demande operations with validation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.data import demande_repo_read as read
from core.data import demande_repo_write as write
from core.data.match_cache import mark_client_dirty
from core.models import Demande
from core.models_cast import as_int
from core.utils.common import coerce_number, ensure_min_le_max, norm_text
from server.pg.lookup_resolver import resolve_lookup_fields
from server.pg.uow import get_uow

from .ale_policy import DEMANDE_ALE_POLICIES
from .match_jobs import enqueue_rebuild_demande_pairs


def create_demande(
    client_id: int,
    input_data: Mapping[str, object],
    *,
    actor: str | None = None,
) -> int:
    """Create a new demande for a client."""
    from .clients import get_client_by_id

    client = get_client_by_id(client_id)
    if not client:
        raise ValueError(f"Client {client_id} not found")

    processed = _normalize_demande_data(input_data)
    processed["client_id"] = client_id
    with get_uow().transaction(actor=actor) as session:
        processed = resolve_lookup_fields(session, processed)
        _enforce_strict_demande_fields(processed)
        demande_id = write.create_demande(session, processed)
        mark_client_dirty(session, client_id)
        if demande_id:
            session.on_commit(
                lambda resolved_demande_id=int(demande_id): enqueue_rebuild_demande_pairs(
                    resolved_demande_id
                )
            )
    return int(demande_id or 0)


def update_demande(
    demande_id: int,
    input_data: Mapping[str, object],
    *,
    actor: str | None = None,
) -> None:
    """Validate and update an existing demande."""
    existing = get_demande_by_id(demande_id)
    processed = _normalize_demande_data(input_data, existing=existing)
    with get_uow().transaction(actor=actor) as session:
        processed = resolve_lookup_fields(session, processed)
        _enforce_strict_demande_fields(processed)
        write.update_demande(session, demande_id, processed)
        demande = read.get_demande_by_id(session, demande_id, include_deleted=False)
        if demande:
            mark_client_dirty(session, demande.client_id)
        session.on_commit(
            lambda resolved_demande_id=int(demande_id): enqueue_rebuild_demande_pairs(
                resolved_demande_id
            )
        )


def delete_demande(demande_id: int, *, actor: str | None = None) -> None:
    """Soft-delete a demande and mark the parent client's matching cache as dirty."""
    with get_uow().transaction(actor=actor) as session:
        demande = read.get_demande_by_id(session, demande_id, include_deleted=False)
        write.delete_demande(session, demande_id)
        if demande:
            mark_client_dirty(session, demande.client_id)
        session.on_commit(
            lambda resolved_demande_id=int(demande_id): enqueue_rebuild_demande_pairs(
                resolved_demande_id
            )
        )


def restore_demande(demande_id: int, *, actor: str | None = None) -> None:
    """Restore a soft-deleted demande."""
    with get_uow().transaction(actor=actor) as session:
        write.restore_demande(session, demande_id)
        demande = read.get_demande_by_id(session, demande_id, include_deleted=False)
        if demande:
            mark_client_dirty(session, demande.client_id)
        session.on_commit(
            lambda resolved_demande_id=int(demande_id): enqueue_rebuild_demande_pairs(
                resolved_demande_id
            )
        )


def purge_demande(demande_id: int, *, actor: str | None = None) -> None:
    """Permanently delete a demande."""
    with get_uow().transaction(actor=actor) as session:
        demande = read.get_demande_by_id(session, demande_id, include_deleted=True)
        write.purge_demande(session, demande_id)
        if demande:
            mark_client_dirty(session, demande.client_id)
        session.on_commit(
            lambda resolved_demande_id=int(demande_id): enqueue_rebuild_demande_pairs(
                resolved_demande_id
            )
        )


def get_demande_by_id(demande_id: int, *, include_deleted: bool = False) -> Demande | None:
    """Retrieve a single demande by ID."""
    with get_uow().session() as session:
        return read.get_demande_by_id(session, demande_id, include_deleted)


def get_demandes_for_client(
    client_id: int,
    *,
    limit: int | None = None,
    offset: int = 0,
    include_deleted: bool = False,
) -> list[Demande]:
    """Retrieve all demandes belonging to a specific client."""
    with get_uow().session() as session:
        return read.get_demandes_for_client(session, client_id, limit, offset, include_deleted)


def fetch_deleted_demandes(*, limit: int | None = None, offset: int = 0) -> list[Demande]:
    """Fetch soft-deleted demandes for trash management."""
    with get_uow().session() as session:
        return read.fetch_deleted_demandes(session, limit, offset)


def get_total_deleted_demande_count() -> int:
    """Get total deleted demande count for pagination."""
    with get_uow().session() as session:
        return read.get_total_deleted_demande_count(session)


def _normalize_demande_data(
    input_data: Mapping[str, object], *, existing: Demande | None = None
) -> dict[str, object]:
    from .ale_helper import normalize_ale_fields

    if existing:
        processed = existing.to_dict()
    else:
        processed = {}

    processed.update(input_data)
    _drop_stale_lookup_ids(processed, input_data)

    beds = coerce_number(processed.get("beds_min"))
    surface_min = coerce_number(processed.get("surface_min"))
    surface_max = coerce_number(processed.get("surface_max"))
    budget_min = coerce_number(processed.get("budget_min"))
    budget_max = coerce_number(processed.get("budget_max"))

    if beds is not None and beds < 0:
        raise ValueError("beds_min cannot be negative")
    if surface_min is not None and surface_min < 0:
        raise ValueError("surface_min cannot be negative")
    if surface_max is not None and surface_max < 0:
        raise ValueError("surface_max cannot be negative")
    if budget_min is not None and budget_min < 0:
        raise ValueError("budget_min cannot be negative")
    if budget_max is not None and budget_max < 0:
        raise ValueError("budget_max cannot be negative")

    ensure_min_le_max(surface_min, surface_max, "surface_min", "surface_max")
    ensure_min_le_max(budget_min, budget_max, "budget_min", "budget_max")

    floor_min = coerce_number(processed.get("floor_min"))
    floor_max = coerce_number(processed.get("floor_max"))

    floor_min = 0.0 if floor_min is None else floor_min
    floor_max = 100.0 if floor_max is None else floor_max
    if floor_min < 0:
        raise ValueError("floor_min cannot be negative")
    if floor_max < 0:
        raise ValueError("floor_max cannot be negative")
    ensure_min_le_max(floor_min, floor_max, "floor_min", "floor_max")

    processed.update(
        {
            "type": norm_text(str(processed.get("type") or "")),
            "action": norm_text(str(processed.get("action") or "")),
            "wilaya": norm_text(str(processed.get("wilaya") or "")),
            "furnished": norm_text(str(processed.get("furnished") or "")),
            "beds_min": (None if beds is None else int(beds)),
            "surface_min": surface_min,
            "surface_max": surface_max,
            "budget_min": budget_min,
            "budget_max": budget_max,
            "floor_min": int(floor_min),
            "floor_max": int(floor_max),
        }
    )

    def normalize_ternary(val: Any) -> int | None:
        if val is None:
            return None
        v = as_int(val)
        return 1 if v == 1 else None

    processed["accessibility_required"] = normalize_ternary(processed.get("accessibility_required"))
    processed["elevator"] = normalize_ternary(processed.get("elevator"))

    normalize_ale_fields(
        processed,
        DEMANDE_ALE_POLICIES,
        changed_fields=set(input_data.keys()),
    )

    return processed


def _drop_stale_lookup_ids(processed: dict[str, object], input_data: Mapping[str, object]) -> None:
    """Let edited property type labels resolve fresh IDs when the client omits IDs."""
    if "type" in input_data:
        processed["type_id"] = None


def _enforce_strict_demande_fields(processed: Mapping[str, object]) -> None:
    """Enforce strict demande invariants after lookup resolution."""
    client_id = as_int(processed.get("client_id"), default=0)
    type_id = as_int(processed.get("type_id"), default=0)
    action_id = as_int(processed.get("action_id"), default=0)
    wilaya_id = as_int(processed.get("wilaya_id"), default=0)

    if client_id <= 0:
        raise ValueError("client_id is required for demandes")
    if type_id <= 0:
        raise ValueError("type_id is required for demandes")
    if action_id <= 0:
        raise ValueError("action_id is required for demandes")
    if wilaya_id <= 0:
        raise ValueError("wilaya_id is required for demandes")

    budget_min = coerce_number(processed.get("budget_min"))
    budget_max = coerce_number(processed.get("budget_max"))
    surface_min = coerce_number(processed.get("surface_min"))
    surface_max = coerce_number(processed.get("surface_max"))

    ensure_min_le_max(surface_min, surface_max, "surface_min", "surface_max")
    ensure_min_le_max(budget_min, budget_max, "budget_min", "budget_max")
