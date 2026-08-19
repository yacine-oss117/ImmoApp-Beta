"""
Postgres-backed agency settings operations.
"""

from __future__ import annotations

from core.data import agency_settings_repository as data
from server.pg.tenant_context import require_agency_id, use_tenant_context
from server.pg.uow import get_uow


def get_agency_setting(key: str, default: str = "") -> str:
    """Retrieve a specific agency setting from Postgres."""
    with get_uow().session() as session:
        return data.get_agency_setting(session, key, default)


def set_agency_setting(
    key: str,
    value: str,
    agency_id: int | None = None,
    *,
    actor: str | None = None,
) -> None:
    """Update a specific agency setting in Postgres."""
    resolved_agency_id = require_agency_id(
        explicit=agency_id,
        error_message="agency_id is required to set agency settings",
    )
    with use_tenant_context(agency_id=resolved_agency_id, source="explicit"):
        with get_uow().transaction(actor=actor) as session:
            data.set_agency_setting(session, key, value)


def get_all_agency_settings() -> dict[str, str]:
    """Retrieve all agency settings from Postgres."""
    with get_uow().session() as session:
        return data.get_all_agency_settings(session)


def generate_contract_serial(prefix: str, agency_id: int) -> str:
    """Atomically generate a new unique contract serial number."""
    with use_tenant_context(agency_id=agency_id, source="explicit"):
        with get_uow().transaction() as session:
            return data.generate_contract_serial(session, prefix)
