"""
Optimized Match Counter Module (facade).
"""

from core.matcher.match_counter_batch import (
    batch_count_all_clients_cte,
    batch_count_all_demandes_cte,
    batch_count_all_listings_cte,
    batch_count_all_offers_cte,
    batch_count_clients_paginated,
    batch_count_listings_paginated,
    count_clients_in_wilaya_cte,
    count_demandes_by_ids,
    count_offers_by_ids,
    count_single_client_cte,
)
from core.matcher.match_counter_demande import (
    count_matches_per_demande,
    get_all_demande_match_counts,
)

__all__ = [
    "batch_count_all_clients_cte",
    "batch_count_all_demandes_cte",
    "batch_count_all_listings_cte",
    "batch_count_all_offers_cte",
    "batch_count_clients_paginated",
    "batch_count_listings_paginated",
    "count_clients_in_wilaya_cte",
    "count_demandes_by_ids",
    "count_offers_by_ids",
    "count_single_client_cte",
    "count_matches_per_demande",
    "get_all_demande_match_counts",
]
