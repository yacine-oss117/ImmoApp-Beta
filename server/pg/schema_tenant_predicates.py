"""
RLS predicate builders for tenant isolation.
"""

from __future__ import annotations

from server.pg.schema_tenant_constants import (
    ACTOR_ID_EXPR,
    AGENCY_DEFAULT_EXPR,
    MANAGER_OR_OWNER_EXPR,
    RLS_PREDICATE,
    TABLE_RLS_PREDICATE_OVERRIDES,
    VISIBILITY_TABLES,
)


def _visibility_predicate(table: str, ref: str | None) -> str:
    prefix = f"{ref}." if ref else ""
    outer_id_ref = f"{ref}.id" if ref else f"{table}.id"
    return (
        "("
        "(NULLIF(current_setting('app.is_superuser', true), '')::boolean = true) "
        "OR ("
        f"{prefix}agency_id = {AGENCY_DEFAULT_EXPR} "
        "AND ("
        f"{MANAGER_OR_OWNER_EXPR} "
        f"OR {prefix}visibility IS NULL "
        f"OR {prefix}visibility = 'agency' "
        "OR ("
        f"{prefix}visibility = 'restricted' "
        f"AND {ACTOR_ID_EXPR} IS NOT NULL "
        "AND EXISTS ("
        "SELECT 1 FROM record_acl ra "
        f"WHERE ra.table_name = '{table}' "
        f"AND ra.record_id = {outer_id_ref} "
        f"AND ra.user_id = {ACTOR_ID_EXPR}"
        ")"
        ")"
        ")"
        ")"
        ")"
    )


def rls_predicate_for_table(table: str) -> str:
    """Return the expected RLS predicate for a given tenant table."""
    override = TABLE_RLS_PREDICATE_OVERRIDES.get(table)
    if override is not None:
        return override
    if table in VISIBILITY_TABLES:
        return _visibility_predicate(table, None)
    if table == "match_pairs":
        return (
            "("
            "(NULLIF(current_setting('app.is_superuser', true), '')::boolean = true) "
            "OR ("
            f"agency_id = {AGENCY_DEFAULT_EXPR} "
            "AND ("
            f"{MANAGER_OR_OWNER_EXPR} "
            "OR match_pairs.demande_visibility IS NULL "
            "OR match_pairs.demande_visibility = 'agency' "
            "OR ("
            "match_pairs.demande_visibility = 'restricted' "
            f"AND {ACTOR_ID_EXPR} IS NOT NULL "
            "AND EXISTS ("
            "SELECT 1 FROM record_acl ra "
            "WHERE ra.table_name = 'demandes' "
            "AND ra.record_id = match_pairs.demande_id "
            f"AND ra.user_id = {ACTOR_ID_EXPR}"
            ")"
            ")"
            ") "
            "AND ("
            f"{MANAGER_OR_OWNER_EXPR} "
            "OR match_pairs.offer_visibility IS NULL "
            "OR match_pairs.offer_visibility = 'agency' "
            "OR ("
            "match_pairs.offer_visibility = 'restricted' "
            f"AND {ACTOR_ID_EXPR} IS NOT NULL "
            "AND EXISTS ("
            "SELECT 1 FROM record_acl ra "
            "WHERE ra.table_name = 'offers' "
            "AND ra.record_id = match_pairs.offer_id "
            f"AND ra.user_id = {ACTOR_ID_EXPR}"
            ")"
            ")"
            ")"
            ")"
            ")"
        )
    if table == "match_candidates":
        return (
            "("
            "(NULLIF(current_setting('app.is_superuser', true), '')::boolean = true) "
            "OR ("
            f"agency_id = {AGENCY_DEFAULT_EXPR} "
            "AND ("
            f"{MANAGER_OR_OWNER_EXPR} "
            "OR match_candidates.demande_visibility IS NULL "
            "OR match_candidates.demande_visibility = 'agency' "
            "OR ("
            "match_candidates.demande_visibility = 'restricted' "
            f"AND {ACTOR_ID_EXPR} IS NOT NULL "
            "AND EXISTS ("
            "SELECT 1 FROM record_acl ra "
            "WHERE ra.table_name = 'demandes' "
            "AND ra.record_id = match_candidates.demande_id "
            f"AND ra.user_id = {ACTOR_ID_EXPR}"
            ")"
            ")"
            ") "
            "AND ("
            f"{MANAGER_OR_OWNER_EXPR} "
            "OR match_candidates.offer_visibility IS NULL "
            "OR match_candidates.offer_visibility = 'agency' "
            "OR ("
            "match_candidates.offer_visibility = 'restricted' "
            f"AND {ACTOR_ID_EXPR} IS NOT NULL "
            "AND EXISTS ("
            "SELECT 1 FROM record_acl ra "
            "WHERE ra.table_name = 'offers' "
            "AND ra.record_id = match_candidates.offer_id "
            f"AND ra.user_id = {ACTOR_ID_EXPR}"
            ")"
            ")"
            ")"
            ")"
            ")"
        )
    if table == "match_counts_cache":
        return (
            "("
            "(NULLIF(current_setting('app.is_superuser', true), '')::boolean = true) "
            "OR ("
            f"agency_id = {AGENCY_DEFAULT_EXPR} "
            "AND ("
            f"{MANAGER_OR_OWNER_EXPR} "
            "OR match_counts_cache.visibility IS NULL "
            "OR match_counts_cache.visibility = 'agency' "
            "OR ("
            "match_counts_cache.visibility = 'restricted' "
            f"AND {ACTOR_ID_EXPR} IS NOT NULL "
            "AND EXISTS ("
            "SELECT 1 FROM record_acl ra "
            "WHERE ra.table_name = 'clients' "
            "AND ra.record_id = match_counts_cache.client_id "
            f"AND ra.user_id = {ACTOR_ID_EXPR}"
            ")"
            ")"
            ")"
            ")"
            ")"
        )
    return RLS_PREDICATE


__all__ = ["rls_predicate_for_table"]
