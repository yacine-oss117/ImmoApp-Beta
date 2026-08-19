from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from rest_framework.response import Response

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

import server.api.idempotency_engine as idempotency_engine  # noqa: E402
from core.contracts.idempotency_contract import (  # noqa: E402
    ERR_UNVERIFIABLE,
    IDEMPOTENCY_HMAC_PAYLOAD_VERSION,
    IdempotencyScope,
)


class _FakeTransactionContext:
    def __init__(self, session: object) -> None:
        self._session = session

    def __enter__(self) -> object:
        return self._session

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        _ = (exc_type, exc, tb)
        return False


class _NoopSession:
    def execute(self, _sql: str, _params: object = ()) -> object:
        return SimpleNamespace(fetchone=lambda: None)


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[tuple[str, object]] = []

    def execute(self, sql: str, params: object = ()) -> object:
        self.statements.append((sql, params))
        return SimpleNamespace(fetchone=lambda: None)


class _FakeUow:
    def __init__(self, session: object) -> None:
        self._session = session

    def transaction(self) -> _FakeTransactionContext:
        return _FakeTransactionContext(self._session)


def _signed_completed_row(*, key_id: str, key_value: str) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    row = {
        "agency_id": 7,
        "normalized_route": "/api/v1/clients/",
        "method": "POST",
        "idempotency_key": "idem-refresh",
        "canonical_body_hash": "body-hash",
        "normalized_query_hash": "query-hash",
        "semantic_headers_hash": "headers-hash",
        "status_code": 201,
        "response_body_hash": "response-hash",
        "response_content_type": "application/json",
        "response_headers_json": {},
        "response_body_json": {"id": 11},
        "created_at": now,
        "expires_at": now + timedelta(hours=1),
        "signature_key_id": key_id,
        "hmac_payload_version": IDEMPOTENCY_HMAC_PAYLOAD_VERSION,
    }
    row["record_hmac"] = idempotency_engine._compute_record_hmac(
        idempotency_engine._normalize_hmac_row(dict(row)),
        key=key_value,
    )
    return row


def test_idempotency_hmac_keyring_refreshes_after_ttl_without_restart(
    monkeypatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(idempotency_engine.time, "monotonic", lambda: clock[0])
    monkeypatch.setenv("IMMOAPP_SECRETS_BACKEND", "env")
    monkeypatch.setenv("IMMOAPP_IDEMPOTENCY_HMAC_REFRESH_TTL_SECONDS", "1")
    monkeypatch.setenv("IMMOAPP_IDEMPOTENCY_HMAC_KEY", "alpha")
    monkeypatch.setenv("IMMOAPP_IDEMPOTENCY_HMAC_KEY_ID", "k1")
    idempotency_engine._invalidate_hmac_keyring_cache()

    assert idempotency_engine._resolve_hmac_key() == ("alpha", "k1")

    monkeypatch.setenv("IMMOAPP_IDEMPOTENCY_HMAC_KEY", "beta")
    monkeypatch.setenv("IMMOAPP_IDEMPOTENCY_HMAC_KEY_ID", "k2")

    clock[0] = 0.5
    assert idempotency_engine._resolve_hmac_key() == ("alpha", "k1")

    clock[0] = 2.0
    assert idempotency_engine._resolve_hmac_key() == ("beta", "k2")


def test_idempotency_hmac_cache_reset_hook_stays_internal() -> None:
    assert "_invalidate_hmac_keyring_cache" not in getattr(idempotency_engine, "__all__", [])


def test_completed_replay_refreshes_keyring_for_new_signature_key_and_fails_safe_when_missing(
    monkeypatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(idempotency_engine.time, "monotonic", lambda: clock[0])
    monkeypatch.setenv("IMMOAPP_SECRETS_BACKEND", "env")
    monkeypatch.setenv("IMMOAPP_IDEMPOTENCY_HMAC_REFRESH_TTL_SECONDS", "60")
    monkeypatch.setenv("IMMOAPP_IDEMPOTENCY_HMAC_KEYS_JSON", '{"k1":"alpha"}')
    monkeypatch.setenv("IMMOAPP_IDEMPOTENCY_HMAC_ACTIVE_KEY_ID", "k1")
    idempotency_engine._invalidate_hmac_keyring_cache()
    assert idempotency_engine._resolve_hmac_key(signature_key_id="k1") == ("alpha", "k1")

    monkeypatch.setenv(
        "IMMOAPP_IDEMPOTENCY_HMAC_KEYS_JSON",
        '{"k1":"alpha","k2":"beta"}',
    )
    monkeypatch.setenv("IMMOAPP_IDEMPOTENCY_HMAC_ACTIVE_KEY_ID", "k2")
    row = _signed_completed_row(key_id="k2", key_value="beta")

    response = idempotency_engine._completed_replay_or_integrity_error(
        dict(row),
        raw_key="idem-refresh",
    )

    assert response.status_code == 201
    assert response["Idempotency-Status"] == "replayed"

    monkeypatch.setenv("IMMOAPP_IDEMPOTENCY_HMAC_KEYS_JSON", '{"k1":"alpha"}')
    idempotency_engine._invalidate_hmac_keyring_cache()

    unverifiable = idempotency_engine._completed_replay_or_integrity_error(
        dict(row),
        raw_key="idem-refresh",
    )

    assert unverifiable.status_code == 409
    assert unverifiable.data["code"] == ERR_UNVERIFIABLE


def test_check_idempotency_returns_immediate_in_progress_response_without_busy_polling(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    request = SimpleNamespace(
        method="POST",
        path="/api/v1/clients/",
        resolver_match=None,
        query_params={},
        data={"family_name": "Idem"},
        headers={"X-Idempotency-Key": "idem-in-progress"},
        user=None,
    )
    row = {
        "id": 44,
        "canonical_body_hash": idempotency_engine._body_hash(request),
        "normalized_query_hash": idempotency_engine.canonical_query_hash({}),
        "semantic_headers_hash": idempotency_engine._semantic_headers_hash(request),
        "state": "in_progress",
        "lease_until": now + timedelta(seconds=30),
        "created_at": now,
        "expires_at": now + timedelta(hours=1),
    }
    fetch_calls: list[int] = []
    monkeypatch.setattr(idempotency_engine, "get_uow", lambda: _FakeUow(_NoopSession()))
    monkeypatch.setattr(
        idempotency_engine, "_try_insert_in_progress_record", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(idempotency_engine, "_select_locked_record", lambda *args, **kwargs: row)
    monkeypatch.setattr(
        idempotency_engine,
        "_fetch_record",
        lambda *args, **kwargs: fetch_calls.append(1) or dict(row),
    )
    monkeypatch.setattr(
        idempotency_engine.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep must not be called")),
    )

    context, response = idempotency_engine.check_idempotency(request)

    assert context is None
    assert response is not None
    assert response.status_code == 202
    assert response["Idempotency-Status"] == "in_progress"
    assert response["Retry-After"] == "2"
    assert fetch_calls == [1]


def test_store_idempotency_uses_single_update_with_context_metadata_and_hmac(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    session = _RecordingSession()
    response = Response({"id": 91}, status=201)
    response["Content-Type"] = "application/json"
    response["ETag"] = "etag-1"
    context = idempotency_engine.IdempotencyContext(
        scope=IdempotencyScope(
            agency_id=7,
            normalized_route="/api/v1/clients/",
            method="POST",
            idempotency_key="idem-store",
        ),
        canonical_body_hash="body-hash",
        normalized_query_hash="query-hash",
        semantic_headers_hash="headers-hash",
        policy=None,
        raw_key_header="Idempotency-Key",
        lease_owner="req-1",
        record_id=12,
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    monkeypatch.setenv("IMMOAPP_SECRETS_BACKEND", "env")
    monkeypatch.setenv("IMMOAPP_IDEMPOTENCY_HMAC_KEY", "alpha")
    monkeypatch.setenv("IMMOAPP_IDEMPOTENCY_HMAC_KEY_ID", "k1")
    idempotency_engine._invalidate_hmac_keyring_cache()
    monkeypatch.setattr(idempotency_engine, "get_uow", lambda: _FakeUow(session))

    stored = idempotency_engine.store_idempotency(context, response, SimpleNamespace())

    assert stored["Idempotency-Status"] == "created"
    assert len(session.statements) == 1
    sql, params = session.statements[0]
    assert "UPDATE api_idempotency_records" in sql
    assert "record_hmac = %s" in sql
    assert "WHERE id = %s" in sql
    assert "SELECT " not in sql
    assert params[7] is not None
    assert params[8] == "k1"
    assert params[9] == IDEMPOTENCY_HMAC_PAYLOAD_VERSION
