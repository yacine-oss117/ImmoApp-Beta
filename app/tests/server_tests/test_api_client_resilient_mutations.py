from __future__ import annotations

import pytest

from app.services import api_client as module
from app.services import api_write_queue as queue_module
from app.services.api_client_errors import ApiError
from app.services.api_write_queue import (
    clear_api_write_queue,
    failed_api_mutation_count,
    pending_api_mutation_count,
)
from app.services.offline_account_scope import OfflineAccountScope
from app.services.offline_op_log import queue_generic_api_mutation


@pytest.fixture(autouse=True)
def _clear_queue() -> None:
    clear_api_write_queue()
    yield
    clear_api_write_queue()


def _scope(suffix: str = "scope") -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_resilient_mutation_queues_transient_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _scope("queue-transient")
    monkeypatch.setattr(module, "get_active_account_scope", lambda: scope)
    monkeypatch.setattr(queue_module, "require_active_account_scope", lambda: scope)
    monkeypatch.setattr(
        module,
        "_send_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    result = module.api_put_resilient(
        "/clients/7",
        {"name": "queued"},
        dedupe_key="PUT:/clients/7",
        label="client.update",
    )

    assert result.queued is True
    assert pending_api_mutation_count(scope=scope) == 1


def test_resilient_mutation_does_not_queue_permanent_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "get_active_account_scope", lambda: _scope("queue-permanent"))
    monkeypatch.setattr(
        module,
        "_send_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(ApiError(400, "bad request")),
    )

    with pytest.raises(ApiError):
        module.api_put_resilient(
            "/clients/7",
            {"name": "bad"},
            dedupe_key="PUT:/clients/7",
            label="client.update",
        )

    assert pending_api_mutation_count() == 0


def test_flush_pending_api_mutations_replays_successfully(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _scope("flush-success")
    monkeypatch.setattr(module, "get_active_account_scope", lambda: scope)
    queue_generic_api_mutation(
        "PUT",
        "/clients/7",
        json_body={"name": "queued"},
        dedupe_key="PUT:/clients/7",
        label="client.update",
        scope=scope,
    )

    monkeypatch.setattr(module, "get_offline_mode", lambda: False)
    calls: list[tuple[str, str]] = []

    def _send(method: str, path: str, **kwargs):
        calls.append((method, path))
        return {"ok": True}

    monkeypatch.setattr(module, "_send_request", _send)

    result = module.flush_pending_api_mutations(scope=scope)

    assert calls == [("PUT", "/clients/7")]
    assert result["flushed"] == 1
    assert result["pending"] == 0


def test_flush_pending_api_mutations_discards_permanent_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope("flush-discard")
    monkeypatch.setattr(module, "get_active_account_scope", lambda: scope)
    queue_generic_api_mutation(
        "PUT",
        "/clients/7",
        json_body={"name": "queued"},
        dedupe_key="PUT:/clients/7",
        label="client.update",
        scope=scope,
    )

    monkeypatch.setattr(module, "get_offline_mode", lambda: False)
    monkeypatch.setattr(
        module,
        "_send_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(ApiError(409, "conflict")),
    )

    result = module.flush_pending_api_mutations(scope=scope)

    assert result["discarded"] == 1
    assert result["pending"] == 0
    assert failed_api_mutation_count(scope=scope) == 1


def test_flush_pending_api_mutations_no_active_scope_does_not_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "get_offline_mode", lambda: False)
    monkeypatch.setattr(module, "get_active_account_scope", lambda: None)

    result = module.flush_pending_api_mutations()

    assert result == {"flushed": 0, "pending": 0, "discarded": 0, "failed_permanent": 0}
