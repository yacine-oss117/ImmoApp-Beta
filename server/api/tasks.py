"""
Celery task aggregator.

This module re-exports tasks defined in focused submodules so Celery
autodiscovery continues to work via `api.tasks`.
"""

from .tasks_ale import (
    ale_rotation_alert_task,
    purge_ale_pii_task,
    reindex_ale_search_task,
    rotate_ale_keys_task,
    rotate_ale_search_keys_task,
)
from .tasks_compliance import run_compliance_delete_task, run_compliance_export_task
from .tasks_import import import_execute_task, import_parse_task
from .tasks_import_review import import_review_submit_task
from .tasks_integrity import match_pairs_janitor_task
from .tasks_maintenance import (
    expire_pending_registration_requests_task,
    flush_email_outbox,
    prune_importer_runtime_artifacts_task,
    purge_deleted_storage_objects_task,
    purge_idempotency_records_task,
    purge_old_audit_logs_task,
    purge_old_auth_events_task,
    purge_pending_storage_objects_task,
    requeue_expired_import_phases_task,
)
from .tasks_match_cache import (
    count_matches_all_clients_task,
    count_matches_all_demandes_task,
    count_matches_all_listings_task,
    count_matches_all_offers_task,
    fetch_match_cache_all_task,
    rebuild_match_cache_all,
    rebuild_match_cache_client,
    rebuild_match_cache_dirty,
    rebuild_match_cache_wilaya,
)
from .tasks_match_pairs import (
    expand_match_pairs_for_demande,
    flush_rebuild_demande_pairs_queue,
    rebuild_match_pairs_for_client,
    rebuild_match_pairs_for_demande,
    rebuild_match_pairs_for_demandes_batch,
    rebuild_match_pairs_for_offer,
    rebuild_match_pairs_for_offers_batch,
    rebuild_match_pairs_for_wilaya,
)
from .tasks_notifications import purge_notifications_task
from .tasks_postgres_health import snapshot_postgres_match_health

__all__ = [
    "import_parse_task",
    "import_execute_task",
    "import_review_submit_task",
    "rebuild_match_cache_all",
    "rebuild_match_cache_dirty",
    "rebuild_match_cache_client",
    "rebuild_match_cache_wilaya",
    "rebuild_match_pairs_for_demande",
    "rebuild_match_pairs_for_demandes_batch",
    "flush_rebuild_demande_pairs_queue",
    "expand_match_pairs_for_demande",
    "rebuild_match_pairs_for_wilaya",
    "rebuild_match_pairs_for_client",
    "rebuild_match_pairs_for_offer",
    "rebuild_match_pairs_for_offers_batch",
    "match_pairs_janitor_task",
    "count_matches_all_clients_task",
    "count_matches_all_demandes_task",
    "count_matches_all_listings_task",
    "count_matches_all_offers_task",
    "fetch_match_cache_all_task",
    "purge_old_audit_logs_task",
    "purge_old_auth_events_task",
    "purge_deleted_storage_objects_task",
    "purge_pending_storage_objects_task",
    "flush_email_outbox",
    "expire_pending_registration_requests_task",
    "purge_idempotency_records_task",
    "requeue_expired_import_phases_task",
    "prune_importer_runtime_artifacts_task",
    "purge_notifications_task",
    "purge_ale_pii_task",
    "ale_rotation_alert_task",
    "rotate_ale_keys_task",
    "reindex_ale_search_task",
    "rotate_ale_search_keys_task",
    "run_compliance_export_task",
    "run_compliance_delete_task",
    "snapshot_postgres_match_health",
]
