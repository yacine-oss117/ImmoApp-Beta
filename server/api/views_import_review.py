"""Import review/correction endpoints."""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.request_schemas_import import ImportReviewSubmitSerializer
from server.api.route_registry import route
from server.api.task_registry import register_task
from server.api.tasks import import_review_submit_task
from server.api.tasks_core import enqueue_import_task
from server.api.validation import validate_payload
from server.api.view_helpers import error, request_correlation_id, safe_forbidden_message
from server.services.import_parsers import normalize_import_entity_type
from server.services.import_review_compatibility import enrich_review_items
from server.services.import_review_execution_service import ImportReviewSubmitConflictError
from server.services.import_review_payloads import (
    allowed_review_entity_types,
    build_import_review_response,
    build_review_capacity_exceeded_response,
    build_review_duplicate_conflict_response,
    normalize_review_submit_request,
    query_bool_param,
    query_int_param,
)
from server.services.import_review_store import (
    ensure_review_state,
    paged_review_groups,
    paged_review_items,
    review_count_snapshot,
)
from server.services.import_service import ImportPermissionError, ImportService, get_active_schema
from server.services.import_ui_summary import review_state_for_payload


@route("import/<str:session_id>/review/", order=133)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def import_review(request: Request, session_id: str) -> Response:
    """Get grouped, paged rows that need review for an import job."""
    try:
        service = ImportService(request.user)
    except ImportPermissionError as e:
        return error(safe_forbidden_message(e), status.HTTP_403_FORBIDDEN)

    job = service.get_job(session_id)
    if not job:
        return error("Session not found", status.HTTP_404_NOT_FOUND)

    snapshot = ensure_review_state(job) or review_count_snapshot(job)
    page = query_int_param(request, "page", 1)
    page_size = query_int_param(request, "page_size", 50)
    mode = str(request.query_params.get("mode", "groups") or "groups").strip().lower()
    issue_group = str(request.query_params.get("issue_group", "") or "").strip() or None
    search = str(request.query_params.get("search", "") or "").strip()
    pending_only = query_bool_param(request, "pending_only", True)

    review_groups, review_page = paged_review_groups(
        job=job,
        page=page,
        page_size=page_size,
        issue_group=issue_group,
        search=search,
        pending_only=pending_only,
    )
    requested_group_key = str(request.query_params.get("group_key", "") or "").strip()
    visible_group_keys = {
        str(dict(group or {}).get("group_key", "") or "") for group in list(review_groups or [])
    }
    if requested_group_key and requested_group_key in visible_group_keys:
        selected_group_key = requested_group_key
    else:
        selected_group_key = (
            str(review_groups[0].get("group_key", "") or "") if review_groups else ""
        )
    if mode == "items":
        review_items, items_page = paged_review_items(
            job=job,
            page=page,
            page_size=page_size,
            group_key=selected_group_key or None,
            issue_group=issue_group,
            search=search,
            pending_only=pending_only,
        )
    else:
        review_items, items_page = paged_review_items(
            job=job,
            page=1,
            page_size=200,
            group_key=selected_group_key or None,
            issue_group=None,
            search="",
            pending_only=pending_only,
        )
    normalized_items, legacy_rows = enrich_review_items(job=job, review_items=review_items)
    return Response(
        build_import_review_response(
            job=job,
            snapshot=snapshot,
            review_groups=review_groups,
            review_page=items_page if mode == "items" else review_page,
            review_items=normalized_items,
            review_rows=legacy_rows,
            review_mode=mode,
            selected_group_key=selected_group_key or None,
            issue_group=issue_group,
            search=search,
            pending_only=pending_only,
        )
    )


@route("import/<str:session_id>/review/submit/", order=134)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def import_review_submit(request: Request, session_id: str) -> Response:
    """Submit corrections for grouped review rows and import them."""
    try:
        service = ImportService(request.user)
    except ImportPermissionError as e:
        return error(safe_forbidden_message(e), status.HTTP_403_FORBIDDEN)

    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        ImportReviewSubmitSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    data = payload or {}

    job = service.get_job(session_id)
    if not job:
        return error("Session not found", status.HTTP_404_NOT_FOUND)

    snapshot = ensure_review_state(job) or review_count_snapshot(job)
    review_state = review_state_for_payload(
        progress_detail=job.progress_detail or {},
        result_summary=job.result_summary or {},
    )
    overflow_blocking = bool(
        (job.result_summary or {}).get("overflow_blocking", False)
        or (job.progress_detail or {}).get("overflow_blocking", False)
        or review_state == "emergency_overflow"
    )
    if overflow_blocking:
        return Response(
            build_review_capacity_exceeded_response(job=job, review_state=review_state),
            status=status.HTTP_409_CONFLICT,
        )
    if int(snapshot.visible_review_count or 0) <= 0:
        return error("No rows to review", status.HTTP_400_BAD_REQUEST)

    normalized_request, validation_error = normalize_review_submit_request(
        data=data,
        allowed_entity_types=allowed_review_entity_types(job),
    )
    if validation_error:
        return error(validation_error, status.HTTP_400_BAD_REQUEST)
    assert normalized_request is not None

    entity_type = normalize_import_entity_type(job.detected_entity)
    try:
        accepted_payload = service.submit_review(
            job=job,
            entity_type=entity_type,
            request_payload=normalized_request,
            enqueue_review_submit_task_fn=lambda **kwargs: enqueue_import_task(
                import_review_submit_task, **kwargs
            ),
            register_task_fn=register_task,
            schema=get_active_schema(),
            correlation_id=request_correlation_id(request),
        )
    except ImportReviewSubmitConflictError as exc:
        return Response(
            build_review_duplicate_conflict_response(
                job=job,
                detail=exc.detail,
                row_conflicts=exc.row_conflicts,
                conflict_groups=exc.conflict_groups,
                conflict_item_ids=exc.conflict_item_ids,
                correlation_id=request_correlation_id(request) or "",
                snapshot=snapshot,
                review_state=review_state,
            ),
            status=status.HTTP_409_CONFLICT,
        )

    return Response(accepted_payload, status=status.HTTP_202_ACCEPTED)


__all__ = ["import_review", "import_review_submit"]
