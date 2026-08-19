"""
Canonical task name registry.

This enum is the single source of truth for Celery task exports that callers
are allowed to schedule through ``server.api.tasks``.
"""

from __future__ import annotations

from enum import StrEnum


class TaskName(StrEnum):
    IMPORT_PARSE = "import_parse_task"
    IMPORT_EXECUTE = "import_execute_task"
    IMPORT_REVIEW_SUBMIT = "import_review_submit_task"
    REBUILD_MATCH_CACHE_ALL = "rebuild_match_cache_all"
    REBUILD_MATCH_CACHE_DIRTY = "rebuild_match_cache_dirty"
    REBUILD_MATCH_CACHE_CLIENT = "rebuild_match_cache_client"
    REBUILD_MATCH_CACHE_WILAYA = "rebuild_match_cache_wilaya"
    REBUILD_MATCH_PAIRS_DEMANDE = "rebuild_match_pairs_for_demande"
    REBUILD_MATCH_PAIRS_DEMANDES_BATCH = "rebuild_match_pairs_for_demandes_batch"
    FLUSH_REBUILD_DEMANDE_PAIRS_QUEUE = "flush_rebuild_demande_pairs_queue"
    EXPAND_MATCH_PAIRS_DEMANDE = "expand_match_pairs_for_demande"
    REBUILD_MATCH_PAIRS_WILAYA = "rebuild_match_pairs_for_wilaya"
    REBUILD_MATCH_PAIRS_CLIENT = "rebuild_match_pairs_for_client"
    REBUILD_MATCH_PAIRS_OFFER = "rebuild_match_pairs_for_offer"
    REBUILD_MATCH_PAIRS_OFFERS_BATCH = "rebuild_match_pairs_for_offers_batch"
    MATCH_PAIRS_JANITOR = "match_pairs_janitor_task"
    COUNT_MATCHES_ALL_CLIENTS = "count_matches_all_clients_task"
    COUNT_MATCHES_ALL_DEMANDES = "count_matches_all_demandes_task"
    COUNT_MATCHES_ALL_LISTINGS = "count_matches_all_listings_task"
    COUNT_MATCHES_ALL_OFFERS = "count_matches_all_offers_task"
    FETCH_MATCH_CACHE_ALL = "fetch_match_cache_all_task"
    PURGE_OLD_AUDIT_LOGS = "purge_old_audit_logs_task"
    PURGE_OLD_AUTH_EVENTS = "purge_old_auth_events_task"
    PURGE_DELETED_STORAGE_OBJECTS = "purge_deleted_storage_objects_task"
    PURGE_PENDING_STORAGE_OBJECTS = "purge_pending_storage_objects_task"
    PURGE_IDEMPOTENCY_RECORDS = "purge_idempotency_records_task"
    FLUSH_EMAIL_OUTBOX = "flush_email_outbox"
    REQUEUE_EXPIRED_IMPORT_PHASES = "requeue_expired_import_phases_task"
    PRUNE_IMPORTER_RUNTIME_ARTIFACTS = "prune_importer_runtime_artifacts_task"
    PURGE_NOTIFICATIONS = "purge_notifications_task"
    PURGE_ALE_PII = "purge_ale_pii_task"
    EXPIRE_PENDING_REGISTRATION_REQUESTS = "expire_pending_registration_requests_task"
    ALE_ROTATION_ALERT = "ale_rotation_alert_task"
    ROTATE_ALE_KEYS = "rotate_ale_keys_task"
    REINDEX_ALE_SEARCH = "reindex_ale_search_task"
    ROTATE_ALE_SEARCH_KEYS = "rotate_ale_search_keys_task"
    RUN_COMPLIANCE_EXPORT = "run_compliance_export_task"
    RUN_COMPLIANCE_DELETE = "run_compliance_delete_task"
    SNAPSHOT_POSTGRES_MATCH_HEALTH = "snapshot_postgres_match_health"


__all__ = ["TaskName"]
