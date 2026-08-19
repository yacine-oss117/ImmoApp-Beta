from __future__ import annotations

import pytest

import app.services.api_client as api_module
from app.services import offline_reconciler as module
from app.services.api_client_errors import ApiError
from app.services.offline_account_scope import OfflineAccountScope
from app.services.offline_conflicts import list_conflicts
from app.services.offline_ids import resolve_reconciled_id
from app.services.offline_op_log import get_operation, list_operations, queue_create_operation
from app.services.offline_projection import get_projection_record
from app.services.offline_types import OfflineEntityRef


def _scope(suffix: str = "reconciler") -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_replay_create_reconciles_temp_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.offline_projection import OfflineProjectionRecord, upsert_projection_record

    scope = _scope()
    op = queue_create_operation(
        "client",
        -1,
        payload={
            "method": "POST",
            "path": "/clients",
            "body": {"full_name": "Offline Client"},
            "headers": {"Idempotency-Key": "offline:test"},
        },
        dedupe_key="offline:test",
        scope=scope,
    )
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type="client",
            local_id=-1,
            server_id=None,
            data={"id": -1, "full_name": "Offline Client"},
            sync_status=op.status,
            is_local_only=True,
        ),
        scope=scope,
    )
    monkeypatch.setattr(
        api_module,
        "_send_request",
        lambda method, path, **kwargs: {
            "id": 41,
            "item": {"id": 41, "family_name": "Offline Client"},
        },
    )

    result = module.replay_offline_operations(scope=scope)

    assert result["flushed"] == 1
    assert resolve_reconciled_id("client", -1, scope=scope) == 41
    assert get_projection_record("client", -1, scope=scope) is None
    reconciled = get_projection_record("client", 41, scope=scope)
    assert reconciled is not None
    assert reconciled.sync_status == "synced"
    assert get_operation(op.op_id, scope=scope) is None


def test_replay_unblocks_child_after_parent_create(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.offline_projection import OfflineProjectionRecord, upsert_projection_record

    scope = _scope("parent-child")
    client = queue_create_operation(
        "client",
        -1,
        payload={"method": "POST", "path": "/clients", "body": {"full_name": "Parent"}},
        dedupe_key="offline:client",
        scope=scope,
    )
    demande = queue_create_operation(
        "demande",
        -1,
        payload={
            "method": "POST",
            "path_template": "/clients/{client_id}/demandes",
            "path_refs": {"client_id": {"entity_type": "client", "local_id": -1}},
            "body": {"budget_min": 1},
        },
        parent_refs=[OfflineEntityRef(entity_type="client", local_id=-1)],
        dedupe_key="offline:demande",
        scope=scope,
    )
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type="client",
            local_id=-1,
            server_id=None,
            data={"id": -1, "full_name": "Parent"},
            sync_status=client.status,
            is_local_only=True,
        ),
        scope=scope,
    )
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type="demande",
            local_id=-1,
            server_id=None,
            data={"id": -1, "client_id": -1},
            sync_status=demande.status,
            is_local_only=True,
        ),
        scope=scope,
    )

    calls: list[tuple[str, str]] = []

    def _send(method: str, path: str, **kwargs):
        calls.append((method, path))
        if path == "/clients":
            return {"id": 77, "item": {"id": 77, "family_name": "Parent"}}
        return {"id": 88, "item": {"id": 88, "client_id": 77, "budget_min": 1}}

    monkeypatch.setattr(api_module, "_send_request", _send)

    first = module.replay_offline_operations(scope=scope)
    second = module.replay_offline_operations(scope=scope)

    assert first["flushed"] == 1
    assert second["flushed"] == 1
    assert calls == [("POST", "/clients"), ("POST", "/clients/77/demandes")]
    assert get_projection_record("demande", 88, scope=scope) is not None


def test_replay_parent_create_updates_child_projection_parent_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.offline_projection import OfflineProjectionRecord, upsert_projection_record

    scope = _scope("projection-refs")
    queue_create_operation(
        "client",
        -1,
        payload={"method": "POST", "path": "/clients", "body": {"full_name": "Parent"}},
        dedupe_key="offline:client",
        scope=scope,
    )
    queue_create_operation(
        "demande",
        -1,
        payload={
            "method": "POST",
            "path_template": "/clients/{client_id}/demandes",
            "path_refs": {"client_id": {"entity_type": "client", "local_id": -1}},
            "body": {"budget_min": 1},
        },
        parent_refs=[OfflineEntityRef(entity_type="client", local_id=-1)],
        dedupe_key="offline:demande",
        scope=scope,
    )
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type="client",
            local_id=-1,
            server_id=None,
            data={"id": -1, "family_name": "Parent"},
            sync_status="pending",
            is_local_only=True,
        ),
        scope=scope,
    )
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type="demande",
            local_id=-1,
            server_id=None,
            data={"id": -1, "client_id": -1, "budget_min": 1},
            sync_status="blocked",
            is_local_only=True,
        ),
        scope=scope,
    )

    monkeypatch.setattr(
        api_module,
        "_send_request",
        lambda method, path, **kwargs: {"id": 77, "item": {"id": 77, "family_name": "Parent"}},
    )

    result = module.replay_offline_operations(scope=scope)

    assert result["flushed"] == 1
    child_projection = get_projection_record("demande", -1, scope=scope)
    assert child_projection is not None
    assert int(child_projection.data["client_id"]) == 77


def test_replay_parent_create_updates_contract_article_projection_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.offline_projection import OfflineProjectionRecord, upsert_projection_record

    scope = _scope("contract-article-refs")
    queue_create_operation(
        "contract",
        -1,
        payload={"method": "POST", "path": "/crm/contracts", "body": {"contract_type": "sale"}},
        dedupe_key="offline:contract",
        scope=scope,
    )
    queue_create_operation(
        "contract_article",
        -1,
        payload={
            "method": "POST",
            "path_template": "/crm/contracts/{contract_id}/articles",
            "path_refs": {"contract_id": {"entity_type": "contract", "local_id": -1}},
            "body": {"article_number": 1, "title": "Clause", "content": "Body"},
        },
        parent_refs=[OfflineEntityRef(entity_type="contract", local_id=-1)],
        dedupe_key="offline:contract-article",
        scope=scope,
    )
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type="contract",
            local_id=-1,
            server_id=None,
            data={"id": -1, "contract_type": "sale"},
            sync_status="pending",
            is_local_only=True,
        ),
        scope=scope,
    )
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type="contract_article",
            local_id=-1,
            server_id=None,
            data={"id": -1, "contract_id": -1, "article_number": 1, "title": "Clause"},
            sync_status="blocked",
            is_local_only=True,
        ),
        scope=scope,
    )

    monkeypatch.setattr(
        api_module,
        "_send_request",
        lambda method, path, **kwargs: {"id": 91, "item": {"id": 91, "contract_type": "sale"}},
    )

    result = module.replay_offline_operations(scope=scope)

    assert result["flushed"] == 1
    projection = get_projection_record("contract_article", -1, scope=scope)
    assert projection is not None
    assert int(projection.data["contract_id"]) == 91


def test_replay_moves_permanent_api_failure_to_review(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _scope("review")
    op = queue_create_operation(
        "client",
        -1,
        payload={"method": "POST", "path": "/clients", "body": {"full_name": "Bad"}},
        dedupe_key="offline:bad",
        scope=scope,
    )
    monkeypatch.setattr(
        api_module,
        "_send_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(ApiError(409, "conflict")),
    )

    result = module.replay_offline_operations(scope=scope)

    assert result["needs_review"] == 1
    assert get_operation(op.op_id, scope=scope) is not None
    assert get_operation(op.op_id, scope=scope).status == "needs_review"
    assert len(list_conflicts(scope=scope)) == 1


def test_replay_blocks_on_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _scope("auth")
    op = queue_create_operation(
        "client",
        -1,
        payload={"method": "POST", "path": "/clients", "body": {"full_name": "Auth"}},
        dedupe_key="offline:auth",
        scope=scope,
    )
    monkeypatch.setattr(
        api_module,
        "_send_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(ApiError(401, "login required")),
    )

    result = module.replay_offline_operations(scope=scope)

    assert result["blocked"] == 1
    assert get_operation(op.op_id, scope=scope) is not None
    assert get_operation(op.op_id, scope=scope).status == "blocked"


def test_replay_is_account_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    scope_a = _scope("a")
    scope_b = _scope("b")
    queue_create_operation(
        "client",
        -1,
        payload={"method": "POST", "path": "/clients", "body": {"full_name": "Only A"}},
        scope=scope_a,
    )
    calls: list[str] = []
    monkeypatch.setattr(
        api_module,
        "_send_request",
        lambda method, path, **kwargs: calls.append(path) or {"id": 1, "item": {"id": 1}},
    )

    result = module.replay_offline_operations(scope=scope_b)

    assert result["flushed"] == 0
    assert calls == []
    assert len(list_operations(scope=scope_a)) == 1


def test_replay_requires_active_scope_when_not_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        module,
        "require_active_account_scope",
        lambda: (_ for _ in ()).throw(RuntimeError("missing scope")),
    )

    with pytest.raises(RuntimeError, match="missing scope"):
        module.replay_offline_operations()
