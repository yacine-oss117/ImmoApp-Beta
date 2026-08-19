"""
Database, cache, channels, and Celery settings.
"""

from __future__ import annotations

import os

from .settings_base import DEBUG

_SKIP_CELERY_IMPORTS = os.environ.get("IMMOAPP_SKIP_CELERY_APP", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

if _SKIP_CELERY_IMPORTS:

    def crontab(*, minute: int = 0, hour: int = 0, **_: object) -> dict[str, int]:
        return {"minute": int(minute), "hour": int(hour)}

    class Queue:  # pragma: no cover - import-time compatibility shim for non-celery contexts
        def __init__(self, name: str, *args: object, **kwargs: object) -> None:
            self.name = name
            self.args = args
            self.kwargs = kwargs

else:
    from celery.schedules import crontab  # type: ignore[no-redef]
    from kombu import Queue  # type: ignore[no-redef]


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


DB_NAME = _require_env("POSTGRES_DB")
DB_USER = _require_env("POSTGRES_USER")
DB_PASSWORD = _require_env("POSTGRES_PASSWORD")
DB_HOST = os.environ.get("POSTGRES_HOST", "localhost")
DB_PORT = os.environ.get("POSTGRES_PORT", "5432")
_default_conn_max_age = "0" if DEBUG else "60"
DB_CONN_MAX_AGE = int(os.environ.get("POSTGRES_CONN_MAX_AGE", _default_conn_max_age))

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": DB_NAME,
        "USER": DB_USER,
        "PASSWORD": DB_PASSWORD,
        "HOST": DB_HOST,
        "PORT": DB_PORT,
        "CONN_MAX_AGE": DB_CONN_MAX_AGE,
    }
}

VALKEY_URL = os.environ.get("VALKEY_URL", "redis://localhost:6379/1")
CHANNEL_LAYER_URL = os.environ.get(
    "CHANNEL_LAYER_URL",
    os.environ.get("VALKEY_URL", "redis://localhost:6379/3"),
)

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": VALKEY_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [CHANNEL_LAYER_URL]},
    }
}

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL")
if not CELERY_BROKER_URL:
    if DEBUG:
        CELERY_BROKER_URL = "amqp://immoapp:immoapp@localhost:5672//"
    else:
        raise RuntimeError("CELERY_BROKER_URL is required when DEBUG=False")
CELERY_RESULT_BACKEND = os.environ.get(
    "CELERY_RESULT_BACKEND",
    os.environ.get("VALKEY_URL", "redis://localhost:6379/2"),
)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
# default OFF; only enable eager for local/dev test runs
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "0") == "1"
CELERY_TASK_EAGER_PROPAGATES = CELERY_TASK_ALWAYS_EAGER
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = int(os.environ.get("CELERY_WORKER_PREFETCH_MULTIPLIER", "1"))
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_SOFT_TIME_LIMIT = int(os.environ.get("CELERY_TASK_SOFT_TIME_LIMIT", "240"))
CELERY_TASK_TIME_LIMIT = int(os.environ.get("CELERY_TASK_TIME_LIMIT", "300"))
CELERY_TASK_DEFAULT_EXCHANGE = "immoapp.tasks"
CELERY_TASK_DEFAULT_EXCHANGE_TYPE = "direct"
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_DEFAULT_ROUTING_KEY = "default"
CELERY_TASK_QUEUES = (
    Queue("default", routing_key="default"),
    Queue("maintenance", routing_key="maintenance"),
    Queue("imports", routing_key="imports"),
    Queue("rebuild_batch", routing_key="rebuild_batch"),
    Queue("match_pairs", routing_key="match_pairs"),
)
CELERY_TASK_ROUTES = {
    "flush_email_outbox": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_maintenance.purge_old_audit_logs_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_maintenance.purge_old_auth_events_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_maintenance.purge_deleted_storage_objects_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_maintenance.purge_pending_storage_objects_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_maintenance.purge_idempotency_records_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_maintenance.expire_pending_registration_requests_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_maintenance.requeue_expired_import_phases_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_maintenance.prune_importer_runtime_artifacts_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_maintenance.repair_stalled_import_jobs_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_notifications.purge_notifications_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_integrity.match_pairs_janitor_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "snapshot_postgres_match_health": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_import.import_parse_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_import.import_execute_task": {
        "queue": "imports",
        "routing_key": "imports",
    },
    "server.api.tasks_import.import_prepare_phase_task": {
        "queue": "imports",
        "routing_key": "imports",
    },
    "server.api.tasks_import.import_plan_chunk_task": {
        "queue": "imports",
        "routing_key": "imports",
    },
    "server.api.tasks_import.import_load_chunk_task": {
        "queue": "imports",
        "routing_key": "imports",
    },
    "server.api.tasks_import.import_finalize_job_task": {
        "queue": "imports",
        "routing_key": "imports",
    },
    "server.api.tasks_import_review.import_review_submit_task": {
        "queue": "imports",
        "routing_key": "imports",
    },
    "server.api.tasks_ale.purge_ale_pii_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_ale.ale_rotation_alert_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_ale.rotate_ale_keys_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_ale.reindex_ale_search_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_ale.rotate_ale_search_keys_task": {
        "queue": "maintenance",
        "routing_key": "maintenance",
    },
    "server.api.tasks_match_cache.rebuild_match_cache_all": {
        "queue": "rebuild_batch",
        "routing_key": "rebuild_batch",
    },
    "server.api.tasks_match_cache.rebuild_match_cache_dirty": {
        "queue": "rebuild_batch",
        "routing_key": "rebuild_batch",
    },
    "server.api.tasks_match_cache.rebuild_match_cache_client": {
        "queue": "rebuild_batch",
        "routing_key": "rebuild_batch",
    },
    "server.api.tasks_match_cache.rebuild_match_cache_wilaya": {
        "queue": "rebuild_batch",
        "routing_key": "rebuild_batch",
    },
    "server.api.tasks_match_pairs.rebuild_match_pairs_for_demande": {
        "queue": "match_pairs",
        "routing_key": "match_pairs",
    },
    "server.api.tasks_match_pairs.rebuild_match_pairs_for_demandes_batch": {
        "queue": "match_pairs",
        "routing_key": "match_pairs",
    },
    "server.api.tasks_match_pairs.flush_rebuild_demande_pairs_queue": {
        "queue": "match_pairs",
        "routing_key": "match_pairs",
    },
    "server.api.tasks_match_pairs.expand_match_pairs_for_demande": {
        "queue": "match_pairs",
        "routing_key": "match_pairs",
    },
    "server.api.tasks_match_pairs.rebuild_match_pairs_for_wilaya": {
        "queue": "match_pairs",
        "routing_key": "match_pairs",
    },
    "server.api.tasks_match_pairs.rebuild_match_pairs_for_client": {
        "queue": "match_pairs",
        "routing_key": "match_pairs",
    },
    "server.api.tasks_match_pairs.rebuild_match_pairs_for_offer": {
        "queue": "match_pairs",
        "routing_key": "match_pairs",
    },
}

CELERY_BEAT_SCHEDULE = {
    "flush-email-outbox": {
        "task": "flush_email_outbox",
        "schedule": 30.0,
        "options": {"queue": "maintenance"},
    },
    "purge-old-audit-logs-daily": {
        "task": "server.api.tasks_maintenance.purge_old_audit_logs_task",
        "schedule": crontab(minute=0, hour=2),
        "kwargs": {"retention_days": 90},
        "options": {"queue": "maintenance"},
    },
    "purge-old-auth-events-daily": {
        "task": "server.api.tasks_maintenance.purge_old_auth_events_task",
        "schedule": crontab(minute=20, hour=2),
        "kwargs": {"retention_days": int(os.environ.get("AUTH_EVENT_RETENTION_DAYS", "180"))},
        "options": {"queue": "maintenance"},
    },
    "requeue-expired-import-phases": {
        "task": "server.api.tasks_maintenance.requeue_expired_import_phases_task",
        "schedule": 30.0,
        "options": {"queue": "maintenance"},
    },
    "prune-importer-runtime-artifacts": {
        "task": "server.api.tasks_maintenance.prune_importer_runtime_artifacts_task",
        "schedule": 600.0,
        "options": {"queue": "maintenance"},
    },
    "repair-stalled-import-jobs": {
        "task": "server.api.tasks_maintenance.repair_stalled_import_jobs_task",
        "schedule": 60.0,
        "options": {"queue": "maintenance"},
    },
    "purge-deleted-storage-daily": {
        "task": "server.api.tasks_maintenance.purge_deleted_storage_objects_task",
        "schedule": crontab(minute=40, hour=2),
        "kwargs": {"retention_days": 30, "batch_size": 200},
        "options": {"queue": "maintenance"},
    },
    "purge-pending-storage-daily": {
        "task": "server.api.tasks_maintenance.purge_pending_storage_objects_task",
        "schedule": crontab(minute=0, hour=3),
        "kwargs": {"retention_hours": 24, "batch_size": 200},
        "options": {"queue": "maintenance"},
    },
    "purge-ale-pii-daily": {
        "task": "server.api.tasks_ale.purge_ale_pii_task",
        "schedule": crontab(minute=20, hour=3),
        "kwargs": {"retention_days": int(os.environ.get("ALE_PII_RETENTION_DAYS", "365"))},
        "options": {"queue": "maintenance"},
    },
    "ale-rotation-alert-daily": {
        "task": "server.api.tasks_ale.ale_rotation_alert_task",
        "schedule": crontab(minute=40, hour=3),
        "options": {"queue": "maintenance"},
    },
    "ale-autorotate-weekly": {
        "task": "server.api.tasks_ale.rotate_ale_keys_task",
        "schedule": crontab(minute=0, hour=4, day_of_week=0),
        "options": {"queue": "maintenance"},
    },
    "ale-autoreindex-weekly": {
        "task": "server.api.tasks_ale.reindex_ale_search_task",
        "schedule": crontab(minute=30, hour=4, day_of_week=0),
        "options": {"queue": "maintenance"},
    },
    "match-janitor": {
        "task": "server.api.tasks_integrity.match_pairs_janitor_task",
        "schedule": 900.0,  # every 15 minutes
        "options": {"queue": "maintenance"},
    },
    "snapshot-postgres-match-health": {
        "task": "snapshot_postgres_match_health",
        "schedule": float(os.environ.get("IMMOAPP_MATCH_HEALTH_SAMPLE_INTERVAL_SECONDS", "5")),
        "options": {"queue": "maintenance"},
    },
    "purge-notifications-daily": {
        "task": "server.api.tasks_notifications.purge_notifications_task",
        "schedule": crontab(minute=10, hour=3),
        "kwargs": {"retention_days": 60},
        "options": {"queue": "maintenance"},
    },
    "purge-idempotency-daily": {
        "task": "server.api.tasks_maintenance.purge_idempotency_records_task",
        "schedule": crontab(minute=20, hour=3),
        "kwargs": {"limit": 5000},
        "options": {"queue": "maintenance"},
    },
    "expire-pending-registration-daily": {
        "task": "server.api.tasks_maintenance.expire_pending_registration_requests_task",
        "schedule": crontab(minute=50, hour=3),
        "kwargs": {
            "older_than_days": int(os.environ.get("IMMOAPP_PENDING_REGISTRATION_EXPIRY_DAYS", "30"))
        },
        "options": {"queue": "maintenance"},
    },
}

__all__ = [
    "CACHES",
    "CELERY_ACCEPT_CONTENT",
    "CELERY_BEAT_SCHEDULE",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "CELERY_RESULT_SERIALIZER",
    "CELERY_TASK_ACKS_LATE",
    "CELERY_TASK_ALWAYS_EAGER",
    "CELERY_TASK_DEFAULT_EXCHANGE",
    "CELERY_TASK_DEFAULT_EXCHANGE_TYPE",
    "CELERY_TASK_EAGER_PROPAGATES",
    "CELERY_TASK_DEFAULT_QUEUE",
    "CELERY_TASK_DEFAULT_ROUTING_KEY",
    "CELERY_TASK_QUEUES",
    "CELERY_TASK_ROUTES",
    "CELERY_TASK_REJECT_ON_WORKER_LOST",
    "CELERY_TASK_SOFT_TIME_LIMIT",
    "CELERY_TASK_SERIALIZER",
    "CELERY_TASK_TIME_LIMIT",
    "CELERY_TASK_TRACK_STARTED",
    "CELERY_WORKER_PREFETCH_MULTIPLIER",
    "CHANNEL_LAYERS",
    "CHANNEL_LAYER_URL",
    "DATABASES",
    "DB_CONN_MAX_AGE",
    "DB_HOST",
    "DB_NAME",
    "DB_PASSWORD",
    "DB_PORT",
    "DB_USER",
    "VALKEY_URL",
]
