from __future__ import annotations

from core.data.schema_registry import TABLE_COLUMNS


def test_match_cache_schema_registry_forbids_identity_columns() -> None:
    cache_columns = TABLE_COLUMNS["match_counts_cache"]
    forbidden = {"family_name", "phone", "email", "address", "display_name"}
    assert forbidden.isdisjoint(cache_columns)
    assert {"agency_id", "client_id", "count", "computed_at", "is_dirty"}.issubset(cache_columns)
