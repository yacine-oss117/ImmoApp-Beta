"""RLS predicate guardrails for match_counts_cache."""

from server.pg.schema_tenant_predicates import rls_predicate_for_table


def test_match_cache_predicate_avoids_clients_join() -> None:
    predicate = rls_predicate_for_table("match_counts_cache")
    assert "FROM clients" not in predicate
    assert "match_counts_cache.visibility" in predicate
