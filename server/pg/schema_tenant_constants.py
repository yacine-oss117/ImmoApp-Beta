"""
Canonical constants for tenant isolation/RLS.
"""

from __future__ import annotations

import hashlib
import json

# Canonical tenant table list (used by enforcement + verification)
TENANT_TABLES = [
    "clients",
    "listings",
    "visits",
    "contracts",
    "demandes",
    "offers",
    "demande_locations",
    "offer_locations",
    "match_counts_cache",
    "match_candidates",
    "match_pairs",
    "match_rebuild_state",
    "custom_locations",
    "contract_articles",
    "wa_templates",
    "audit_logs",
    "task_failures",
    "notifications",
    "notification_reads",
    "surface_cache_generation",
    "auth_security_events",
    "storage_objects",
    "offer_photos",
    "record_acl",
    "storage_usage",
    "storage_events",
    "agency_settings",
    "imports_importjob",
    "imports_importagencyalias",
    "imports_importagencyprofile",
    "imports_importcorrectionsignal",
    "imports_importdeadletterrow",
    "imports_importrowaudit",
    "imports_importchunk",
    "imports_importchunkphase",
    "imports_importartifactmanifest",
]

# Tenant tables that should never allow NULL agency_id
TENANT_TABLES_NOT_NULL = [
    "clients",
    "listings",
    "visits",
    "contracts",
    "demandes",
    "offers",
    "demande_locations",
    "offer_locations",
    "match_counts_cache",
    "match_candidates",
    "match_pairs",
    "match_rebuild_state",
    "custom_locations",
    "contract_articles",
    "wa_templates",
    "storage_objects",
    "offer_photos",
    "record_acl",
    "storage_usage",
    "storage_events",
    "agency_settings",
    "imports_importjob",
    "imports_importagencyalias",
    "imports_importagencyprofile",
    "imports_importcorrectionsignal",
    "imports_importdeadletterrow",
    "imports_importrowaudit",
    "imports_importchunk",
    "imports_importartifactmanifest",
]

# Tenant tables that allow NULL agency_id (explicit allow-list)
TENANT_TABLES_NULL_OK = {
    "audit_logs",
    "task_failures",
    "notifications",
    "notification_reads",
    "auth_security_events",
    "surface_cache_generation",
}

# Tables that support per-record visibility/ACL rules
VISIBILITY_TABLES = {
    "clients",
    "listings",
    "demandes",
    "offers",
    "visits",
    "contracts",
}

# Canonical RLS predicate + DEFAULT expression
RLS_PREDICATE = (
    "(NULLIF(current_setting('app.is_superuser', true), '')::boolean = true) "
    "OR (agency_id = NULLIF(current_setting('app.current_agency_id', true), '')::bigint)"
)
AGENCY_DEFAULT_EXPR = "NULLIF(current_setting('app.current_agency_id', true), '')::bigint"
SURFACE_CACHE_GENERATION_RLS_PREDICATE = (
    "(NULLIF(current_setting('app.is_superuser', true), '')::boolean = true) "
    f"OR (agency_id IS NOT NULL AND agency_id = {AGENCY_DEFAULT_EXPR})"
)
TABLE_RLS_PREDICATE_OVERRIDES: dict[str, str] = {
    "surface_cache_generation": SURFACE_CACHE_GENERATION_RLS_PREDICATE,
}
TABLE_AGENCY_ID_DEFAULT_OVERRIDES: dict[str, str | None] = {
    # Global surface scopes intentionally allow NULL agency_id and therefore
    # cannot rely on the generic tenant-column default.
    "surface_cache_generation": None,
}

ACTOR_ID_EXPR = "NULLIF(current_setting('app.actor_id', true), '')::bigint"
ACTOR_ROLE_EXPR = "NULLIF(current_setting('app.actor_role', true), '')"
ACTOR_IS_OWNER_EXPR = "NULLIF(current_setting('app.actor_is_owner', true), '')::boolean = true"
MANAGER_OR_OWNER_EXPR = (
    f"({ACTOR_ROLE_EXPR} = ANY (ARRAY['manager','super_admin']) OR {ACTOR_IS_OWNER_EXPR})"
)

GLOBAL_SYSTEM_TABLES = (
    "django_migrations",
    "django_content_type",
    "auth_permission",
    "auth_group",
    "auth_group_permissions",
    "django_session",
    "match_artifact_health_samples",
    "match_artifact_timeout_counters",
)

SPECIAL_POLYMORPHIC_TABLES = ("record_acl",)

TENANT_OWNED_TABLES = tuple(
    table_name for table_name in TENANT_TABLES if table_name not in SPECIAL_POLYMORPHIC_TABLES
)
DB_RLS_MANAGED_TABLES = tuple(
    table_name
    for table_name in TENANT_TABLES
    if table_name
    not in {
        "imports_importjob",
        "imports_importagencyalias",
        "imports_importagencyprofile",
        "imports_importcorrectionsignal",
        "imports_importdeadletterrow",
        "imports_importrowaudit",
        "imports_importchunk",
        "imports_importchunkphase",
        "imports_importartifactmanifest",
    }
)
CLIENT_LOCAL_STORES = (
    "agency_settings_cache",
    "agency_media_cache",
    "dashboard_cache",
    "locations_cache",
    "offline_sync_op_log",
    "offline_sync_pending_snapshot",
    "offline_sync_projection_snapshot",
    "offline_sync_temp_id_map",
    "offline_sync_conflicts",
    "offline_sync_allocator_state",
    "offline_sync_meta",
    "upload_queue",
    "upload_queue_history",
)


def tenant_surface_classification_manifest() -> dict[str, object]:
    return {
        "tenant_owned": list(TENANT_OWNED_TABLES),
        "global_system": list(GLOBAL_SYSTEM_TABLES),
        "special_polymorphic": list(SPECIAL_POLYMORPHIC_TABLES),
        "client_local_stores": list(CLIENT_LOCAL_STORES),
    }


def tenant_surface_classification_version() -> str:
    payload = json.dumps(tenant_surface_classification_manifest(), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]
