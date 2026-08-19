"""
WhatsApp template API views.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import templates

from .idempotency import check_idempotency, store_idempotency
from .rbac import require_manager
from .request_schemas import TemplatePayloadSerializer
from .validation import validate_payload
from .view_helpers import actor, error, list_response


@route("templates/", order=86)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def templates_list(request: Request) -> Response:
    """List or create templates."""
    if request.method == "POST":
        idem_ctx, idem_response = check_idempotency(request)
        if idem_response is not None:
            return idem_response
        deny = require_manager(request)
        if deny:
            return deny
        payload, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            TemplatePayloadSerializer,
        )
        if error_response:
            return error_response
        payload = payload or {}
        name = str(payload.get("name") or "")
        template = str(payload.get("template") or "")
        template_id = templates.create_template(name, template, actor=actor(request))
        response = Response({"id": template_id}, status=status.HTTP_201_CREATED)
        return store_idempotency(idem_ctx, response, request)
    return list_response(templates.get_all_templates())


@route("templates/<int:template_id>/", order=88)
@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def template_detail(request: Request, template_id: int) -> Response:
    """Get, update, or delete a template."""
    if request.method == "GET":
        template = templates.get_template_by_id(template_id)
        if not template:
            return error("Template not found", status.HTTP_404_NOT_FOUND)
        return Response(template)
    if request.method == "PUT":
        idem_ctx, idem_response = check_idempotency(request)
        if idem_response is not None:
            return idem_response
        deny = require_manager(request)
        if deny:
            return deny
        payload, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            TemplatePayloadSerializer,
            partial=True,
        )
        if error_response:
            return error_response
        payload = payload or {}
        name = str(payload.get("name") or "")
        template_text = str(payload.get("template") or "")
        if not name or not template_text:
            return error("name and template are required", status.HTTP_400_BAD_REQUEST)
        ok = templates.update_template(
            template_id,
            name,
            template_text,
            actor=actor(request),
        )
        response = Response({"updated": ok})
        return store_idempotency(idem_ctx, response, request)
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response is not None:
        return idem_response
    deny = require_manager(request)
    if deny:
        return deny
    ok = templates.delete_template(template_id, actor=actor(request))
    response = Response({"deleted": ok})
    return store_idempotency(idem_ctx, response, request)


@route("templates/reset-defaults/", order=89)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def templates_reset(request: Request) -> Response:
    """Reset templates to defaults."""
    idem_ctx, idem_response = check_idempotency(request)
    if idem_response is not None:
        return idem_response
    deny = require_manager(request)
    if deny:
        return deny
    templates.reset_default_templates(actor=actor(request))
    response = Response(status=status.HTTP_204_NO_CONTENT)
    return store_idempotency(idem_ctx, response, request)
