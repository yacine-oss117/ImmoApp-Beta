"""
Match cache facade.

Re-exports read/write/schema helpers to keep a stable import path.
"""

from __future__ import annotations

from core.data.match_cache_read import (
    get_cached_count,
    get_cached_count_for_ids,
    get_cached_count_with_status,
    get_cached_counts_batch,
    get_cached_counts_with_meta_for_ids,
    get_dirty_client_count,
    get_dirty_client_ids_page,
    get_dirty_count,
    get_hot_leads,
    get_missing_client_count,
    get_missing_client_ids_page,
    is_cache_clean,
)
from core.data.match_cache_write import (
    clear_all,
    delete_client_cache,
    mark_all_dirty,
    mark_client_dirty,
    mark_clients_for_demande_ids_dirty,
    mark_clients_in_wilaya_dirty,
    store_count,
    store_counts_batch,
)

__all__ = [
    "is_cache_clean",
    "get_dirty_count",
    "get_dirty_client_count",
    "get_missing_client_count",
    "get_cached_count",
    "get_cached_count_with_status",
    "get_cached_count_for_ids",
    "get_cached_counts_with_meta_for_ids",
    "get_cached_counts_batch",
    "get_hot_leads",
    "store_count",
    "store_counts_batch",
    "mark_client_dirty",
    "mark_clients_for_demande_ids_dirty",
    "mark_clients_in_wilaya_dirty",
    "mark_all_dirty",
    "clear_all",
    "get_missing_client_ids_page",
    "get_dirty_client_ids_page",
    "delete_client_cache",
]
