"""
Record visibility + ACL API.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import record_acl
from server.services.errors import ConflictError, NotFoundError

from .rbac import require_manager
from .request_schemas import RecordVisibilitySerializer
from .validation import validate_payload
from .view_helpers import conflict_error, error, safe_error_message


@route("visibility/<str:table>/<int:record_id>/", order=126)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def record_visibility(request: Request, table: str, record_id: int) -> Response:
    """Get or update visibility/ACL for a record."""
    deny = require_manager(request)
    if deny:
        return deny

    if request.method == "GET":
        try:
            snapshot = record_acl.get_record_visibility(table, record_id)
        except NotFoundError:
            return error("Record not found", status.HTTP_404_NOT_FOUND)
        except ValueError as exc:
            return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
        return Response(snapshot)

    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        RecordVisibilitySerializer,
        partial=False,
        require_row_version=True,
    )
    if error_response:
        return error_response
    payload = payload or {}
    allowed_user_ids_raw = payload.get("allowed_user_ids")
    allowed_user_ids = (
        [int(user_id) for user_id in allowed_user_ids_raw if isinstance(user_id, int)]
        if isinstance(allowed_user_ids_raw, list)
        else []
    )
    row_version_raw = payload.get("row_version")
    row_version = row_version_raw if isinstance(row_version_raw, int) else None
    try:
        record_acl.set_record_visibility(
            table=table,
            record_id=record_id,
            visibility=str(payload.get("visibility") or ""),
            allowed_user_ids=allowed_user_ids,
            row_version=row_version,
        )
    except ConflictError as exc:
        return conflict_error(
            str(exc),
            current_version=exc.current_version,
            current_record=exc.current_record,
        )
    except NotFoundError:
        return error("Record not found", status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return error(safe_error_message(exc), status.HTTP_400_BAD_REQUEST)
    return Response(status=status.HTTP_204_NO_CONTENT)


__all__ = ["record_visibility"]
