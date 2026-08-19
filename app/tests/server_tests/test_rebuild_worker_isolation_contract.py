from __future__ import annotations

from pathlib import Path

from scripts.repo_layout import COMPOSE_YML


def test_rebuild_tasks_route_to_rebuild_batch_queue() -> None:
    text = Path("server/immoapp_server/settings_database.py").read_text(encoding="utf-8")
    assert "CELERY_TASK_ROUTES = {" in text
    for task_name in (
        "server.api.tasks_match_cache.rebuild_match_cache_all",
        "server.api.tasks_match_cache.rebuild_match_cache_dirty",
        "server.api.tasks_match_cache.rebuild_match_cache_client",
        "server.api.tasks_match_cache.rebuild_match_cache_wilaya",
    ):
        assert f'"{task_name}":' in text
    assert '"queue": "rebuild_batch"' in text
    assert '"routing_key": "rebuild_batch"' in text


def test_compose_has_dedicated_rebuild_worker_and_main_worker_excludes_queue() -> None:
    text = COMPOSE_YML.read_text(encoding="utf-8")
    assert "worker-rebuild:" in text
    assert (
        "-Q rebuild_batch -c ${CELERY_REBUILD_CONCURRENCY_DOCKER:?hub_runtime_profile_required}"
        in text
    )
    assert "worker-match:" in text
    assert (
        "-Q match_pairs -c ${CELERY_MATCH_PAIRS_CONCURRENCY_DOCKER:?hub_runtime_profile_required}"
        in text
    )
    assert (
        "worker -l info -Q celery,default,maintenance -c ${CELERY_WORKER_CONCURRENCY_DOCKER:?hub_runtime_profile_required}"
        in text
    )


def test_stack_actions_start_and_log_rebuild_worker() -> None:
    text = Path("scripts/stack.ps1").read_text(encoding="utf-8")
    required_tokens = (
        '"up-app"',
        '"up"',
        '"up-full"',
        '"restart-app"',
        '"logs"',
        '$appRuntimeServices = @("web", "worker", "worker-import", "worker-rebuild", "worker-match", "beat")',
        '$appRuntimeServicesWithFrontDoor += "caddy"',
        '@("up", "-d", "--force-recreate") + $appRuntimeServicesWithFrontDoor',
        '@("logs", "-f", "--tail=200") + $appRuntimeServicesWithFrontDoor',
    )
    for token in required_tokens:
        assert token in text


def test_celery_queue_routing_keys_are_isolated() -> None:
    text = Path("server/immoapp_server/settings_database.py").read_text(encoding="utf-8")
    assert 'CELERY_TASK_DEFAULT_EXCHANGE = "immoapp.tasks"' in text
    assert 'CELERY_TASK_DEFAULT_EXCHANGE_TYPE = "direct"' in text
    assert 'CELERY_TASK_DEFAULT_ROUTING_KEY = "default"' in text
    assert 'Queue("default", routing_key="default")' in text
    assert 'Queue("maintenance", routing_key="maintenance")' in text
    assert 'Queue("rebuild_batch", routing_key="rebuild_batch")' in text
    assert 'Queue("match_pairs", routing_key="match_pairs")' in text


def test_match_pair_tasks_route_to_match_pairs_queue() -> None:
    text = Path("server/immoapp_server/settings_database.py").read_text(encoding="utf-8")
    required_routes = (
        '"server.api.tasks_match_pairs.rebuild_match_pairs_for_demande": {',
        '"server.api.tasks_match_pairs.flush_rebuild_demande_pairs_queue": {',
        '"server.api.tasks_match_pairs.expand_match_pairs_for_demande": {',
        '"server.api.tasks_match_pairs.rebuild_match_pairs_for_wilaya": {',
        '"server.api.tasks_match_pairs.rebuild_match_pairs_for_client": {',
        '"server.api.tasks_match_pairs.rebuild_match_pairs_for_offer": {',
    )
    for route in required_routes:
        assert route in text
    assert '"queue": "match_pairs"' in text
    assert '"routing_key": "match_pairs"' in text


def test_maintenance_tasks_route_to_maintenance_queue() -> None:
    text = Path("server/immoapp_server/settings_database.py").read_text(encoding="utf-8")
    required_routes = (
        '"flush_email_outbox": {',
        '"server.api.tasks_maintenance.purge_old_audit_logs_task": {',
        '"server.api.tasks_maintenance.purge_old_auth_events_task": {',
        '"server.api.tasks_maintenance.purge_deleted_storage_objects_task": {',
        '"server.api.tasks_maintenance.purge_pending_storage_objects_task": {',
        '"server.api.tasks_maintenance.purge_idempotency_records_task": {',
        '"server.api.tasks_maintenance.expire_pending_registration_requests_task": {',
        '"server.api.tasks_notifications.purge_notifications_task": {',
        '"server.api.tasks_integrity.match_pairs_janitor_task": {',
        '"snapshot_postgres_match_health": {',
        '"server.api.tasks_ale.purge_ale_pii_task": {',
        '"server.api.tasks_ale.ale_rotation_alert_task": {',
        '"server.api.tasks_ale.rotate_ale_keys_task": {',
        '"server.api.tasks_ale.reindex_ale_search_task": {',
        '"server.api.tasks_ale.rotate_ale_search_keys_task": {',
    )
    for route in required_routes:
        assert route in text
    assert '"queue": "maintenance"' in text
    assert '"routing_key": "maintenance"' in text
