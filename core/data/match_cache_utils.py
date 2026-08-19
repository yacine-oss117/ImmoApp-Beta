"""
Shared helpers for the match count cache modules.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def mark_dashboard_stale() -> None:
    """Notify the dashboard cache it should refresh."""
    logger.debug("Dashboard cache invalidation requested (no local cache)")


def chunk_ids(ids: list[int], chunk_size: int = 900) -> list[list[int]]:
    """Yield ID chunks small enough for database parameter limits."""
    return [ids[i : i + chunk_size] for i in range(0, len(ids), chunk_size)]
