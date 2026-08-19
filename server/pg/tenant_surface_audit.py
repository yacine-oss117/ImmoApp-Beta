"""Repo-wide tenant surface classification helpers."""

from __future__ import annotations

from dataclasses import dataclass

from server.pg import schema_tenant_constants


@dataclass(frozen=True)
class TenantSurfaceAuditResult:
    """Classification summary for application-owned tenant surfaces."""

    tenant_owned: tuple[str, ...]
    global_system: tuple[str, ...]
    special_polymorphic: tuple[str, ...]
    client_local_stores: tuple[str, ...]
    classification_version: str


def audit_tenant_surfaces() -> TenantSurfaceAuditResult:
    """Return the canonical tenant surface classification summary."""

    return TenantSurfaceAuditResult(
        tenant_owned=tuple(schema_tenant_constants.TENANT_OWNED_TABLES),
        global_system=tuple(schema_tenant_constants.GLOBAL_SYSTEM_TABLES),
        special_polymorphic=tuple(schema_tenant_constants.SPECIAL_POLYMORPHIC_TABLES),
        client_local_stores=tuple(schema_tenant_constants.CLIENT_LOCAL_STORES),
        classification_version=schema_tenant_constants.tenant_surface_classification_version(),
    )
