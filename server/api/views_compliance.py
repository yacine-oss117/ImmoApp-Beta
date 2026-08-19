"""Compliance export/delete endpoints with step-up proof binding."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.api.throttling import HeaderScopedRateThrottle as ScopedRateThrottle
from server.services import compliance_jobs
from server.services.errors import NotFoundError, PermissionDeniedError

from .rbac import require_owner
from .request_schemas_compliance import ComplianceJobRequestSerializer
from .step_up import parse_step_up_claims, step_up_iat_to_datetime
from .validation import validate_payload
from .view_helpers import error, safe_error_message, safe_forbidden_message, safe_not_found_message

ViewFunc = TypeVar("ViewFunc", bound=Callable[..., object])


def _compliance_export_throttle(view: ViewFunc) -> ViewFunc:
    view.throttle_scope = "compliance_export"  # type: ignore[attr-defined]
    return view


def _compliance_delete_throttle(view: ViewFunc) -> ViewFunc:
    view.throttle_scope = "compliance_delete"  # type: ignore[attr-defined]
    return view


@route("compliance/users/<int:user_id>/export/", order=158)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_compliance_export_throttle
def compliance_user_export(request: Request, user_id: int) -> Response:
    deny = require_owner(request)
    if deny:
        return deny
    claims, step_up_error = parse_step_up_claims(request)
    if step_up_error is not None:
        return step_up_error
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        ComplianceJobRequestSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    try:
        step_up_verified_at = step_up_iat_to_datetime(claims or {})
        created = compliance_jobs.create_export_job(
            actor=request.user,
            target_user_id=user_id,
            step_up_verified_at=step_up_verified_at,
            reason=str((payload or {}).get("reason") or ""),
        )
    except compliance_jobs.JobAlreadyActiveError as exc:
        return Response(
            {"code": "JOB_ALREADY_ACTIVE", "detail": str(exc), "job_id": exc.job_id},
            status=status.HTTP_409_CONFLICT,
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    from server.api.tasks_compliance import run_compliance_export_task

    run_compliance_export_task.delay(str(created["job_id"]))
    return Response(created, status=status.HTTP_202_ACCEPTED)


@route("compliance/users/<int:user_id>/delete/", order=159)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([ScopedRateThrottle])
@_compliance_delete_throttle
def compliance_user_delete(request: Request, user_id: int) -> Response:
    deny = require_owner(request)
    if deny:
        return deny
    claims, step_up_error = parse_step_up_claims(request)
    if step_up_error is not None:
        return step_up_error
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        ComplianceJobRequestSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    try:
        step_up_verified_at = step_up_iat_to_datetime(claims or {})
        created = compliance_jobs.create_delete_job(
            actor=request.user,
            target_user_id=user_id,
            step_up_verified_at=step_up_verified_at,
            reason=str((payload or {}).get("reason") or ""),
        )
    except compliance_jobs.JobAlreadyActiveError as exc:
        return Response(
            {"code": "JOB_ALREADY_ACTIVE", "detail": str(exc), "job_id": exc.job_id},
            status=status.HTTP_409_CONFLICT,
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    from server.api.tasks_compliance import run_compliance_delete_task

    run_compliance_delete_task.delay(str(created["job_id"]))
    return Response(created, status=status.HTTP_202_ACCEPTED)


@route("compliance/jobs/<uuid:job_id>/", order=160)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def compliance_job_status(request: Request, job_id: UUID) -> Response:
    deny = require_owner(request)
    if deny:
        return deny
    try:
        item = compliance_jobs.get_job(actor=request.user, job_id=str(job_id))
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    return Response(item, status=status.HTTP_200_OK)


@route("compliance/exports/<uuid:job_id>/download/", order=161)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def compliance_export_download(request: Request, job_id: UUID) -> Response:
    deny = require_owner(request)
    if deny:
        return deny
    try:
        content_type, body = compliance_jobs.get_export_artifact(
            actor=request.user, job_id=str(job_id)
        )
    except PermissionDeniedError as exc:
        return error(safe_forbidden_message(exc), status.HTTP_403_FORBIDDEN)
    except NotFoundError as exc:
        return error(safe_not_found_message(exc), status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_409_CONFLICT)
    response = HttpResponse(body, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="compliance_export_{job_id}.json"'
    return response


__all__ = [
    "compliance_export_download",
    "compliance_job_status",
    "compliance_user_delete",
    "compliance_user_export",
]
