"""
Celery application setup for the ImmoApp server.
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import Any

from celery import Celery
from celery.signals import task_failure, task_revoked, task_success

from server.immoapp_server.observability import setup_observability


def _load_runtime_secrets() -> None:
    try:
        module = importlib.import_module("server.secret_store")
    except ModuleNotFoundError:  # pragma: no cover - fallback when running from server/ cwd
        module = importlib.import_module("secret_store")
    module.load_secrets()


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
_load_runtime_secrets()
setup_observability(service_name=os.environ.get("OTEL_WORKER_SERVICE_NAME", "immoapp-worker"))
from server.services.cache_layers import ensure_single_flight_backend_ready  # noqa: E402

ensure_single_flight_backend_ready()

celery_app = Celery("immoapp_server")
celery_app.config_from_object("django.conf:settings", namespace="CELERY")
celery_app.autodiscover_tasks()

logger = logging.getLogger(__name__)


@task_failure.connect
def _on_task_failure(
    sender: Any = None,
    task_id: str | None = None,
    exception: Exception | None = None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    traceback: Any = None,
    einfo: Any = None,
    **_extras: Any,
) -> None:
    try:
        from server.pg.task_failures import record_task_failure

        schema_name = None
        agency_id = None
        if isinstance(kwargs, dict):
            schema_name = kwargs.get("schema")
            agency_id = kwargs.get("agency_id")
        record_task_failure(
            task_id=task_id,
            name=getattr(sender, "name", None),
            args=args,
            kwargs=kwargs,
            exception=exception,
            traceback_text=str(einfo) if einfo else None,
            schema_name=schema_name,
            agency_id=agency_id if isinstance(agency_id, int) else None,
        )
        try:
            from server.api.task_events import notify_task_status

            notify_task_status(task_id or "", "FAILURE", result={"error": str(exception or "")})
        except Exception:
            logger.warning("Failed to publish task failure", exc_info=True)
    except Exception:
        logger.warning("Failed to record task failure", exc_info=True)


@task_success.connect
def _on_task_success(
    sender: Any = None,
    result: Any = None,
    task_id: str | None = None,
    **_extras: Any,
) -> None:
    try:
        from server.api.task_events import notify_task_status

        notify_task_status(task_id or "", "SUCCESS", result=result)
    except Exception:
        logger.warning("Failed to publish task success", exc_info=True)


@task_revoked.connect
def _on_task_revoked(
    sender: Any = None,
    request: Any = None,
    terminated: bool | None = None,
    signum: int | None = None,
    expired: bool | None = None,
    **_extras: Any,
) -> None:
    task_id = None
    try:
        task_id = getattr(request, "id", None)
    except Exception:
        task_id = None
    try:
        from server.api.task_events import notify_task_status

        notify_task_status(task_id or "", "REVOKED", result={"terminated": terminated})
    except Exception:
        logger.warning("Failed to publish task revoked", exc_info=True)


__all__ = ["celery_app"]
