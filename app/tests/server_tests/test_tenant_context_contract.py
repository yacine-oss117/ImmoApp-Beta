from __future__ import annotations

import pytest

from server.pg.tenant_context import get_tenant_context, require_agency_id, use_tenant_context


def test_use_tenant_context_sets_canonical_ambient_context() -> None:
    with use_tenant_context(
        agency_id=7,
        actor_id=41,
        actor_email="owner@example.com",
        actor_role="manager",
        actor_is_owner=True,
        source="explicit",
    ):
        context = get_tenant_context()

    assert context.agency_id == 7
    assert context.actor_id == 41
    assert context.actor_email == "owner@example.com"
    assert context.actor_role == "manager"
    assert context.actor_is_owner is True
    assert context.source == "explicit"
    assert context.bootstrap_mode == "strict"


def test_require_agency_id_prefers_explicit_value_over_ambient() -> None:
    with use_tenant_context(agency_id=7, source="ambient"):
        resolved = require_agency_id(explicit=13)

    assert resolved == 13


def test_require_agency_id_uses_parent_resolver_when_ambient_missing() -> None:
    resolved = require_agency_id(parent_resolver=lambda: 19)

    assert resolved == 19


def test_require_agency_id_raises_when_unresolved() -> None:
    with pytest.raises(RuntimeError, match="agency_id is required"):
        require_agency_id(error_message="agency_id is required")
