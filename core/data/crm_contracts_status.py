"""
Status mutation helpers for CRM contracts.
"""

from __future__ import annotations

import logging

from core.matcher.ports.db import DbSession

logger = logging.getLogger(__name__)


def update_client_status(session: DbSession, client_id: int, status: str) -> None:
    """Update client status (e.g. 'active', 'archived_rented')."""
    session.execute(
        "UPDATE clients SET status = %s, row_version = row_version + 1 "
        "WHERE id = %s AND deleted_at IS NULL",
        (status, client_id),
    )


def update_listing_status(session: DbSession, listing_id: int, status: str) -> None:
    """Update listing status (e.g. 'available', 'rented')."""
    session.execute(
        "UPDATE listings SET status = %s, row_version = row_version + 1 "
        "WHERE id = %s AND deleted_at IS NULL",
        (status, listing_id),
    )


def archive_demande_offer(session: DbSession, client_id: int, listing_id: int) -> None:
    """Archive matching demande/offer when a contract is signed."""
    logger.debug(
        "archive_demande_offer called for client=%s, listing=%s (no-op)",
        client_id,
        listing_id,
    )
