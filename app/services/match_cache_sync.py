"""
Cache write helpers for UI-driven match count updates.
"""

from __future__ import annotations

import logging

from app.services.match_cache import mark_client_dirty, store_count

logger = logging.getLogger(__name__)


def _context_suffix(context: str | None) -> str:
    return f" ({context})" if context else ""


def store_client_match_count(client_id: int, count: int, *, context: str | None = None) -> bool:
    """
    Persist a single client's match count with fallback to mark dirty.
    Uses the match_cache service which handles transactions.
    """
    try:
        store_count(client_id, count)
        return True
    except Exception:
        logger.error(
            "Failed to store match count for %s%s",
            client_id,
            _context_suffix(context),
            exc_info=True,
        )
        try:
            mark_client_dirty(client_id)
        except Exception:
            logger.error(
                "Fallback mark_client_dirty failed for %s%s",
                client_id,
                _context_suffix(context),
                exc_info=True,
            )
            logger.warning(
                "Proceeding without cache persistence for client %s%s",
                client_id,
                _context_suffix(context),
            )
            return False
        return False
