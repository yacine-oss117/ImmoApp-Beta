"""User service query operations."""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from core.data.surface_cache_generation import USERS_SURFACE, agency_scope_key, read_generation
from server.pg.uow import get_uow, use_security_context
from server.services.cursor_pagination import decode_cursor, encode_cursor, normalize_limit
from server.services.errors import NotFoundError, PermissionDeniedError

from .users_helpers import (
    agency_id_of,
    ensure_manager_owns_agent,
    ensure_manager_target_role,
    get_user_model_for_service,
    require_manager,
    require_same_agency,
    serialize_user,
)


def _filtered_users_queryset(
    *,
    actor: object | None,
    include_inactive: bool = False,
    role: str | None = None,
    agency_id: int | None = None,
    scope: str = "agency",
    q: str | None = None,
) -> object:
    normalized_scope = (scope or "agency").strip().lower()
    if normalized_scope not in {"agency", "all"}:
        raise ValueError("scope must be 'agency' or 'all'")

    require_manager(actor)
    User = get_user_model_for_service()

    actor_is_superuser = bool(actor and getattr(actor, "is_superuser", False))
    actor_agency_id = agency_id_of(actor)

    if normalized_scope == "all":
        if not actor_is_superuser:
            raise PermissionDeniedError("Superuser access required for scope=all.")
        qs = User.objects.all()
        if agency_id is not None:
            qs = qs.filter(agency_id=agency_id)
    else:
        if actor_is_superuser:
            if agency_id is None:
                raise PermissionDeniedError(
                    "agency_id is required for superuser scope=agency requests."
                )
            scoped_agency_id = agency_id
        else:
            if actor_agency_id is None:
                raise PermissionDeniedError("Agency is required.")
            if agency_id is not None and agency_id != actor_agency_id:
                raise PermissionDeniedError("Forbidden agency scope.")
            scoped_agency_id = actor_agency_id
        qs = User.objects.filter(agency_id=scoped_agency_id)

    if not include_inactive:
        qs = qs.filter(is_active=True)
    if role:
        qs = qs.filter(role=role)
    q_text = str(q or "").strip()
    if q_text:
        qs = qs.filter(
            Q(username__icontains=q_text)
            | Q(email__icontains=q_text)
            | Q(first_name_search_src__icontains=q_text)
            | Q(last_name_search_src__icontains=q_text)
        )
    return qs


def list_users_page(
    *,
    actor: object | None,
    include_inactive: bool = False,
    role: str | None = None,
    agency_id: int | None = None,
    scope: str = "agency",
    q: str | None = None,
    limit: int | str | None = None,
    cursor: str | None = None,
) -> tuple[list[dict[str, object]], str | None, bool]:
    normalized_limit = normalize_limit(limit, default=50, minimum=1, maximum=200)
    cursor_data = decode_cursor(cursor)
    last_id = 0
    if cursor_data is not None:
        try:
            last_id = int(cursor_data.get("id", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid cursor.") from exc
        if last_id < 0:
            raise ValueError("Invalid cursor.")

    qs: Any = _filtered_users_queryset(
        actor=actor,
        include_inactive=include_inactive,
        role=role,
        agency_id=agency_id,
        scope=scope,
        q=q,
    )
    if last_id > 0:
        qs = qs.filter(id__gt=last_id)

    users = list(qs.order_by("id")[: normalized_limit + 1])
    has_more = len(users) > normalized_limit
    page = users[:normalized_limit]
    next_cursor = None
    if has_more and page:
        next_cursor = encode_cursor({"id": int(page[-1].id)})

    return [serialize_user(user) for user in page], next_cursor, has_more


def list_users(
    *,
    actor: object | None,
    include_inactive: bool = False,
    role: str | None = None,
    agency_id: int | None = None,
    scope: str = "agency",
    q: str | None = None,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    cursor: str | None = None
    while True:
        page, next_cursor, has_more = list_users_page(
            actor=actor,
            include_inactive=include_inactive,
            role=role,
            agency_id=agency_id,
            scope=scope,
            q=q,
            limit=200,
            cursor=cursor,
        )
        items.extend(page)
        if not has_more or not next_cursor:
            break
        cursor = next_cursor
    return items


def get_user_detail(
    *,
    actor: object | None,
    user_id: int,
) -> dict[str, object]:
    require_manager(actor)
    User = get_user_model_for_service()
    user = User.objects.filter(id=user_id).first()
    if not user:
        raise NotFoundError("User not found.")
    require_same_agency(actor, user)
    ensure_manager_target_role(actor, user)
    ensure_manager_owns_agent(actor, user)
    return serialize_user(user)


def get_users_surface_generation(*, agency_id: int) -> int:
    resolved_agency_id = int(agency_id)
    if resolved_agency_id <= 0:
        raise ValueError("agency_id is required for users surface generation")
    with use_security_context(agency_id=resolved_agency_id, is_superuser=False):
        with get_uow().session() as session:
            return int(
                read_generation(
                    session,
                    surface=USERS_SURFACE,
                    scope_key=agency_scope_key(resolved_agency_id),
                    agency_id=resolved_agency_id,
                )
            )


__all__ = ["get_user_detail", "get_users_surface_generation", "list_users", "list_users_page"]
