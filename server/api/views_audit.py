"""
Audit log API views.
"""

from __future__ import annotations

from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import audit, auth_events

from .rbac import require_manager, require_superuser
from .response_schemas import AuditResponseSerializer, AuthSecurityEventResponseSerializer
from .view_helpers import (
    actor,
    list_response,
    parse_int,
    parse_timestamp,
    require_confirmation,
)


@route("audit/logs/", order=110)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def audit_logs(request: Request) -> Response:
    """Return audit logs."""
    deny = require_manager(request)
    if deny:
        return deny
    limit = parse_int(request.query_params.get("limit"), default=200) or 200
    offset = parse_int(request.query_params.get("offset"), default=0) or 0
    table_name = request.query_params.get("table_name")
    record_id = request.query_params.get("record_id")
    actor_param = request.query_params.get("actor")
    action = request.query_params.get("action")
    start_ts = request.query_params.get("start_ts")
    end_ts = request.query_params.get("end_ts")
    items = audit.fetch_audit_logs(
        limit=limit,
        offset=offset,
        table_name=table_name,
        record_id=record_id,
        actor=actor_param,
        action=action,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    return list_response(AuditResponseSerializer(items, many=True).data)


@route("audit/auth-events/", order=112)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def auth_security_events(request: Request) -> Response:
    """Return structured authentication security events."""
    deny = require_manager(request)
    if deny:
        return deny
    limit = parse_int(request.query_params.get("limit"), default=200) or 200
    offset = parse_int(request.query_params.get("offset"), default=0) or 0
    event_type = request.query_params.get("event_type")
    outcome = request.query_params.get("outcome")
    user_id = parse_int(request.query_params.get("user_id"))
    identifier = request.query_params.get("identifier")
    source_ip = request.query_params.get("source_ip")
    start_ts = parse_timestamp(request.query_params.get("start_ts"))
    end_ts = parse_timestamp(request.query_params.get("end_ts"))
    items = auth_events.fetch_auth_events(
        limit=limit,
        offset=offset,
        event_type=event_type,
        outcome=outcome,
        user_id=user_id,
        identifier=identifier,
        source_ip=source_ip,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    return list_response(AuthSecurityEventResponseSerializer(items, many=True).data)


@route("audit/count/", order=111)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def audit_count(request: Request) -> Response:
    """Return audit log counts."""
    deny = require_manager(request)
    if deny:
        return deny
    table_name = request.query_params.get("table_name")
    record_id = request.query_params.get("record_id")
    actor_param = request.query_params.get("actor")
    action = request.query_params.get("action")
    start_ts = request.query_params.get("start_ts")
    end_ts = request.query_params.get("end_ts")
    total = audit.count_audit_logs(
        table_name=table_name,
        record_id=record_id,
        actor=actor_param,
        action=action,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    return Response({"total": total})


@route("audit/auth-events/count/", order=113)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def auth_security_events_count(request: Request) -> Response:
    """Return auth security event count."""
    deny = require_manager(request)
    if deny:
        return deny
    total = auth_events.count_auth_events(
        event_type=request.query_params.get("event_type"),
        outcome=request.query_params.get("outcome"),
        user_id=parse_int(request.query_params.get("user_id")),
        identifier=request.query_params.get("identifier"),
        source_ip=request.query_params.get("source_ip"),
        start_ts=parse_timestamp(request.query_params.get("start_ts")),
        end_ts=parse_timestamp(request.query_params.get("end_ts")),
    )
    return Response({"total": total})


@route("audit/purge/", order=114)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def audit_purge(request: Request) -> Response:
    """Purge audit logs."""
    deny = require_superuser(request)
    if deny:
        return deny
    confirm = require_confirmation(request, "PURGE_AUDIT_LOGS")
    if confirm:
        return confirm
    count = audit.purge_audit_logs(actor=actor(request))
    return Response({"purged": count})


@route("audit/security-alerts/", order=115)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def auth_security_alerts(request: Request) -> Response:
    """Return security alert events (subset of auth security events)."""
    deny = require_manager(request)
    if deny:
        return deny
    limit = parse_int(request.query_params.get("limit"), default=200) or 200
    offset = parse_int(request.query_params.get("offset"), default=0) or 0
    outcome = request.query_params.get("outcome")
    user_id = parse_int(request.query_params.get("user_id"))
    identifier = request.query_params.get("identifier")
    source_ip = request.query_params.get("source_ip")
    start_ts = parse_timestamp(request.query_params.get("start_ts"))
    end_ts = parse_timestamp(request.query_params.get("end_ts"))
    items = auth_events.fetch_auth_events(
        limit=limit,
        offset=offset,
        event_type="security_alert",
        outcome=outcome,
        user_id=user_id,
        identifier=identifier,
        source_ip=source_ip,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    return list_response(AuthSecurityEventResponseSerializer(items, many=True).data)


@route("audit/security-alerts/count/", order=116)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def auth_security_alerts_count(request: Request) -> Response:
    """Return security alert event count."""
    deny = require_manager(request)
    if deny:
        return deny
    total = auth_events.count_auth_events(
        event_type="security_alert",
        outcome=request.query_params.get("outcome"),
        user_id=parse_int(request.query_params.get("user_id")),
        identifier=request.query_params.get("identifier"),
        source_ip=request.query_params.get("source_ip"),
        start_ts=parse_timestamp(request.query_params.get("start_ts")),
        end_ts=parse_timestamp(request.query_params.get("end_ts")),
    )
    return Response({"total": total})
