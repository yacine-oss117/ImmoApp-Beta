"""
Lookup Tables - Normalized reference data for schema optimization.
"""

from __future__ import annotations

from core.matcher.ports.db import DbSession
from core.models_cast import as_int, as_optional_int, as_str, row_at


def get_property_type_id(session: DbSession, name: str) -> int | None:
    """Get property type ID by name."""
    if not name:
        return None
    row = session.execute(
        """
        SELECT id
        FROM property_types
        WHERE LOWER(name) = LOWER(%s)
           OR (name_ar IS NOT NULL AND LOWER(name_ar) = LOWER(%s))
        """,
        (name.strip(), name.strip()),
    ).fetchone()
    return as_optional_int(row_at(row, 0)) if row else None


def get_property_type_name(session: DbSession, type_id: int) -> str | None:
    """Get property type name by ID."""
    row = session.execute("SELECT name FROM property_types WHERE id = %s", (type_id,)).fetchone()
    value = row_at(row, 0) if row else None
    return as_str(value) if value is not None else None


def get_action_id(session: DbSession, name: str) -> int | None:
    """Get action ID by name."""
    if not name:
        return None
    row = session.execute(
        """
        SELECT id
        FROM actions
        WHERE LOWER(name) = LOWER(%s)
           OR (name_ar IS NOT NULL AND LOWER(name_ar) = LOWER(%s))
        """,
        (name.strip(), name.strip()),
    ).fetchone()
    return as_optional_int(row_at(row, 0)) if row else None


def get_action_name(session: DbSession, action_id: int) -> str | None:
    """Get action name by ID."""
    row = session.execute("SELECT name FROM actions WHERE id = %s", (action_id,)).fetchone()
    value = row_at(row, 0) if row else None
    return as_str(value) if value is not None else None


def get_wilaya_id(session: DbSession, name: str) -> int | None:
    """Get wilaya ID by name."""
    if not name:
        return None
    row = session.execute(
        """
        SELECT id
        FROM wilayas
        WHERE LOWER(name) = LOWER(%s)
           OR (name_ar IS NOT NULL AND LOWER(name_ar) = LOWER(%s))
           OR code = %s
        """,
        (name.strip(), name.strip(), name.strip()),
    ).fetchone()
    return as_optional_int(row_at(row, 0)) if row else None


def get_wilaya_name(session: DbSession, wilaya_id: int) -> str | None:
    """Get wilaya name by ID."""
    row = session.execute("SELECT name FROM wilayas WHERE id = %s", (wilaya_id,)).fetchone()
    value = row_at(row, 0) if row else None
    return as_str(value) if value is not None else None


def resolve_property_type(
    session: DbSession, type_id: int | None, name: str | None
) -> tuple[int | None, str]:
    """Resolve a property type to (id, canonical name)."""
    normalized = name.strip() if isinstance(name, str) else ""
    if type_id is not None:
        resolved_name = get_property_type_name(session, type_id)
        if not resolved_name:
            raise ValueError("Unknown property type id")
        if normalized and normalized.lower() != resolved_name.lower():
            raise ValueError("Property type mismatch")
        return type_id, resolved_name
    if normalized:
        resolved_id = get_property_type_id(session, normalized)
        if resolved_id is None:
            raise ValueError(f"Unknown property type: {normalized}")
        return resolved_id, get_property_type_name(session, resolved_id) or normalized
    return None, ""


def resolve_action(
    session: DbSession, action_id: int | None, name: str | None
) -> tuple[int | None, str]:
    """Resolve an action to (id, canonical name)."""
    normalized = name.strip() if isinstance(name, str) else ""
    if action_id is not None:
        resolved_name = get_action_name(session, action_id)
        if not resolved_name:
            raise ValueError("Unknown action id")
        if normalized and normalized.lower() != resolved_name.lower():
            raise ValueError("Action mismatch")
        return action_id, resolved_name
    if normalized:
        resolved_id = get_action_id(session, normalized)
        if resolved_id is None:
            raise ValueError(f"Unknown action: {normalized}")
        return resolved_id, get_action_name(session, resolved_id) or normalized
    return None, ""


def resolve_wilaya(
    session: DbSession, wilaya_id: int | None, name: str | None
) -> tuple[int | None, str]:
    """Resolve a wilaya to (id, canonical name)."""
    normalized = name.strip() if isinstance(name, str) else ""
    if wilaya_id is not None:
        resolved_name = get_wilaya_name(session, wilaya_id)
        if not resolved_name:
            raise ValueError("Unknown wilaya id")
        if normalized and normalized.lower() != resolved_name.lower():
            raise ValueError("Wilaya mismatch")
        return wilaya_id, resolved_name
    if normalized:
        resolved_id = get_wilaya_id(session, normalized)
        if resolved_id is None:
            raise ValueError(f"Unknown wilaya: {normalized}")
        return resolved_id, get_wilaya_name(session, resolved_id) or normalized
    return None, ""


def get_all_property_types(session: DbSession) -> list[tuple[int, str]]:
    """Get all property types as (id, name) tuples."""
    rows = session.execute("SELECT id, name FROM property_types ORDER BY id").fetchall()
    items: list[tuple[int, str]] = []
    for row in rows:
        type_id = row_at(row, 0)
        name = row_at(row, 1)
        if type_id is None or name is None:
            continue
        items.append((as_int(type_id), as_str(name)))
    return items


def get_all_actions(session: DbSession) -> list[tuple[int, str]]:
    """Get all actions as (id, name) tuples."""
    rows = session.execute("SELECT id, name FROM actions ORDER BY id").fetchall()
    items: list[tuple[int, str]] = []
    for row in rows:
        action_id = row_at(row, 0)
        name = row_at(row, 1)
        if action_id is None or name is None:
            continue
        items.append((as_int(action_id), as_str(name)))
    return items


def get_all_wilayas(session: DbSession) -> list[tuple[int, str, str]]:
    """Get all wilayas as (id, name, code) tuples."""
    rows = session.execute("SELECT id, name, code FROM wilayas ORDER BY id").fetchall()
    items: list[tuple[int, str, str]] = []
    for row in rows:
        wilaya_id = row_at(row, 0)
        name = row_at(row, 1)
        code = row_at(row, 2)
        if wilaya_id is None or name is None or code is None:
            continue
        items.append((as_int(wilaya_id), as_str(name), as_str(code)))
    return items
