"""
Postgres-backed custom locations operations.
"""

from __future__ import annotations

from core.data import locations_repository as data
from server.pg.uow import get_uow


def get_all_locations() -> list[str]:
    """List all custom locations for an agency."""
    with get_uow().session() as session:
        return data.get_all_locations(session)


def add_location(name: str) -> bool:
    """Add a new custom location to the agency's list."""
    with get_uow().transaction() as session:
        return data.add_location(session, name)


def delete_location(name: str) -> bool:
    """Remove a custom location from the agency's list."""
    with get_uow().transaction() as session:
        return data.delete_location(session, name)


def update_location(old_name: str, new_name: str) -> bool:
    """Rename an existing custom location."""
    with get_uow().transaction() as session:
        return data.update_location(session, old_name, new_name)


def refresh_locations_cache() -> None:
    """Manually clear and reload the location name cache."""
    with get_uow().session() as session:
        data._refresh_cache(session)
