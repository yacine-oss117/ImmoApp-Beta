from __future__ import annotations

import pytest

from app.services import api_write_queue as queue
from app.services.offline_account_scope import OfflineAccountScope
from app.services.offline_op_log import queue_create_operation, queue_generic_api_mutation


def _scope(suffix: str) -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_enqueue_api_mutation_replaces_existing_dedupe_key(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _scope("enqueue-replace")
    queue.clear_api_write_queue(scope=scope)
    monkeypatch.setattr(queue, "require_active_account_scope", lambda: scope)

    first_id = queue.enqueue_api_mutation(
        "PUT",
        "/clients/1",
        json_body={"name": "old"},
        dedupe_key="PUT:/clients/1",
        label="client.update",
    )
    second_id = queue.enqueue_api_mutation(
        "PUT",
        "/clients/1",
        json_body={"name": "new"},
        dedupe_key="PUT:/clients/1",
        label="client.update",
    )

    items = queue.list_pending_api_mutations(scope=scope)
    assert first_id != second_id
    assert len(items) == 1
    assert items[0]["id"] == second_id
    assert items[0]["json_body"] == {"name": "new"}


def test_enqueue_api_mutation_requires_active_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        queue,
        "require_active_account_scope",
        lambda: (_ for _ in ()).throw(RuntimeError("missing scope")),
    )

    with pytest.raises(RuntimeError, match="missing scope"):
        queue.enqueue_api_mutation(
            "PUT",
            "/clients/1",
            json_body={"name": "blocked"},
            dedupe_key="PUT:/clients/1",
            label="client.update",
        )


def test_record_failed_api_mutation_caps_history(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _scope("failed-cap")
    queue.clear_api_write_queue(scope=scope)
    monkeypatch.setattr(queue, "require_active_account_scope", lambda: scope)

    for index in range(60):
        queue.record_failed_api_mutation(
            {"id": f"q{index}", "method": "PUT", "path": f"/clients/{index}"},
            f"boom-{index}",
        )

    items = queue.list_failed_api_mutations(scope=scope)
    assert len(items) == 50
    assert items[0]["id"] == "q10"
    assert items[-1]["id"] == "q59"


def test_failed_api_mutations_remain_account_scoped() -> None:
    scope_a = _scope("failed-a")
    scope_b = _scope("failed-b")
    queue.clear_api_write_queue(scope=scope_a)
    queue.clear_api_write_queue(scope=scope_b)

    queue.record_failed_api_mutation(
        {"id": "qa", "method": "PUT", "path": "/clients/1"},
        "boom-a",
        scope=scope_a,
    )
    queue.record_failed_api_mutation(
        {"id": "qb", "method": "PUT", "path": "/clients/2"},
        "boom-b",
        scope=scope_b,
    )

    assert [item["id"] for item in queue.list_failed_api_mutations(scope=scope_a)] == ["qa"]
    assert [item["id"] for item in queue.list_failed_api_mutations(scope=scope_b)] == ["qb"]


def test_pending_api_mutation_count_only_counts_generic_api_mutations() -> None:
    scope = _scope("pending-generic")
    queue.clear_api_write_queue(scope=scope)

    queue_generic_api_mutation(
        "PUT",
        "/clients/1",
        json_body={"name": "queued"},
        dedupe_key="PUT:/clients/1",
        label="client.update",
        scope=scope,
    )
    queue_create_operation(
        "client",
        -1,
        payload={"method": "POST", "path": "/clients", "body": {"full_name": "Offline Client"}},
        parent_refs=[],
        dedupe_key="offline:create:client:-1",
        scope=scope,
    )

    assert queue.pending_api_mutation_count(scope=scope) == 1
    assert len(queue.list_pending_api_mutations(scope=scope)) == 1
