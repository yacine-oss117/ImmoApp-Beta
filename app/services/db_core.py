"""
Database core service - API-only facade (SQLite removed).
"""

from __future__ import annotations

from app.services.api_client import api_get
from app.services.api_config import get_api_base_url


def db_init() -> None:
    """Initialize database or validate API connectivity."""
    base_url = get_api_base_url()
    if not base_url:
        raise RuntimeError("API base URL is not configured")
    try:
        api_get("/health")
    except Exception as exc:
        raise RuntimeError(f"API health check failed: {exc}") from exc


def optimize_db() -> None:
    """Optimize local database (not available in API mode)."""
    return None


def db_health_status() -> str:
    """Return a short health status string for UI status bar."""
    return "API"


def active_connection_count() -> int:
    """Return the number of active database connections (always 0 in API mode)."""
    return 0


def wait_for_no_active_connections(timeout_seconds: float = 10.0) -> bool:
    """Wait for all connections to close (always True in API mode)."""
    return True


def get_audit_actor() -> str:
    """Get the current audit actor name (empty in API mode - handled server-side)."""
    return ""


def set_audit_actor(actor: str) -> None:
    """Set the audit actor name (no-op in API mode - handled server-side)."""
    return None


__all__ = [
    "db_init",
    "optimize_db",
    "db_health_status",
    "active_connection_count",
    "wait_for_no_active_connections",
    "get_audit_actor",
    "set_audit_actor",
]
