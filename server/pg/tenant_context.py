"""Canonical tenant-context helpers built on top of the UoW context."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable, Iterator, Literal

from server.pg import uow

TenantContextSource = Literal[
    "explicit",
    "request_user",
    "jwt_claims",
    "task_payload",
    "import_job",
    "parent_record",
    "ambient",
    "platform_bootstrap",
]

TenantBootstrapMode = Literal[
    "strict",
    "platform_root_create",
]

_TENANT_SOURCE_CTX: ContextVar[TenantContextSource] = ContextVar(
    "tenant_context_source",
    default="ambient",
)
_TENANT_BOOTSTRAP_CTX: ContextVar[TenantBootstrapMode] = ContextVar(
    "tenant_bootstrap_mode",
    default="strict",
)


@dataclass(frozen=True)
class TenantContext:
    agency_id: int | None
    actor_id: int | None
    actor_email: str | None
    actor_role: str | None
    actor_is_owner: bool
    is_superuser: bool
    source: TenantContextSource
    bootstrap_mode: TenantBootstrapMode


def get_tenant_context() -> TenantContext:
    return TenantContext(
        agency_id=uow.get_current_agency_id(),
        actor_id=uow.get_current_actor_id(),
        actor_email=uow.get_current_actor_email(),
        actor_role=uow.get_current_actor_role(),
        actor_is_owner=uow.is_current_actor_owner(),
        is_superuser=uow.is_current_user_superuser(),
        source=_TENANT_SOURCE_CTX.get(),
        bootstrap_mode=_TENANT_BOOTSTRAP_CTX.get(),
    )


def resolve_agency_id(
    *,
    explicit: int | None = None,
    parent_resolver: Callable[[], int | None] | None = None,
) -> int | None:
    if explicit is not None:
        return int(explicit)
    ambient = uow.get_current_agency_id()
    if ambient is not None:
        return int(ambient)
    if parent_resolver is None:
        return None
    resolved = parent_resolver()
    if resolved is None:
        return None
    return int(resolved)


def require_agency_id(
    *,
    explicit: int | None = None,
    parent_resolver: Callable[[], int | None] | None = None,
    error_message: str = "Missing tenant context: agency_id is required.",
) -> int:
    resolved = resolve_agency_id(explicit=explicit, parent_resolver=parent_resolver)
    if resolved is None:
        raise RuntimeError(error_message)
    return resolved


def in_platform_root_create_mode() -> bool:
    return _TENANT_BOOTSTRAP_CTX.get() == "platform_root_create"


@contextmanager
def use_tenant_context(
    *,
    agency_id: int | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
    actor_role: str | None = None,
    actor_is_owner: bool = False,
    is_superuser: bool = False,
    source: TenantContextSource = "ambient",
    bootstrap_mode: TenantBootstrapMode = "strict",
) -> Iterator[TenantContext]:
    source_token = _TENANT_SOURCE_CTX.set(source)
    bootstrap_token = _TENANT_BOOTSTRAP_CTX.set(bootstrap_mode)
    try:
        with ExitStack() as stack:
            stack.enter_context(
                uow.use_security_context(
                    agency_id=agency_id,
                    is_superuser=is_superuser,
                )
            )
            stack.enter_context(
                uow.use_actor_context(
                    actor_id=actor_id,
                    actor_email=actor_email,
                    actor_role=actor_role,
                    actor_is_owner=actor_is_owner,
                )
            )
            yield get_tenant_context()
    finally:
        _TENANT_SOURCE_CTX.reset(source_token)
        _TENANT_BOOTSTRAP_CTX.reset(bootstrap_token)


__all__ = [
    "TenantBootstrapMode",
    "TenantContext",
    "TenantContextSource",
    "get_tenant_context",
    "in_platform_root_create_mode",
    "require_agency_id",
    "resolve_agency_id",
    "use_tenant_context",
]
