"""
Match cache async task endpoints.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Protocol

from celery.result import AsyncResult
from rest_framework import status
from rest_framework.decorators import permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.rbac import require_owner
from server.api.route_registry import route
from server.api.secured_view import secured_api_view
from server.api.throttling import HeaderScopedRateThrottle as ScopedRateThrottle
from server.async_task_identity import build_request_async_task_identity
from server.immoapp_server.business_metrics_governance import record_queue_saturation
from server.immoapp_server.business_metrics_match import (
    record_match_cache_lookup,
)
from server.services import auth_security_alerts, rebuild_leases, tenant_resource_governor

from .request_schemas import CacheClientSerializer, CacheWilayaSerializer
from .task_registry import get_task_owner, register_task
from .tasks import (
    rebuild_match_cache_all,
    rebuild_match_cache_client,
    rebuild_match_cache_dirty,
    rebuild_match_cache_wilaya,
)
from .validation import validate_payload
from .view_helpers import agency_id, error, is_superuser, parse_int, request_correlation_id

_CACHE_ALL_DEPRECATION_WARNING = (
    '299 - "/api/v1/cache/match/all/ is deprecated; use /api/v1/cache/match/get with visible ids"'
)
_REBUILD_BACKPRESSURE_CODE = "REBUILD_BACKPRESSURE"
logger = logging.getLogger(__name__)


class EnqueuedTask(Protocol):
    id: str


def _cache_rebuild_throttle(view: Callable[..., object]) -> Callable[..., object]:
    view.throttle_scope = "cache_rebuild"  # type: ignore[attr-defined]
    return view


def _enqueue_rebuild(
    *,
    request: Request,
    job_type: str,
    scope_key: str,
    enqueue: Callable[[str, dict[str, object]], EnqueuedTask],
) -> Response:
    """Reserve a durable rebuild lease, then enqueue one Celery task."""
    user = getattr(request, "user", None)
    user_id = getattr(user, "id", None)
    scoped_agency_id = agency_id(request)
    if scoped_agency_id is None:
        return error("Agency scope is required", status.HTTP_400_BAD_REQUEST)
    task_identity = build_request_async_task_identity(request, agency_id=int(scoped_agency_id))
    if task_identity is None:
        return error("Agency scope is required", status.HTTP_400_BAD_REQUEST)
    allowed, retry_after = tenant_resource_governor.allow_expensive_work(
        budget_name="rebuild_cache",
        agency_id=int(scoped_agency_id),
    )
    if not allowed:
        record_queue_saturation(queue="rebuild_batch", outcome="backpressured")
        response = Response(
            {
                "code": _REBUILD_BACKPRESSURE_CODE,
                "detail": "Too many active rebuild jobs for this agency.",
                "retry_after_seconds": max(1, int(retry_after or 30)),
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
        response["Retry-After"] = str(max(1, int(retry_after or 30)))
        return response
    task_id = str(uuid.uuid4())
    reserve = rebuild_leases.LeaseReserveResult(
        outcome="accepted",
        task_id=task_id,
        retry_after_seconds=30,
    )
    reserve = rebuild_leases.reserve_rebuild_lease_tx(
        agency_id=int(scoped_agency_id),
        job_type=job_type,
        scope_key=scope_key,
        task_id=task_id,
    )

    if reserve.outcome == "coalesced":
        coalesced_task_id = reserve.task_id or task_id
        register_task(coalesced_task_id, user_id=user_id, agency_id=scoped_agency_id)
        response = Response(
            {
                "task_id": coalesced_task_id,
                "coalesced": True,
                "status": "accepted",
            },
            status=status.HTTP_202_ACCEPTED,
        )
        response["Retry-After"] = str(reserve.retry_after_seconds)
        return response
    if reserve.outcome == "backpressured":
        record_queue_saturation(queue="rebuild_batch", outcome="backpressured")
        try:
            auth_security_alerts.emit_security_alert(
                reason_code="rebuild_queue_saturation",
                agency_id=int(scoped_agency_id),
                user_id=int(user_id) if isinstance(user_id, int) else None,
                identifier=str(user_id) if user_id is not None else None,
                source_ip=request.META.get("REMOTE_ADDR"),
                user_agent=request.META.get("HTTP_USER_AGENT"),
                request_id=request_correlation_id(request),
                details={
                    "job_type": str(job_type),
                    "scope_key": str(scope_key),
                    "queue": "rebuild_batch",
                    "retry_after_seconds": int(reserve.retry_after_seconds),
                },
                cooldown_identity=f"{int(scoped_agency_id)}:{str(job_type)}:{str(scope_key)}",
            )
        except Exception:
            logger.warning("Failed to emit rebuild saturation alert", exc_info=True)
        response = Response(
            {
                "code": _REBUILD_BACKPRESSURE_CODE,
                "detail": "Too many active rebuild jobs for this agency.",
                "retry_after_seconds": reserve.retry_after_seconds,
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
        response["Retry-After"] = str(reserve.retry_after_seconds)
        return response

    try:
        task = enqueue(task_id, task_identity)
    except Exception as exc:
        rebuild_leases.mark_rebuild_failed_tx(
            agency_id=int(scoped_agency_id),
            task_id=task_id,
            error_message=f"enqueue_failed:{type(exc).__name__}",
        )
        return Response(
            {
                "code": "REBUILD_ENQUEUE_FAILED",
                "detail": "Unable to enqueue rebuild task.",
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    register_task(task.id, user_id=user_id, agency_id=scoped_agency_id)
    return Response(
        {
            "task_id": task.id,
            "coalesced": False,
            "status": "accepted",
        },
        status=status.HTTP_202_ACCEPTED,
    )


@route("cache/match/all/", order=54)
@secured_api_view(
    ["GET"],
    permission_classes=[IsAuthenticated],
    throttle_classes=[ScopedRateThrottle],
)
def match_cache_all(request: Request) -> Response:
    """Retired endpoint: full cache scans are no longer exposed."""
    _ = request
    record_match_cache_lookup(
        cache_name="match_counts_cache_all_endpoint",
        outcome="retired_call",
    )
    response = Response(
        {
            "error": "ENDPOINT_RETIRED",
            "replacement": ["/api/v1/cache/match/get", "/api/v1/cache/match/batch"],
            "doc": "CACHE_MATCH_ALL_RETIRED",
        },
        status=status.HTTP_410_GONE,
    )
    response["Deprecation"] = "true"
    response["Warning"] = _CACHE_ALL_DEPRECATION_WARNING
    return response


@route("cache/match/rebuild/", order=61)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_cache_rebuild_throttle
def match_cache_rebuild_all(request: Request) -> Response:
    """Trigger a full cache rebuild."""
    deny = require_owner(request)
    if deny:
        return deny
    return _enqueue_rebuild(
        request=request,
        job_type="all",
        scope_key="_",
        enqueue=lambda task_id, task_identity: rebuild_match_cache_all.apply_async(
            kwargs={
                **task_identity,
                "lease_task_id": task_id,
            },
            queue="rebuild_batch",
            task_id=task_id,
        ),
    )


@route("cache/match/rebuild/dirty/", order=62)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_cache_rebuild_throttle
def match_cache_rebuild_dirty(request: Request) -> Response:
    """Trigger a cache rebuild for dirty rows."""
    deny = require_owner(request)
    if deny:
        return deny
    return _enqueue_rebuild(
        request=request,
        job_type="dirty",
        scope_key="_",
        enqueue=lambda task_id, task_identity: rebuild_match_cache_dirty.apply_async(
            kwargs={
                **task_identity,
                "lease_task_id": task_id,
            },
            queue="rebuild_batch",
            task_id=task_id,
        ),
    )


@route("cache/match/rebuild/client/", order=63)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_cache_rebuild_throttle
def match_cache_rebuild_client(request: Request) -> Response:
    """Trigger a cache rebuild for a client."""
    deny = require_owner(request)
    if deny:
        return deny
    validated, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        CacheClientSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    client_id_raw = (validated or {}).get("client_id")
    client_id = client_id_raw if isinstance(client_id_raw, int) else 0
    return _enqueue_rebuild(
        request=request,
        job_type="client",
        scope_key=f"client:{client_id}",
        enqueue=lambda task_id, task_identity: rebuild_match_cache_client.apply_async(
            args=(client_id,),
            kwargs={
                **task_identity,
                "lease_task_id": task_id,
            },
            queue="rebuild_batch",
            task_id=task_id,
        ),
    )


@route("cache/match/rebuild/wilaya/", order=64)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_cache_rebuild_throttle
def match_cache_rebuild_wilaya(request: Request) -> Response:
    """Trigger a cache rebuild for a wilaya."""
    deny = require_owner(request)
    if deny:
        return deny
    validated, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        CacheWilayaSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    validated = validated or {}
    wilaya_id_raw = validated.get("wilaya_id")
    wilaya_id = parse_int(wilaya_id_raw) if isinstance(wilaya_id_raw, str) else None
    wilaya = validated.get("wilaya")
    scope_key = (
        f"wilaya:{int(wilaya_id or 0)}"
        if wilaya_id is not None
        else f"wilaya:{str(wilaya or '').strip().lower()}"
    )
    return _enqueue_rebuild(
        request=request,
        job_type="wilaya",
        scope_key=scope_key or "_",
        enqueue=lambda task_id, task_identity: rebuild_match_cache_wilaya.apply_async(
            args=(wilaya_id,),
            kwargs={
                "wilaya": str(wilaya) if wilaya is not None else None,
                **task_identity,
                "lease_task_id": task_id,
            },
            queue="rebuild_batch",
            task_id=task_id,
        ),
    )


@route("tasks/<str:task_id>/", order=65)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def task_status(request: Request, task_id: str) -> Response:
    """Return Celery task status."""
    owner = get_task_owner(task_id)
    if not owner and not is_superuser(request):
        return error("Task not found", status.HTTP_404_NOT_FOUND)

    if owner:
        user_agency = agency_id(request)
        task_agency = owner.get("agency_id")

        allowed = is_superuser(request)
        if not allowed and task_agency is not None:
            allowed = user_agency == task_agency

        if not allowed:
            return error("Forbidden", status.HTTP_403_FORBIDDEN)

    result = AsyncResult(task_id)
    payload = {"task_id": task_id, "status": result.status}
    if result.successful():
        payload["result"] = result.result
    return Response(payload)


__all__ = [
    "match_cache_all",
    "match_cache_rebuild_all",
    "match_cache_rebuild_client",
    "match_cache_rebuild_dirty",
    "match_cache_rebuild_wilaya",
    "task_status",
]


match_cache_all.throttle_scope = "match_cache_all"  # type: ignore[attr-defined]
