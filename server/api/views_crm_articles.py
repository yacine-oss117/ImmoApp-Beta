"""CRM contract article API views."""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.api_view import api_view
from server.api.route_registry import route
from server.services import crm
from server.services.errors import ConflictError

from .request_schemas import (
    ContractArticleSerializer,
    ContractArticleUpdateSerializer,
    CopyClausesSerializer,
)
from .validation import validate_payload
from .view_helpers import actor, conflict_error, list_response


def _payload_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    return value if isinstance(value, int) else 0


@route("crm/contracts/<int:contract_id>/articles/", order=99)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def crm_contract_articles(request: Request, contract_id: int) -> Response:
    """List or create articles for a contract."""
    if request.method == "POST":
        payload, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            ContractArticleSerializer,
            partial=False,
        )
        if error_response:
            return error_response
        payload = payload or {}
        title = str(payload.get("title") or "")
        content = str(payload.get("content") or "")
        article_number = _payload_int(payload, "article_number")
        article_id = crm.create_article(
            contract_id,
            article_number,
            title,
            content,
            is_standard=bool(payload.get("is_standard")),
            is_required=bool(payload.get("is_required")),
            actor=actor(request),
        )
        created_item = next(
            (
                item
                for item in crm.get_articles_for_contract(contract_id)
                if isinstance(item.get("id"), int) and item["id"] == article_id
            ),
            {"id": article_id},
        )
        return Response({"id": article_id, "item": created_item}, status=status.HTTP_201_CREATED)
    return list_response(crm.get_articles_for_contract(contract_id))


@route("crm/articles/<int:article_id>/", order=102)
@api_view(["PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def crm_article_detail(request: Request, article_id: int) -> Response:
    """Update or delete a contract article."""
    if request.method == "PUT":
        payload, error_response = validate_payload(
            request.data if isinstance(request.data, dict) else {},
            ContractArticleUpdateSerializer,
            partial=True,
            require_row_version=True,
        )
        if error_response:
            return error_response
        payload = payload or {}
        title = str(payload.get("title") or "")
        content = str(payload.get("content") or "")
        row_version = payload.get("row_version")
        try:
            ok = crm.update_article(
                article_id,
                title,
                content,
                row_version=row_version if isinstance(row_version, int) else None,
                actor=actor(request),
            )
        except ConflictError as exc:
            return conflict_error(
                str(exc),
                current_version=exc.current_version,
                current_record=exc.current_record,
            )
        return Response({"updated": ok})
    ok = crm.delete_article(article_id, actor=actor(request))
    return Response({"deleted": ok})


@route("crm/contracts/<int:contract_id>/articles/renumber/", order=100)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def crm_contract_articles_renumber(request: Request, contract_id: int) -> Response:
    """Renumber contract articles."""
    crm.renumber_articles(contract_id, actor=actor(request))
    return Response(status=status.HTTP_204_NO_CONTENT)


@route("crm/contracts/<int:contract_id>/clauses/", order=101)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def crm_contract_copy_clauses(request: Request, contract_id: int) -> Response:
    """Copy standard clauses into a contract."""
    payload, error_response = validate_payload(
        request.data if isinstance(request.data, dict) else {},
        CopyClausesSerializer,
        partial=False,
    )
    if error_response:
        return error_response
    raw_context = (payload or {}).get("context")
    context = (
        {str(key): str(value) for key, value in raw_context.items()}
        if isinstance(raw_context, dict)
        else {}
    )
    count = crm.copy_standard_clauses(contract_id, context, actor=actor(request))
    return Response({"count": count})


__all__ = [
    "crm_contract_articles",
    "crm_article_detail",
    "crm_contract_articles_renumber",
    "crm_contract_copy_clauses",
]
