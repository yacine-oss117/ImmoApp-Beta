from __future__ import annotations

import pytest

import app.services.api_client as api_module
from app.services import offline_reconciler as reconciler
from app.services.offline_account_scope import OfflineAccountScope
from app.services.offline_op_log import queue_create_operation
from app.services.offline_projection import OfflineProjectionRecord, upsert_projection_record


def _scope(suffix: str = "chaos") -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_retryable_replay_reuses_same_idempotency_key(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _scope("idempotency")
    op = queue_create_operation(
        "client",
        -1,
        payload={
            "method": "POST",
            "path": "/clients",
            "body": {"full_name": "Offline Client"},
            "headers": {"Idempotency-Key": "offline:test:key"},
        },
        dedupe_key="offline:test:key",
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

    seen_headers: list[str] = []

    def _send(method: str, path: str, **kwargs):
        headers = kwargs.get("headers") or {}
        seen_headers.append(str(headers.get("Idempotency-Key") or ""))
        if len(seen_headers) == 1:
            raise RuntimeError("network jitter")
        return {"id": 51, "item": {"id": 51, "family_name": "Offline Client"}}

    monkeypatch.setattr(api_module, "_send_request", _send)

    first = reconciler.replay_offline_operations(scope=scope)
    second = reconciler.replay_offline_operations(scope=scope)

    assert first["retryable"] == 1
    assert second["flushed"] == 1
    assert seen_headers == ["offline:test:key", "offline:test:key"]


def test_replay_limit_caps_reconnect_burst_per_account(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _scope("limit")
    for idx in range(3):
        queue_create_operation(
            "client",
            -(idx + 1),
            payload={
                "method": "POST",
                "path": "/clients",
                "body": {"full_name": f"Client {idx}"},
                "headers": {"Idempotency-Key": f"offline:test:{idx}"},
            },
            dedupe_key=f"offline:test:{idx}",
            scope=scope,
        )
        upsert_projection_record(
            OfflineProjectionRecord(
                entity_type="client",
                local_id=-(idx + 1),
                server_id=None,
                data={"id": -(idx + 1), "full_name": f"Client {idx}"},
                sync_status="pending",
                is_local_only=True,
            ),
            scope=scope,
        )

    calls: list[str] = []
    monkeypatch.setattr(
        api_module,
        "_send_request",
        lambda method, path, **kwargs: calls.append(path)
        or {"id": len(calls), "item": {"id": len(calls)}},
    )

    result = reconciler.replay_offline_operations(limit=2, scope=scope)

    assert result["flushed"] == 2
    assert len(calls) == 2


def test_replay_isolated_per_account_under_retry_pressure(monkeypatch: pytest.MonkeyPatch) -> None:
    scope_a = _scope("acct-a")
    scope_b = _scope("acct-b")

    for scope, suffix in ((scope_a, "a"), (scope_b, "b")):
        queue_create_operation(
            "client",
            -1,
            payload={
                "method": "POST",
                "path": f"/clients/{suffix}",
                "body": {"full_name": f"Client {suffix}"},
                "headers": {"Idempotency-Key": f"offline:test:{suffix}"},
            },
            dedupe_key=f"offline:test:{suffix}",
            scope=scope,
        )
        upsert_projection_record(
            OfflineProjectionRecord(
                entity_type="client",
                local_id=-1,
                server_id=None,
                data={"id": -1, "full_name": f"Client {suffix}"},
                sync_status="pending",
                is_local_only=True,
            ),
            scope=scope,
        )

    seen_paths: list[str] = []

    def _send(method: str, path: str, **kwargs):
        seen_paths.append(path)
        if path.endswith("/a"):
            raise RuntimeError("jitter")
        return {"id": 9, "item": {"id": 9}}

    monkeypatch.setattr(api_module, "_send_request", _send)

    first = reconciler.replay_offline_operations(scope=scope_a)
    second = reconciler.replay_offline_operations(scope=scope_b)

    assert first["retryable"] == 1
    assert second["flushed"] == 1
    assert seen_paths == ["/clients/a", "/clients/b"]
