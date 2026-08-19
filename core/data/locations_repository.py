"""
Custom Locations Repository - User-customizable commune list.
"""

from __future__ import annotations

import logging
import threading

from core.matcher.ports.db import DbSession
from core.models_cast import as_str, row_at
from core.utils.time import utc_now_iso

"""
Custom Locations Repository - User-customizable commune list.
"""

# Cache for fast access: dict[agency_id, set[locations]]
_locations_cache: dict[int, set[str]] = {}
_cache_lock = threading.Lock()
logger = logging.getLogger(__name__)


def _refresh_cache(session: DbSession) -> None:
    """Refresh the in-memory cache of locations for a specific agency."""
    from server.pg.uow import get_current_agency_id

    agency_id = get_current_agency_id()
    if agency_id is None:
        return

    rows = session.execute(
        "SELECT name FROM custom_locations WHERE deleted_at IS NULL ORDER BY name"
    ).fetchall()
    cache: set[str] = set()
    for row in rows:
        name = row_at(row, 0)
        if name is not None:
            cache.add(as_str(name))
    global _locations_cache
    with _cache_lock:
        _locations_cache[agency_id] = cache


def get_all_locations(session: DbSession) -> list[str]:
    """Get all available locations (sorted) for an agency."""
    from server.pg.uow import get_current_agency_id

    agency_id = get_current_agency_id()
    if agency_id is None:
        return []

    with _cache_lock:
        needs_refresh = agency_id not in _locations_cache
    if needs_refresh:
        _refresh_cache(session)
    with _cache_lock:
        return sorted(_locations_cache.get(agency_id, []))


def add_location(session: DbSession, name: str) -> bool:
    """Add a new location/commune for an agency."""
    from server.pg.uow import get_current_agency_id

    agency_id = get_current_agency_id()
    if agency_id is None:
        return False

    name = name.strip()
    if not name:
        return False

    with _cache_lock:
        if agency_id in _locations_cache and name in _locations_cache[agency_id]:
            return False

    try:
        now = utc_now_iso()
        existing = session.execute(
            """
            SELECT id FROM custom_locations
            WHERE name = %s AND deleted_at IS NULL
            LIMIT 1
            """,
            (name,),
        ).fetchone()
        if existing is not None:
            with _cache_lock:
                if agency_id not in _locations_cache:
                    _locations_cache[agency_id] = set()
                _locations_cache[agency_id].add(name)
            return False
        deleted = session.execute(
            """
            SELECT id FROM custom_locations
            WHERE name = %s AND deleted_at IS NOT NULL
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (name,),
        ).fetchone()
        if deleted is not None:
            session.execute(
                """
                UPDATE custom_locations
                SET deleted_at = NULL,
                    delete_origin = NULL,
                    delete_parent_scope = NULL,
                    delete_parent_id = NULL,
                    updated_at = %s,
                    row_version = row_version + 1
                WHERE id = %s
                """,
                (now, row_at(deleted, 0)),
            )
        else:
            session.execute(
                """
                INSERT INTO custom_locations (name, created_at, updated_at)
                VALUES (%s, %s, %s)
                """,
                (name, now, now),
            )
        with _cache_lock:
            if agency_id not in _locations_cache:
                _locations_cache[agency_id] = set()
            _locations_cache[agency_id].add(name)
        return True
    except Exception:
        logger.error("Failed to add location %s", name, exc_info=True)
        return False


def location_exists(session: DbSession, name: str) -> bool:
    """Check if a location exists in the list for an agency."""
    from server.pg.uow import get_current_agency_id

    agency_id = get_current_agency_id()
    if agency_id is None:
        return False

    with _cache_lock:
        needs_refresh = agency_id not in _locations_cache
    if needs_refresh:
        _refresh_cache(session)
    with _cache_lock:
        return name in _locations_cache.get(agency_id, set())


def delete_location(session: DbSession, name: str) -> bool:
    """Delete a custom location for an agency."""
    from server.pg.uow import get_current_agency_id

    agency_id = get_current_agency_id()
    if agency_id is None:
        return True

    now = utc_now_iso()
    session.execute(
        """
        UPDATE custom_locations
        SET deleted_at = %s, updated_at = %s, row_version = row_version + 1
        WHERE name = %s AND deleted_at IS NULL
        """,
        (now, now, name),
    )
    with _cache_lock:
        if agency_id in _locations_cache:
            _locations_cache[agency_id].discard(name)
    return True


def update_location(session: DbSession, old_name: str, new_name: str) -> bool:
    """Rename an existing location for an agency."""
    from server.pg.uow import get_current_agency_id

    agency_id = get_current_agency_id()
    if agency_id is None:
        return False

    old_name = (old_name or "").strip()
    new_name = (new_name or "").strip()
    if not old_name or not new_name:
        return False
    if old_name == new_name:
        return True
    with _cache_lock:
        if agency_id in _locations_cache and new_name in _locations_cache[agency_id]:
            return False

    now = utc_now_iso()
    session.execute(
        """
        UPDATE custom_locations
        SET name = %s, updated_at = %s, row_version = row_version + 1
        WHERE name = %s AND deleted_at IS NULL
        """,
        (new_name, now, old_name),
    )
    if session.rowcount > 0:
        with _cache_lock:
            if agency_id in _locations_cache:
                _locations_cache[agency_id].discard(old_name)
                _locations_cache[agency_id].add(new_name)
        return True
    return False
