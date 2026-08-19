from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    cleanup_import_test_agency,
    create_agency,
    create_manager_user,
    ensure_django,
    token_for,
)

ensure_django()

from server.pg.schema import ensure_schema  # noqa: E402
from server.services import e2e_control  # noqa: E402

PASSWORD = "StrongTestPass_123!"


class _FakePipeline:
    def __init__(self, client: _FakeRedis) -> None:
        self._client = client
        self._ops: list[tuple[str, str]] = []

    def get(self, key: str) -> _FakePipeline:
        self._ops.append(("get", key))
        return self

    def delete(self, key: str) -> _FakePipeline:
        self._ops.append(("delete", key))
        return self

    def execute(self) -> list[object]:
        results: list[object] = []
        for operation, key in self._ops:
            if operation == "get":
                results.append(self._client.store.get(key))
            elif operation == "delete":
                existed = key in self._client.store
                self._client.store.pop(key, None)
                results.append(int(existed))
        return results


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def setex(self, key: str, ttl: int, value: str) -> None:
        _ = ttl
        self.store[key] = value

    def exists(self, key: str) -> int:
        return int(key in self.store)

    def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self.store:
                deleted += 1
                self.store.pop(key, None)
        return deleted

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        _ = transaction
        return _FakePipeline(self)


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    client = _FakeRedis()
    monkeypatch.setattr(e2e_control, "_redis_client", lambda: client)
    return client


def _make_user(prefix: str) -> tuple[int, int, str]:
    ensure_schema()
    conn = admin_conn()
    try:
        suffix = uuid.uuid4().hex[:8]
        agency_id = create_agency(conn, f"{prefix}{suffix}", f"{prefix} Agency")
        username = f"{prefix.lower()}_{suffix}"
        user_id = create_manager_user(
            conn, agency_id=agency_id, username=username, password=PASSWORD
        )
        conn.commit()
    finally:
        conn.close()
    get_user_model().objects.get(id=user_id)
    return int(agency_id), int(user_id), username


def _auth_headers(username: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token_for(username, PASSWORD)}"}


def _cleanup_user(*, agency_id: int, user_id: int) -> None:
    conn = admin_conn()
    try:
        conn.execute("DELETE FROM match_counts_cache WHERE agency_id = %s", (agency_id,))
        conn.commit()
    finally:
        conn.close()
    cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)


def test_consume_route_fault_noops_when_disabled_with_preseeded_key(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: _FakeRedis,
) -> None:
    monkeypatch.setenv("IMMOAPP_E2E_TEST_MODE", "1")
    e2e_control.inject_route_fault(
        user_id=123,
        route_template="clients/",
        status_code=503,
        detail="seeded",
        code="SEEDED",
    )
    assert fake_redis.store

    monkeypatch.delenv("IMMOAPP_E2E_TEST_MODE", raising=False)

    assert e2e_control.consume_route_fault(user_id=123, route_template="clients/") is None
    assert fake_redis.store


def test_preseeded_route_fault_cannot_affect_normal_route_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: _FakeRedis,
) -> None:
    monkeypatch.setenv("IMMOAPP_E2E_TEST_MODE", "1")
    agency_id, user_id, username = _make_user("E2EGATE")
    try:
        e2e_control.inject_route_fault(
            user_id=user_id,
            route_template="clients/",
            status_code=503,
            detail="should not fire",
            code="DISABLED_FAULT",
        )
        assert fake_redis.store
        monkeypatch.delenv("IMMOAPP_E2E_TEST_MODE", raising=False)

        response = Client().get(
            "/api/v1/clients/?limit=1&offset=0",
            HTTP_HOST="localhost",
            **_auth_headers(username),
        )

        assert response.status_code == 200
    finally:
        _cleanup_user(agency_id=agency_id, user_id=user_id)


@pytest.mark.parametrize(
    ("operation", "call"),
    [
        (
            "publish_user_notification",
            lambda: e2e_control.publish_user_notification(
                agency_id=None,
                user_id=1,
                event_type="desktop.e2e.test",
                title="disabled",
                body="disabled",
            ),
        ),
        (
            "schedule_next_import_pause",
            lambda: e2e_control.schedule_next_import_pause(user_id=1, seconds=1.0),
        ),
        (
            "inject_route_fault",
            lambda: e2e_control.inject_route_fault(
                user_id=1,
                route_template="clients/",
                status_code=503,
                detail="disabled",
                code="DISABLED",
            ),
        ),
    ],
)
def test_e2e_mutators_raise_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    call: Any,
) -> None:
    monkeypatch.delenv("IMMOAPP_E2E_TEST_MODE", raising=False)

    with pytest.raises(RuntimeError, match=operation):
        call()


def test_import_pause_consumers_noop_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: _FakeRedis,
) -> None:
    fake_redis.store["immoapp:e2e:import-pause-next:5"] = "10.000"
    fake_redis.store["immoapp:e2e:import-pause-job:job-1"] = "10.000"
    fake_redis.store["immoapp:e2e:import-pause-armed:job-1"] = "10.000"
    monkeypatch.delenv("IMMOAPP_E2E_TEST_MODE", raising=False)

    assert e2e_control.arm_pending_import_pause_for_job(user_id=5, job_id="job-1") is None
    assert e2e_control.pause_armed_for_job(job_id="job-1") is False
    assert e2e_control.maybe_pause_import_job(job_id="job-1") == 0.0
    e2e_control.clear_import_pause_for_job(job_id="job-1")
    assert fake_redis.store


def test_enabled_route_fault_and_import_pause_behaviors_still_work(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: _FakeRedis,
) -> None:
    _ = fake_redis
    monkeypatch.setenv("IMMOAPP_E2E_TEST_MODE", "1")

    e2e_control.inject_route_fault(
        user_id=77,
        route_template="clients/",
        status_code=503,
        detail="enabled",
        code="ENABLED",
    )
    fault = e2e_control.consume_route_fault(user_id=77, route_template="clients/")
    assert fault is not None
    assert fault.status_code == 503
    assert fault.payload()["code"] == "ENABLED"

    assert e2e_control.schedule_next_import_pause(user_id=88, seconds=2.5) == 2.5
    assert e2e_control.arm_pending_import_pause_for_job(user_id=88, job_id="job-2") == 2.5
    assert e2e_control.pause_armed_for_job(job_id="job-2") is True
