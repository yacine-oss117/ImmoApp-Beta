"""
Visit operations for CRM (Postgres-backed).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, cast

from core.data import crm_visits as visits
from core.models import Visit
from core.shared_types import VisitData
from server.pg.uow import get_uow

from .ale_policy import CRM_VISIT_ALE_POLICIES

logger = logging.getLogger(__name__)


def create_visit(visit_data: Mapping[str, Any], *, actor: str | None = None) -> int:
    """Schedule a new property visit."""
    processed = cast(VisitData, _normalize_visit_data(visit_data))
    with get_uow().transaction(actor=actor) as session:
        visit_id = visits.create_visit(session, processed)
    return visit_id


def update_visit(
    visit_id: int,
    visit_data: Mapping[str, Any],
    *,
    actor: str | None = None,
) -> None:
    """Update visit details."""
    existing = get_visit_by_id(visit_id)
    processed = _normalize_visit_data(visit_data, existing=existing)
    with get_uow().transaction(actor=actor) as session:
        visits.update_visit(session, visit_id, processed)


def fetch_visits(
    *,
    limit: int = 100,
    offset: int = 0,
    client_id: int | None = None,
    status: str | None = None,
    scheduled_date: str | None = None,
) -> list[Visit]:
    """Fetch visits with optional filtering."""
    with get_uow().session() as session:
        return visits.fetch_visits(
            session,
            status=status,
            client_id=str(client_id) if client_id is not None else None,
            scheduled_date=scheduled_date,
            limit=limit,
            offset=offset,
        )


def get_total_visit_count(
    *,
    client_id: int | None = None,
    status: str | None = None,
    scheduled_date: str | None = None,
) -> int:
    """Get total visit count for pagination."""
    with get_uow().session() as session:
        return visits.get_total_visit_count(
            session,
            status=status,
            client_id=str(client_id) if client_id is not None else None,
            scheduled_date=scheduled_date,
        )


def get_visit_by_id(visit_id: int, *, include_deleted: bool = False) -> Visit | None:
    """Get a single visit by ID."""
    with get_uow().session() as session:
        return visits.get_visit_by_id(session, visit_id, include_deleted)


def fetch_deleted_visits(*, limit: int = 100, offset: int = 0) -> list[Visit]:
    """Fetch soft-deleted visits for trash management."""
    with get_uow().session() as session:
        return visits.fetch_deleted_visits(session, limit=limit, offset=offset)


def get_total_deleted_visit_count() -> int:
    """Get total deleted visit count for pagination."""
    with get_uow().session() as session:
        return visits.get_total_deleted_visit_count(session)


def delete_visit(visit_id: int, *, actor: str | None = None) -> None:
    """Soft-delete a visit."""
    with get_uow().transaction(actor=actor) as session:
        visits.delete_visit(session, visit_id)


def restore_visit(visit_id: int, *, actor: str | None = None) -> None:
    """Restore a soft-deleted visit."""
    with get_uow().transaction(actor=actor) as session:
        visits.restore_visit(session, visit_id)


def purge_visit(visit_id: int, *, actor: str | None = None) -> None:
    """Permanently delete a visit."""
    with get_uow().transaction(actor=actor) as session:
        visits.purge_visit(session, visit_id)


def _normalize_visit_data(
    input_data: Mapping[str, Any], *, existing: Visit | None = None
) -> dict[str, Any]:
    from .ale_helper import normalize_ale_fields

    processed: dict[str, Any] = dict(existing.to_dict()) if existing else {}

    processed.update(input_data)

    normalize_ale_fields(
        processed,
        CRM_VISIT_ALE_POLICIES,
        changed_fields=set(input_data.keys()),
    )

    return processed
