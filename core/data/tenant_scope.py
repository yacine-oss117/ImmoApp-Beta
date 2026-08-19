"""Explicit tenant predicates for repository reads.

RLS/session context remains the primary database boundary. These helpers add an
application-level predicate as a second line of defense for high-risk list reads.
"""

from __future__ import annotations


def tenant_condition(alias: str) -> tuple[str | None, list[object]]:
    from server.pg.uow import get_current_agency_id, is_current_user_superuser

    normalized_alias = str(alias or "").strip()
    if not normalized_alias.replace("_", "").isalnum():
        raise ValueError(f"unsafe SQL alias for tenant predicate: {alias!r}")

    agency_id = get_current_agency_id()
    if agency_id is None:
        if is_current_user_superuser():
            return None, []
        return "FALSE", []
    return f"{normalized_alias}.agency_id = %s", [int(agency_id)]


__all__ = ["tenant_condition"]
