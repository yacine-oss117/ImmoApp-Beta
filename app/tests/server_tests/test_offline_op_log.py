from __future__ import annotations

import json

from app.services.offline_account_scope import OfflineAccountScope, get_account_root
from app.services.offline_op_log import (
    discard_operation,
    list_operations,
    queue_create_operation,
    queue_delete_operation,
    queue_generic_api_mutation,
    queue_update_operation,
    refresh_blocked_operations,
)
from app.services.offline_projection import (
    OfflineProjectionRecord,
    get_projection_record,
    upsert_projection_record,
)
from app.services.offline_types import OfflineEntityRef


def _scope(suffix: str = "oplog") -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def _drop_pending_snapshot(scope: OfflineAccountScope) -> None:
    path = get_account_root(scope) / "pending_snapshot.json"
    if path.exists():
        path.unlink()


def test_update_on_temp_create_merges_into_create() -> None:
    scope = _scope()
    create_op = queue_create_operation(
        "client",
        -1,
        payload={"method": "POST", "path": "/clients", "body": {"full_name": "A"}},
        dedupe_key="offline:create:client:-1",
        scope=scope,
    )

    merged = queue_update_operation(
        "client",
        -1,
        payload={"method": "PUT", "path": "/clients/-1", "body": {"phone": "123"}},
        dedupe_key="PUT:/clients/-1",
        scope=scope,
    )

    assert merged is not None
    assert merged.op_id == create_op.op_id
    assert merged.payload["body"] == {"full_name": "A", "phone": "123"}
    assert len(list_operations(scope=scope)) == 1


def test_delete_on_temp_create_cancels_parent_and_dependent_children() -> None:
    scope = _scope("delete-temp")
    parent = queue_create_operation(
        "client",
        -1,
        payload={"method": "POST", "path": "/clients", "body": {"full_name": "Parent"}},
        scope=scope,
    )
    child = queue_create_operation(
        "demande",
        -1,
        payload={
            "method": "POST",
            "path_template": "/clients/{client_id}/demandes",
            "body": {"budget_min": 1},
        },
        parent_refs=[OfflineEntityRef(entity_type="client", local_id=-1)],
        scope=scope,
    )
    upsert_projection_record(
        OfflineProjectionRecord(
            entity_type="client",
            local_id=-1,
            server_id=None,
            data={"id": -1, "full_name": "Parent"},
            sync_status=parent.status,
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
            sync_status=child.status,
            is_local_only=True,
        ),
        scope=scope,
    )

    result = queue_delete_operation("client", -1, scope=scope)

    assert result is None
    assert list_operations(scope=scope) == []
    assert get_projection_record("client", -1, scope=scope) is None
    assert get_projection_record("demande", -1, scope=scope) is None


def test_discard_operation_removes_dependent_temp_creates() -> None:
    scope = _scope("discard")
    parent = queue_create_operation(
        "listing",
        -1,
        payload={"method": "POST", "path": "/listings", "body": {"title": "L"}},
        scope=scope,
    )
    queue_create_operation(
        "offer",
        -1,
        payload={
            "method": "POST",
            "path_template": "/listings/{listing_id}/offers",
            "body": {"price": 10},
        },
        parent_refs=[OfflineEntityRef(entity_type="listing", local_id=-1)],
        scope=scope,
    )

    discard_operation(parent.op_id, scope=scope)

    assert list_operations(scope=scope) == []


def test_refresh_blocked_operations_unblocks_when_parent_resolved() -> None:
    from app.services.offline_ids import record_reconciled_id

    scope = _scope("refresh")
    queue_create_operation(
        "demande",
        -1,
        payload={
            "method": "POST",
            "path_template": "/clients/{client_id}/demandes",
            "body": {"budget_min": 1},
        },
        parent_refs=[OfflineEntityRef(entity_type="client", local_id=-2)],
        scope=scope,
    )

    assert list_operations(scope=scope)[0].status == "blocked"

    record_reconciled_id("client", -2, 99, scope=scope)
    changed = refresh_blocked_operations(scope=scope)

    assert changed == 1
    assert list_operations(scope=scope)[0].status == "pending"


def test_delete_removes_stale_updates_from_journal_rebuild() -> None:
    scope = _scope("delete-rebuild")
    queue_update_operation(
        "client",
        7,
        payload={"method": "PUT", "path": "/clients/7", "body": {"full_name": "Queued"}},
        dedupe_key="PUT:/clients/7",
        scope=scope,
    )

    delete_op = queue_delete_operation(
        "client",
        7,
        payload={"method": "DELETE", "path": "/clients/7"},
        dedupe_key="DELETE:/clients/7",
        scope=scope,
    )

    _drop_pending_snapshot(scope)
    rebuilt = list_operations(scope=scope)

    assert [op.op_type for op in rebuilt] == ["delete"]
    assert rebuilt[0].op_id == delete_op.op_id


def test_generic_dedupe_removal_survives_journal_rebuild() -> None:
    scope = _scope("generic-dedupe")
    queue_generic_api_mutation(
        "POST",
        "/crm/contracts/9/print",
        json_body={"copy": False},
        dedupe_key="POST:/crm/contracts/9/print",
        label="contract.print",
        scope=scope,
    )
    latest = queue_generic_api_mutation(
        "POST",
        "/crm/contracts/9/print",
        json_body={"copy": True},
        dedupe_key="POST:/crm/contracts/9/print",
        label="contract.print",
        scope=scope,
    )

    _drop_pending_snapshot(scope)
    rebuilt = list_operations(scope=scope)

    assert len(rebuilt) == 1
    assert rebuilt[0].op_id == latest.op_id
    assert rebuilt[0].payload["body"] == {"copy": True}


def test_refresh_blocked_status_change_survives_journal_rebuild() -> None:
    from app.services.offline_ids import record_reconciled_id

    scope = _scope("refresh-rebuild")
    queue_create_operation(
        "demande",
        -1,
        payload={
            "method": "POST",
            "path_template": "/clients/{client_id}/demandes",
            "body": {"budget_min": 1},
        },
        parent_refs=[OfflineEntityRef(entity_type="client", local_id=-2)],
        scope=scope,
    )
    record_reconciled_id("client", -2, 99, scope=scope)

    assert refresh_blocked_operations(scope=scope) == 1
    _drop_pending_snapshot(scope)

    rebuilt = list_operations(scope=scope)
    assert len(rebuilt) == 1
    assert rebuilt[0].status == "pending"


def test_note_attempt_survives_journal_rebuild() -> None:
    from app.services.offline_op_log import note_operation_attempt

    scope = _scope("attempt-rebuild")
    op = queue_generic_api_mutation(
        "PUT",
        "/clients/7",
        json_body={"full_name": "Retry"},
        dedupe_key="PUT:/clients/7",
        label="client.update",
        scope=scope,
    )

    note_operation_attempt(op.op_id, "temporary failure", scope=scope)
    _drop_pending_snapshot(scope)

    rebuilt = list_operations(scope=scope)
    assert len(rebuilt) == 1
    assert rebuilt[0].attempts == 1
    assert rebuilt[0].last_error == "temporary failure"


def test_list_operations_does_not_rewrite_existing_meta(
    monkeypatch,
) -> None:
    scope = _scope("meta-stable")
    root = get_account_root(scope)
    root.mkdir(parents=True, exist_ok=True)
    (root / "meta.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "last_sync_at": "",
                "compacted_at": "",
            }
        ),
        encoding="utf-8",
    )
    (root / "pending_snapshot.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(
        "app.services.offline_op_log.write_json_atomic",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected meta rewrite")),
    )

    assert list_operations(scope=scope) == []


def test_list_operations_tolerates_transient_meta_write_failure(
    monkeypatch,
) -> None:
    scope = _scope("meta-locked")
    root = get_account_root(scope)
    root.mkdir(parents=True, exist_ok=True)
    (root / "pending_snapshot.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(
        "app.services.offline_op_log.write_json_atomic",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("locked")),
    )

    assert list_operations(scope=scope) == []
