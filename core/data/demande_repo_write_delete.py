"""
Delete/restore operations for demandes.
"""

from __future__ import annotations

import logging

from core.data.surface_cache_generation import CLIENTS_SURFACE, agency_scope_key, bump_generation
from core.matcher.ports.db import DbSession
from core.models_cast import as_int
from core.utils.time import utc_now_iso

logger = logging.getLogger(__name__)


def delete_demande(session: DbSession, demande_id: int) -> None:
    """
    Delete a demande by ID.
    """
    now = utc_now_iso()
    deleted = session.execute(
        "UPDATE demandes SET deleted_at = %s, updated_at = %s, row_version = row_version + 1 "
        "WHERE id = %s "
        "RETURNING agency_id",
        (now, now, demande_id),
    ).fetchone()
    deleted_agency_id = as_int((deleted or {}).get("agency_id"), default=0)
    if deleted_agency_id > 0:
        bump_generation(
            session,
            surface=CLIENTS_SURFACE,
            scope_key=agency_scope_key(deleted_agency_id),
            agency_id=deleted_agency_id,
        )
    logger.debug("Deleted demande %s", demande_id)


def delete_all_demandes_for_client(session: DbSession, client_id: int) -> int:
    """
    Delete all demandes for a client.
    """
    now = utc_now_iso()
    rows = session.execute(
        "UPDATE demandes SET deleted_at = %s, updated_at = %s, row_version = row_version + 1 "
        "WHERE client_id = %s "
        "RETURNING agency_id",
        (now, now, client_id),
    ).fetchall()
    agency_ids = sorted(
        {
            as_int(row.get("agency_id"), default=0)
            for row in rows
            if as_int(row.get("agency_id"), default=0) > 0
        }
    )
    for agency_id in agency_ids:
        bump_generation(
            session,
            surface=CLIENTS_SURFACE,
            scope_key=agency_scope_key(agency_id),
            agency_id=agency_id,
        )
    count = session.rowcount
    logger.debug("Deleted %s demandes for client %s", count, client_id)
    return count


def restore_demande(session: DbSession, demande_id: int) -> None:
    """Restore a soft-deleted demande."""
    restored = session.execute(
        "UPDATE demandes SET deleted_at = NULL, updated_at = %s, row_version = row_version + 1 "
        "WHERE id = %s "
        "RETURNING agency_id",
        (utc_now_iso(), demande_id),
    ).fetchone()
    restored_agency_id = as_int((restored or {}).get("agency_id"), default=0)
    if restored_agency_id > 0:
        bump_generation(
            session,
            surface=CLIENTS_SURFACE,
            scope_key=agency_scope_key(restored_agency_id),
            agency_id=restored_agency_id,
        )


def purge_demande(session: DbSession, demande_id: int) -> None:
    """Permanently delete a demande."""
    purged = session.execute(
        "DELETE FROM demandes WHERE id = %s RETURNING agency_id",
        (demande_id,),
    ).fetchone()
    purged_agency_id = as_int((purged or {}).get("agency_id"), default=0)
    if purged_agency_id > 0:
        bump_generation(
            session,
            surface=CLIENTS_SURFACE,
            scope_key=agency_scope_key(purged_agency_id),
            agency_id=purged_agency_id,
        )
