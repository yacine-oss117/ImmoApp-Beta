"""Lazy service-layer facade for API views and tasks.

This package intentionally exposes module objects (``server.services.clients``,
``server.services.matches``, etc.) without eagerly importing every submodule at
package import time.
"""

from __future__ import annotations

import importlib
from types import ModuleType

_SERVICE_MODULES = {
    "agency_settings",
    "ale_maintenance",
    "ale_helper",
    "ale_policy",
    "audit",
    "auth_events",
    "auth_lockout",
    "auth_security_alerts",
    "auth_sessions",
    "clients",
    "compliance_jobs",
    "crm",
    "crm_contracts",
    "crm_visits",
    "dashboard",
    "diagnostics_keys",
    "demandes",
    "health",
    "import_admission_service",
    "import_chunk_workflow",
    "import_execution_governor",
    "import_jobs",
    "import_runtime_maintenance",
    "import_service",
    "listings",
    "locations",
    "lookup",
    "match_cache",
    "match_all_scheduler",
    "match_jobs",
    "match_runtime_profile",
    "matches",
    "media",
    "mfa_service",
    "mfa_totp",
    "notifications",
    "offer_photos",
    "offers",
    "permission_elevation",
    "postgres_match_health",
    "registration_lifecycle",
    "record_acl",
    "runtime_pressure_tripwire",
    "simulation",
    "storage",
    "sync",
    "tenant_resource_governor",
    "tenant_usage_gauge",
    "templates",
    "user_auth_lifecycle",
    "users",
    "work_admission",
}

__all__ = sorted(_SERVICE_MODULES)


def __getattr__(name: str) -> ModuleType:
    if name not in _SERVICE_MODULES:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
    module = importlib.import_module(f"{__name__}.{name}")
    globals()[name] = module
    return module
