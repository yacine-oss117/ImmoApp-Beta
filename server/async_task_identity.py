"""Canonical async identity payload builders for tenant-originated work."""

from __future__ import annotations

from typing import Protocol

from server.logging_config import get_correlation_id
from server.pg.uow import (
    get_current_actor_id,
    get_current_actor_role,
    get_current_agency_id,
    get_current_schema,
    is_current_actor_owner,
)


class RequestLike(Protocol):
    user: object


def _user_agency_id(user: object | None) -> int | None:
    if not user or not getattr(user, "is_authenticated", False):
        return None
    direct_id = getattr(user, "agency_id", None)
    if isinstance(direct_id, int):
        return direct_id
    agency = getattr(user, "agency", None)
    agency_id = getattr(agency, "id", None) if agency is not None else None
    return int(agency_id) if isinstance(agency_id, int) else None


def _user_actor_id(user: object | None) -> int | None:
    if not user or not getattr(user, "is_authenticated", False):
        return None
    actor_id = getattr(user, "id", None)
    return int(actor_id) if isinstance(actor_id, int) else None


def _user_actor_role(user: object | None) -> str | None:
    if not user or not getattr(user, "is_authenticated", False):
        return None
    role = getattr(user, "role", None)
    if isinstance(role, str) and role:
        return role
    return None


def _user_actor_is_owner(user: object | None) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return bool(getattr(user, "is_owner", False))


def build_async_task_identity(
    *,
    agency_id: int,
    schema: str | None,
    correlation_id: str | None,
    actor_id: int | None,
    actor_role: str | None,
    actor_is_owner: bool = False,
    include_schema: bool = True,
    include_actor_is_owner: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "agency_id": int(agency_id),
        "correlation_id": correlation_id,
        "actor_id": actor_id,
        "actor_role": actor_role,
    }
    if include_schema:
        payload["schema"] = schema
    if include_actor_is_owner:
        payload["actor_is_owner"] = bool(actor_is_owner)
    return payload


def build_request_async_task_identity(
    request: RequestLike,
    *,
    agency_id: int | None = None,
    include_schema: bool = True,
    include_actor_is_owner: bool = False,
) -> dict[str, object] | None:
    user = getattr(request, "user", None)
    effective_agency_id = agency_id if isinstance(agency_id, int) and agency_id > 0 else None
    if effective_agency_id is None:
        effective_agency_id = _user_agency_id(user)
    if effective_agency_id is None:
        return None
    return build_async_task_identity(
        agency_id=effective_agency_id,
        schema=get_current_schema() if include_schema else None,
        correlation_id=get_correlation_id(),
        actor_id=_user_actor_id(user),
        actor_role=_user_actor_role(user),
        actor_is_owner=_user_actor_is_owner(user),
        include_schema=include_schema,
        include_actor_is_owner=include_actor_is_owner,
    )


def build_context_async_task_identity(
    *,
    agency_id: int | None = None,
    include_schema: bool = True,
    include_actor_is_owner: bool = False,
) -> dict[str, object] | None:
    effective_agency_id = get_current_agency_id()
    if effective_agency_id is None and isinstance(agency_id, int) and agency_id > 0:
        effective_agency_id = agency_id
    if effective_agency_id is None:
        return None
    return build_async_task_identity(
        agency_id=int(effective_agency_id),
        schema=get_current_schema() if include_schema else None,
        correlation_id=get_correlation_id(),
        actor_id=get_current_actor_id(),
        actor_role=get_current_actor_role(),
        actor_is_owner=is_current_actor_owner(),
        include_schema=include_schema,
        include_actor_is_owner=include_actor_is_owner,
    )


__all__ = [
    "build_async_task_identity",
    "build_context_async_task_identity",
    "build_request_async_task_identity",
]
