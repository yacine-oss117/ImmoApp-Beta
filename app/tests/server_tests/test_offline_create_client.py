from __future__ import annotations

import pytest

from app.services import client_repository
from app.services.offline_account_scope import OfflineAccountScope
from app.services.offline_op_log import list_operations
from app.services.offline_projection import get_projection_record


def _scope(suffix: str = "scope") -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_offline_client_create_returns_negative_id(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.offline_entity_mutations as mutations

    scope = _scope("client-create")
    monkeypatch.setenv("IMMOAPP_OFFLINE_CREATES_ENABLED", "1")
    monkeypatch.setattr(mutations, "require_active_account_scope", lambda: scope)
    monkeypatch.setattr(
        mutations.api_module,
        "_send_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    created_id = client_repository.upsert_client({"full_name": "Offline Client"})

    assert created_id < 0
    projection = get_projection_record("client", created_id, scope=scope)
    assert projection is not None
    assert projection.is_local_only is True
    assert projection.sync_status == "pending"
    ops = list_operations(scope=scope)
    assert len(ops) == 1
    assert ops[0].entity_type == "client"
    assert ops[0].op_type == "create"


def test_offline_client_create_requires_active_account_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.offline_entity_mutations as mutations

    monkeypatch.setenv("IMMOAPP_OFFLINE_CREATES_ENABLED", "1")
    monkeypatch.setattr(
        mutations,
        "require_active_account_scope",
        lambda: (_ for _ in ()).throw(RuntimeError("scope missing")),
    )

    with pytest.raises(RuntimeError, match="scope missing"):
        client_repository.upsert_client({"full_name": "Offline Client"})
