"""
Tenant isolation compatibility exports.

Runtime schema DDL is migration-owned. This module remains only as a compatibility
import surface for constants/predicates used by verifiers.
"""

from __future__ import annotations

from .schema_tenant_constants import (
    AGENCY_DEFAULT_EXPR,
    TENANT_TABLES,
    TENANT_TABLES_NOT_NULL,
    TENANT_TABLES_NULL_OK,
)
from .schema_tenant_predicates import rls_predicate_for_table
from .uow import PgSession

__all__ = [
    "AGENCY_DEFAULT_EXPR",
    "TENANT_TABLES",
    "TENANT_TABLES_NOT_NULL",
    "TENANT_TABLES_NULL_OK",
    "ensure_tenant_isolation",
    "rls_predicate_for_table",
]


def ensure_tenant_isolation(session: PgSession) -> None:
    """Compatibility shim kept for one release cycle.

    Schema/RLS ownership moved to Alembic migrations. Callers must not rely on
    runtime schema mutation anymore.
    """
    del session
    raise RuntimeError(
        "ensure_tenant_isolation() is no longer supported at runtime. "
        "Run Alembic migrations to apply tenant isolation/RLS schema."
    )
