"""
Write operations for demandes.
"""

from __future__ import annotations

from core.data.demande_repo_write_create import (
    create_demande,
    insert_demandes_batch,
    insert_demandes_batch_refs,
    update_demande,
)
from core.data.demande_repo_write_delete import (
    delete_all_demandes_for_client,
    delete_demande,
    purge_demande,
    restore_demande,
)

__all__ = [
    "create_demande",
    "insert_demandes_batch",
    "insert_demandes_batch_refs",
    "update_demande",
    "delete_demande",
    "delete_all_demandes_for_client",
    "restore_demande",
    "purge_demande",
]
