"""
Demande repository facade.

Re-exports demande read/write helpers to keep a stable import path.
"""

from __future__ import annotations

from core.data.demande_repo_read import (
    count_demandes_for_client,
    fetch_deleted_demandes,
    get_all_demande_counts,
    get_all_demandes_grouped,
    get_demande_by_id,
    get_demande_ids_for_client,
    get_demande_ids_for_listing,
    get_demande_ids_for_offer,
    get_demande_ids_for_offers,
    get_demande_ids_for_wilaya,
    get_demandes_for_client,
    get_total_demande_count,
    iter_demande_ids_for_client,
    iter_demande_ids_for_wilaya,
)
from core.data.demande_repo_write import (
    create_demande,
    delete_all_demandes_for_client,
    delete_demande,
    purge_demande,
    restore_demande,
    update_demande,
)

__all__ = [
    "create_demande",
    "update_demande",
    "delete_demande",
    "delete_all_demandes_for_client",
    "restore_demande",
    "purge_demande",
    "get_demande_by_id",
    "get_demande_ids_for_client",
    "get_demande_ids_for_offer",
    "get_demande_ids_for_offers",
    "get_demande_ids_for_listing",
    "get_demande_ids_for_wilaya",
    "iter_demande_ids_for_wilaya",
    "iter_demande_ids_for_client",
    "get_demandes_for_client",
    "count_demandes_for_client",
    "get_all_demande_counts",
    "get_total_demande_count",
    "get_all_demandes_grouped",
    "fetch_deleted_demandes",
]
