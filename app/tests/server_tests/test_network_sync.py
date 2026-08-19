from __future__ import annotations

from app.services import network_sync as module
from app.services.offline_account_scope import OfflineAccountScope


def _scope(suffix: str = "scope") -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_network_status_snapshot_marks_pending_work(monkeypatch) -> None:
    monkeypatch.setattr(module, "get_offline_mode", lambda: False)
    monkeypatch.setattr(module, "get_active_account_scope", lambda: _scope())
    monkeypatch.setattr(
        module,
        "list_operations",
        lambda *, scope=None: [
            type("Op", (), {"op_type": "update", "status": "pending"})(),
            type("Op", (), {"op_type": "delete", "status": "pending"})(),
        ],
    )
    monkeypatch.setattr(module, "pending_api_mutation_count", lambda *, scope=None: 1)
    monkeypatch.setattr(module, "pending_media_upload_count", lambda *, scope=None: 1)
    monkeypatch.setattr(module, "failed_api_mutation_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "needs_review_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "get_api_circuit_snapshot", lambda: {"state": "closed"})

    snapshot = module.get_network_status_snapshot()

    assert snapshot["state"] == "pending"
    assert snapshot["pending_total"] == 3
    assert snapshot["pending_ops"] == 2
    assert snapshot["pending_api"] == 1


def test_network_status_snapshot_marks_degraded_circuit(monkeypatch) -> None:
    monkeypatch.setattr(module, "get_offline_mode", lambda: False)
    monkeypatch.setattr(module, "get_active_account_scope", lambda: _scope())
    monkeypatch.setattr(module, "list_operations", lambda *, scope=None: [])
    monkeypatch.setattr(module, "pending_api_mutation_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "pending_media_upload_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "failed_api_mutation_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "needs_review_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "get_api_circuit_snapshot", lambda: {"state": "open"})

    snapshot = module.get_network_status_snapshot()

    assert snapshot["state"] == "degraded"


def test_network_status_snapshot_marks_pending_creates_without_generic_queue(monkeypatch) -> None:
    monkeypatch.setattr(module, "get_offline_mode", lambda: False)
    monkeypatch.setattr(module, "get_active_account_scope", lambda: _scope("creates"))
    monkeypatch.setattr(
        module,
        "list_operations",
        lambda *, scope=None: [type("Op", (), {"op_type": "create", "status": "pending"})()],
    )
    monkeypatch.setattr(module, "pending_api_mutation_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "pending_media_upload_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "failed_api_mutation_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "needs_review_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "get_api_circuit_snapshot", lambda: {"state": "closed"})

    snapshot = module.get_network_status_snapshot()

    assert snapshot["state"] == "pending"
    assert snapshot["pending_creates"] == 1
    assert snapshot["pending_total"] == 1


def test_network_status_snapshot_ignores_compatibility_scope_without_active_account(
    monkeypatch,
) -> None:
    monkeypatch.setattr(module, "get_offline_mode", lambda: False)
    monkeypatch.setattr(module, "get_active_account_scope", lambda: None)
    monkeypatch.setattr(module, "pending_api_mutation_count", lambda *, scope=None: 99)
    monkeypatch.setattr(module, "pending_media_upload_count", lambda *, scope=None: 99)
    monkeypatch.setattr(module, "failed_api_mutation_count", lambda *, scope=None: 99)
    monkeypatch.setattr(module, "get_api_circuit_snapshot", lambda: {"state": "closed"})

    snapshot = module.get_network_status_snapshot()

    assert snapshot["pending_api"] == 0
    assert snapshot["pending_media"] == 0
    assert snapshot["failed_api"] == 0
    assert snapshot["pending_total"] == 0


def test_network_status_snapshot_falls_back_when_scope_lookup_fails(monkeypatch) -> None:
    monkeypatch.setattr(module, "get_offline_mode", lambda: False)
    monkeypatch.setattr(
        module,
        "get_active_account_scope",
        lambda: (_ for _ in ()).throw(RuntimeError("locked out")),
    )
    monkeypatch.setattr(module, "pending_api_mutation_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "pending_media_upload_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "failed_api_mutation_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "needs_review_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "get_api_circuit_snapshot", lambda: {"state": "closed"})

    snapshot = module.get_network_status_snapshot()

    assert snapshot["state"] == "online"
    assert snapshot["pending_total"] == 0


def test_network_status_snapshot_fails_soft_when_offline_store_is_locked(monkeypatch) -> None:
    monkeypatch.setattr(module, "get_offline_mode", lambda: False)
    monkeypatch.setattr(module, "get_active_account_scope", lambda: _scope("locked"))
    monkeypatch.setattr(
        module,
        "list_operations",
        lambda *, scope=None: (_ for _ in ()).throw(PermissionError("locked")),
    )
    monkeypatch.setattr(module, "get_api_circuit_snapshot", lambda: {"state": "closed"})

    snapshot = module.get_network_status_snapshot()

    assert snapshot["state"] == "error"
    assert snapshot["store_error"] is True
    assert snapshot["pending_total"] == 0


def test_flush_pending_network_work_probes_and_combines_results(monkeypatch) -> None:
    scope = _scope("flush")
    monkeypatch.setattr(module, "get_offline_mode", lambda: False)
    monkeypatch.setattr(module, "get_active_account_scope", lambda: scope)
    monkeypatch.setattr(module, "list_operations", lambda *, scope=None: [])
    monkeypatch.setattr(module, "pending_api_mutation_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "pending_media_upload_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "failed_api_mutation_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "needs_review_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "get_api_circuit_snapshot", lambda: {"state": "open"})
    probes: list[str] = []
    monkeypatch.setattr(module, "api_get", lambda path: probes.append(path) or {"ok": True})
    seen_scopes: list[OfflineAccountScope | None] = []
    monkeypatch.setattr(
        module,
        "flush_pending_api_mutations",
        lambda limit=50, *, scope=None: seen_scopes.append((scope, limit))
        or {"flushed": 2, "discarded": 1, "pending": 0},
    )
    monkeypatch.setattr(
        module,
        "flush_pending_media_uploads",
        lambda *, scope=None: seen_scopes.append(scope) or 3,
    )

    summary = module.flush_pending_network_work()

    assert probes == ["/health"]
    assert seen_scopes == [(scope, module._API_SYNC_BATCH_LIMIT), scope]
    assert summary["flushed_api"] == 2
    assert summary["discarded_api"] == 1
    assert summary["flushed_media"] == 3


def test_flush_pending_network_work_skips_replay_without_active_scope(monkeypatch) -> None:
    monkeypatch.setattr(module, "get_offline_mode", lambda: False)
    monkeypatch.setattr(module, "get_active_account_scope", lambda: None)
    monkeypatch.setattr(module, "list_operations", lambda *, scope=None: [])
    monkeypatch.setattr(module, "pending_api_mutation_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "pending_media_upload_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "failed_api_mutation_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "needs_review_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "get_api_circuit_snapshot", lambda: {"state": "closed"})
    api_calls: list[object] = []
    media_calls: list[object] = []
    monkeypatch.setattr(
        module,
        "flush_pending_api_mutations",
        lambda limit=50, *, scope=None: api_calls.append((scope, limit))
        or {"flushed": 0, "discarded": 0, "pending": 0},
    )
    monkeypatch.setattr(
        module,
        "flush_pending_media_uploads",
        lambda *, scope=None: media_calls.append(scope) or 0,
    )

    summary = module.flush_pending_network_work()

    assert api_calls == [(None, module._API_SYNC_BATCH_LIMIT)]
    assert media_calls == [None]
    assert summary["flushed_api"] == 0
    assert summary["flushed_media"] == 0


def test_flush_pending_network_work_does_not_probe_api_without_active_scope(monkeypatch) -> None:
    monkeypatch.setattr(module, "get_offline_mode", lambda: False)
    monkeypatch.setattr(module, "get_active_account_scope", lambda: None)
    monkeypatch.setattr(module, "list_operations", lambda *, scope=None: [])
    monkeypatch.setattr(module, "pending_api_mutation_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "pending_media_upload_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "failed_api_mutation_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "needs_review_count", lambda *, scope=None: 0)
    monkeypatch.setattr(module, "get_api_circuit_snapshot", lambda: {"state": "open"})
    probes: list[str] = []
    monkeypatch.setattr(module, "api_get", lambda path: probes.append(path) or {"ok": True})
    monkeypatch.setattr(
        module,
        "flush_pending_api_mutations",
        lambda limit=50, *, scope=None: {"flushed": 0, "discarded": 0, "pending": 0},
    )
    monkeypatch.setattr(module, "flush_pending_media_uploads", lambda *, scope=None: 0)

    summary = module.flush_pending_network_work()

    assert probes == []
    assert summary["flushed_api"] == 0
