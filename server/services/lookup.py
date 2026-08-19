"""
Postgres-backed lookup helpers for reference tables.
"""

from __future__ import annotations

from core.data import lookup_tables as data
from server.pg.uow import get_uow

__all__ = [
    "get_property_type_id",
    "get_property_type_name",
    "get_action_id",
    "get_action_name",
    "get_wilaya_id",
    "get_wilaya_name",
    "get_all_property_types",
    "get_all_actions",
    "get_all_wilayas",
]


def get_property_type_id(name: str) -> int | None:
    """Resolve property type ID by name."""
    with get_uow().session() as session:
        return data.get_property_type_id(session, name)


def get_property_type_name(type_id: int) -> str | None:
    """Resolve property type name by ID."""
    with get_uow().session() as session:
        return data.get_property_type_name(session, type_id)


def get_action_id(name: str) -> int | None:
    """Resolve action ID by name."""
    with get_uow().session() as session:
        return data.get_action_id(session, name)


def get_action_name(action_id: int) -> str | None:
    """Resolve action name by ID."""
    with get_uow().session() as session:
        return data.get_action_name(session, action_id)


def get_wilaya_id(name: str) -> int | None:
    """Resolve wilaya ID by name."""
    with get_uow().session() as session:
        return data.get_wilaya_id(session, name)


def get_wilaya_name(wilaya_id: int) -> str | None:
    """Resolve wilaya name by ID."""
    with get_uow().session() as session:
        return data.get_wilaya_name(session, wilaya_id)


def get_all_property_types() -> list[tuple[int, str]]:
    """Fetch all property types."""
    with get_uow().session() as session:
        return data.get_all_property_types(session)


def get_all_actions() -> list[tuple[int, str]]:
    """Fetch all actions."""
    with get_uow().session() as session:
        return data.get_all_actions(session)


def get_all_wilayas() -> list[tuple[int, str, str]]:
    """Fetch all wilayas."""
    with get_uow().session() as session:
        return data.get_all_wilayas(session)
