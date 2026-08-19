"""
Cleanup helpers for CRM contracts.
"""

from __future__ import annotations

from core.matcher.ports.db import DbSession
from core.models_cast import as_int, row_at


def cleanup_orphan_contracts(session: DbSession) -> int:
    """
    Delete contracts where client_id or listing_id no longer exists.
    Returns count of deleted records.
    """
    orphans = session.execute("""
        SELECT c.id FROM contracts c
        LEFT JOIN clients cl ON c.client_id = cl.id
        LEFT JOIN listings l ON c.listing_id = l.id
        WHERE c.deleted_at IS NULL
            AND (cl.id IS NULL OR l.id IS NULL)
    """).fetchall()

    orphan_ids: list[int] = []
    for row in orphans:
        orphan_id = row_at(row, 0)
        if orphan_id is not None:
            orphan_ids.append(as_int(orphan_id))

    if orphan_ids:
        placeholders = ",".join("%s" for _ in orphan_ids)
        session.execute(
            f"DELETE FROM contracts WHERE id IN ({placeholders})",
            orphan_ids,
        )

    return len(orphan_ids)
