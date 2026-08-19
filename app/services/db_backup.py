"""Service wrapper for database backups (disabled in API-only mode)."""

from __future__ import annotations


def backup_database(_reason: str, *, force: bool = False) -> str | None:
    """Backups are managed server-side; client-local backups are disabled."""
    _ = force
    return None


__all__ = ["backup_database"]
