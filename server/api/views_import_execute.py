"""Import execution/status endpoints."""

from __future__ import annotations

import uuid

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.request_schemas import ImportExecuteSerializer
from server.api.route_registry import route
from server.api.task_registry import register_task
from server.api.tasks import import_execute_task
from server.api.tasks_core import enqueue_import_task
from server.api.validation import validate_payload
from server.api.view_helpers import error, request_correlation_id, safe_forbidden_message
from server.immoapp_server.business_metrics_imports import (
    record_import_execution_budget_decision,
    record_import_execution_profile,
)
from server.imports.models import ImportJob
from server.services import e2e_control
from server.services.import_admission_service import admit_import_execute
from server.services.import_chunk_workflow import (
    initialize_distributed_workflow,
    save_workflow_payload,
)
from server.services.import_constants import normalize_duplicate_strategy
from server.services.import_decision import build_import_decision
from server.services.import_execute_request import execute_import_request
from server.services.import_execution_governor import (
    calculate_import_execution_cost,
    effective_import_runtime_profile,
)
from server.services.import_job_queue import (
    claim_execution_or_queue,
)
from server.services.import_mapping import canonicalize_column_mapping
from server.services.import_parsers import normalize_import_entity_type
from server.services.import_service import (
    ImportPermissionError,
    ImportService,
    get_active_schema,
)
from server.services.import_status_api_facade import (
    build_import_status_payload,
    cancel_import_immediately_response,
    cancel_import_request_payload,
)


@route("import/execute/", order=131)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def import_execute(request: Request) -> Response:
    """Execute the import with atomic transaction."""
    try:
        service = ImportService(request.user)
    except ImportPermissionError as e:
        return error(safe_forbidden_message(e), status.HTTP_403_FORBIDDEN)

    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        ImportExecuteSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    data = payload or {}
    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return error("session_id required", status.HTTP_400_BAD_REQUEST)

    session = service.get_job(session_id)
    if not session:
        return error("Session not found or expired", status.HTTP_404_NOT_FOUND)
    if e2e_control.e2e_test_mode_enabled():
        e2e_control.arm_pending_import_pause_for_job(
            user_id=int(service.user_id),
            job_id=str(session.id),
        )
    outcome = execute_import_request(
        request=request,
        session=session,
        user_id=service.user_id,
        agency_id=int(service.agency_id or 0),
        data=data,
        request_correlation_id_fn=request_correlation_id,
        canonicalize_column_mapping_fn=canonicalize_column_mapping,
        normalize_import_entity_type_fn=normalize_import_entity_type,
        build_import_decision_fn=build_import_decision,
        normalize_duplicate_strategy_fn=normalize_duplicate_strategy,
        calculate_import_execution_cost_fn=calculate_import_execution_cost,
        effective_import_runtime_profile_fn=effective_import_runtime_profile,
        admit_import_execute_fn=admit_import_execute,
        record_import_execution_profile_fn=record_import_execution_profile,
        record_import_execution_budget_decision_fn=record_import_execution_budget_decision,
        initialize_distributed_workflow_fn=initialize_distributed_workflow,
        save_workflow_payload_fn=save_workflow_payload,
        claim_execution_or_queue_fn=claim_execution_or_queue,
        enqueue_import_task_fn=lambda **kwargs: enqueue_import_task(import_execute_task, **kwargs),
        register_task_fn=register_task,
        get_active_schema_fn=get_active_schema,
    )
    if outcome.status_code >= 400:
        response = Response(outcome.payload, status=outcome.status_code)
        for key, value in outcome.headers.items():
            response[key] = value
        return response

    response = Response(outcome.payload, status=outcome.status_code)
    for key, value in outcome.headers.items():
        response[key] = value
    return response


@route("import/status/<str:task_id>/", order=132)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def import_status(request: Request, task_id: str) -> Response:
    """Check import task status (for async imports)."""
    try:
        service = ImportService(request.user)
    except ImportPermissionError as e:
        return error(safe_forbidden_message(e), status.HTTP_403_FORBIDDEN)

    session = None
    try:
        uuid_obj = uuid.UUID(task_id)
        session = service.get_job(str(uuid_obj))
    except ValueError:
        pass

    if not session:
        session = service.get_job_by_task_id(task_id)

    if not session:
        return error("Session not found", status.HTTP_404_NOT_FOUND)

    return Response(
        build_import_status_payload(
            session=session,
            agency_id=int(service.agency_id or 0),
        )
    )


@route("import/<str:session_id>/cancel/", order=132)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def import_cancel(request: Request, session_id: str) -> Response:
    """Cancel a queued or running import."""
    try:
        service = ImportService(request.user)
    except ImportPermissionError as e:
        return error(safe_forbidden_message(e), status.HTTP_403_FORBIDDEN)

    session = service.get_job(session_id)
    if not session:
        return error("Session not found or expired", status.HTTP_404_NOT_FOUND)
    if e2e_control.e2e_test_mode_enabled() and session.status in {
        ImportJob.Status.QUEUED,
        ImportJob.Status.RUNNING,
    }:
        e2e_control.clear_import_pause_for_job(job_id=str(session.id))
        return Response(
            cancel_import_immediately_response(
                job=session,
                user_id=service.user_id,
                agency_id=int(service.agency_id or 0),
            )
        )
    payload = cancel_import_request_payload(
        job=session,
        user_id=service.user_id,
        agency_id=int(service.agency_id or 0),
    )
    return Response(payload)
