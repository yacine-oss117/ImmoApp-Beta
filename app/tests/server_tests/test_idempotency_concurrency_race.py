from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from django.test import Client

from server.api.route_registry import resolve_route_template

pytest.importorskip("psycopg", reason="idempotency concurrency tests require server dependencies")

from app.tests.server_tests._integration_auth_helpers import (  # noqa: E402
    admin_conn,
    cleanup_import_test_agency,
    create_agency,
    create_manager_user,
    ensure_django,
    token_for,
)

ensure_django()

import server.api.idempotency_engine as idempotency_engine  # noqa: E402
import server.api.views_clients_list as views_clients_list  # noqa: E402

_CLIENTS_ROUTE = "/api/v1/clients/"


def _normalized_clients_route() -> str:
    return resolve_route_template(None, request_path=_CLIENTS_ROUTE)


def _legacy_semantic_headers_hash() -> str:
    return hashlib.sha256(idempotency_engine.canonical_json_dumps({}).encode("utf-8")).hexdigest()


def _phone_from_suffix(prefix: str, suffix: str) -> str:
    digits = str(int(suffix, 16))[-6:].rjust(6, "0")
    return f"{prefix}{digits}"


def _auth_headers(
    *,
    token: str,
    idem_key: str,
    request_id: str | None = None,
) -> dict[str, str]:
    headers = {
        "HTTP_AUTHORIZATION": f"Bearer {token}",
        "HTTP_X_IDEMPOTENCY_KEY": idem_key,
    }
    if request_id:
        headers["HTTP_X_REQUEST_ID"] = request_id
    return headers


def _post_client(
    *,
    payload: dict[str, object],
    headers: dict[str, str],
) -> tuple[int, str, dict[str, object] | None]:
    web = Client()
    response = web.post(
        _CLIENTS_ROUTE,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_HOST="localhost",
        **headers,
    )
    body: dict[str, object] | None = None
    if "application/json" in str(response.headers.get("Content-Type", "") or "").lower():
        try:
            parsed = response.json()
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            body = parsed
    return (
        int(response.status_code),
        str(response.headers.get("Idempotency-Status", "")).strip().lower(),
        body,
    )


def _seed_idempotency_record(
    conn,
    *,
    agency_id: int,
    idem_key: str,
    payload: dict[str, object],
    state: str,
    lease_until: datetime | None,
    attempt: int = 1,
) -> None:
    now = datetime.now(timezone.utc)
    conn.execute(
        """
        INSERT INTO api_idempotency_records (
            agency_id,
            normalized_route,
            method,
            idempotency_key,
            canonical_body_hash,
            normalized_query_hash,
            semantic_headers_hash,
            state,
            attempt,
            lease_owner,
            lease_until,
            expires_at,
            updated_at
        ) VALUES (%s, %s, 'POST', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            agency_id,
            _normalized_clients_route(),
            idem_key,
            idempotency_engine.canonical_body_hash(payload),
            idempotency_engine.canonical_query_hash({}),
            _legacy_semantic_headers_hash(),
            state,
            int(attempt),
            "seed-owner",
            lease_until,
            now + timedelta(hours=1),
            now,
        ),
    )


def _block_first_client_create(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[threading.Event, threading.Event]:
    entered = threading.Event()
    release = threading.Event()
    call_lock = threading.Lock()
    call_count = 0
    original_upsert = views_clients_list.clients.upsert_client

    def _slow_upsert(*args: object, **kwargs: object) -> int:
        nonlocal call_count
        with call_lock:
            call_count += 1
            current_call = call_count
        if current_call == 1:
            entered.set()
            assert release.wait(timeout=10)
        return int(original_upsert(*args, **kwargs))

    monkeypatch.setattr(views_clients_list.clients, "upsert_client", _slow_upsert)
    return entered, release


def _count_clients_for_ids(conn, *, agency_id: int, client_ids: list[int]) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM clients
        WHERE agency_id = %s
          AND id = ANY(%s)
        """,
        (agency_id, client_ids),
    ).fetchone()
    assert row is not None
    return int(row["n"])


def _idempotency_row_summary(conn, *, agency_id: int, idem_key: str) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT state, attempt, status_code, lease_until
        FROM api_idempotency_records
        WHERE agency_id = %s
          AND method = 'POST'
          AND normalized_route = %s
          AND idempotency_key = %s
        """,
        (agency_id, _normalized_clients_route(), idem_key),
    ).fetchone()
    assert isinstance(row, dict)
    return dict(row)


def test_concurrent_first_writer_same_key_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    username = f"idem_race_mgr_{suffix}"
    password = "StrongTestPass_123!"
    idem_key = f"idem-race-{suffix}"
    phone_digits = str(int(suffix, 16))[-6:].rjust(6, "0")
    payload = {"family_name": f"Idem Race {suffix}", "phone": f"21366{phone_digits}"}

    agency_id = 0
    user_id = 0
    created_client_ids: set[int] = set()
    responses: list[tuple[int, str]] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)
    counter_lock = threading.Lock()
    helper_calls = 0
    original_try_insert = idempotency_engine._try_insert_in_progress_record

    def _synchronized_try_insert(*args: object, **kwargs: object) -> bool:
        nonlocal helper_calls
        with counter_lock:
            helper_calls += 1
            current_call = helper_calls
        if current_call <= 2:
            barrier.wait(timeout=5)
        return original_try_insert(*args, **kwargs)

    monkeypatch.setattr(
        idempotency_engine,
        "_try_insert_in_progress_record",
        _synchronized_try_insert,
    )

    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"IDR{suffix}", f"Idem Race Agency {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=username,
            password=password,
        )
        conn.commit()

        token = token_for(username, password)
        headers = _auth_headers(token=token, idem_key=idem_key)

        def _submit() -> None:
            try:
                status_code, idem_status, body = _post_client(payload=payload, headers=headers)
                responses.append((status_code, idem_status))
                if status_code == 201 and isinstance(body, dict) and "id" in body:
                    created_client_ids.add(int(body["id"]))
            except BaseException as exc:  # pragma: no cover - surfaced via assertion
                errors.append(exc)

        first = threading.Thread(target=_submit)
        second = threading.Thread(target=_submit)
        first.start()
        second.start()
        first.join(timeout=15)
        second.join(timeout=15)

        assert not first.is_alive()
        assert not second.is_alive()
        assert not errors
        assert len(responses) == 2
        assert all(status_code < 500 for status_code, _ in responses)
        assert all(
            idem_status in {"created", "replayed", "in_progress"} for _, idem_status in responses
        )
        if not created_client_ids:
            replay_status, _, replay_body = _post_client(payload=payload, headers=headers)
            assert replay_status == 201
            assert isinstance(replay_body, dict) and "id" in replay_body
            created_client_ids.add(int(replay_body["id"]))
        assert len(created_client_ids) == 1

        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM clients
            WHERE agency_id = %s
              AND id = %s
            """,
            (agency_id, next(iter(created_client_ids))),
        ).fetchone()
        assert row is not None
        assert int(row["n"]) == 1

        idem_row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM api_idempotency_records
            WHERE agency_id = %s
              AND method = 'POST'
              AND idempotency_key = %s
            """,
            (agency_id, idem_key),
        ).fetchone()
        assert idem_row is not None
        assert int(idem_row["n"]) == 1
    finally:
        conn.rollback()
        conn.close()
        if agency_id:
            cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)


def test_concurrent_same_key_different_payload_conflicts_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    username = f"idem_conflict_mgr_{suffix}"
    password = "StrongTestPass_123!"
    idem_key = f"idem-conflict-{suffix}"
    payload_a = {
        "family_name": f"Conflict A {suffix}",
        "phone": _phone_from_suffix("21377", suffix),
    }
    payload_b = {
        "family_name": f"Conflict B {suffix}",
        "phone": _phone_from_suffix("21388", suffix),
    }

    agency_id = 0
    user_id = 0
    created_client_ids: set[int] = set()
    responses: list[tuple[int, str]] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)
    helper_lock = threading.Lock()
    helper_calls = 0
    original_try_insert = idempotency_engine._try_insert_in_progress_record

    def _synchronized_try_insert(*args: object, **kwargs: object) -> bool:
        nonlocal helper_calls
        with helper_lock:
            helper_calls += 1
            current_call = helper_calls
        if current_call <= 2:
            barrier.wait(timeout=5)
        return original_try_insert(*args, **kwargs)

    monkeypatch.setattr(
        idempotency_engine,
        "_try_insert_in_progress_record",
        _synchronized_try_insert,
    )

    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"IDC{suffix}", f"Idem Conflict Agency {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=username,
            password=password,
        )
        conn.commit()
        token = token_for(username, password)
        headers = _auth_headers(token=token, idem_key=idem_key)

        def _submit(payload: dict[str, object]) -> None:
            try:
                status_code, idem_status, body = _post_client(payload=payload, headers=headers)
                responses.append((status_code, idem_status))
                if status_code == 201 and isinstance(body, dict) and "id" in body:
                    created_client_ids.add(int(body["id"]))
            except BaseException as exc:  # pragma: no cover - surfaced via assertion
                errors.append(exc)

        first = threading.Thread(target=_submit, args=(payload_a,))
        second = threading.Thread(target=_submit, args=(payload_b,))
        first.start()
        second.start()
        first.join(timeout=15)
        second.join(timeout=15)

        assert not first.is_alive()
        assert not second.is_alive()
        assert not errors
        assert len(responses) == 2
        assert sorted(status_code for status_code, _ in responses) == [201, 409]
        assert any(idem_status == "created" for _, idem_status in responses)
        assert len(created_client_ids) == 1
        assert (
            _count_clients_for_ids(
                conn,
                agency_id=agency_id,
                client_ids=list(created_client_ids),
            )
            == 1
        )
        idem_row = _idempotency_row_summary(conn, agency_id=agency_id, idem_key=idem_key)
        assert str(idem_row["state"]) == "completed"
    finally:
        conn.rollback()
        conn.close()
        if agency_id:
            cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)


def test_stale_lease_takeover_under_contention_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    username = f"idem_stale_mgr_{suffix}"
    password = "StrongTestPass_123!"
    idem_key = f"idem-stale-{suffix}"
    phone = _phone_from_suffix("21399", suffix)
    payload = {"family_name": f"Stale Lease {suffix}", "phone": phone}

    agency_id = 0
    user_id = 0
    created_client_ids: set[int] = set()
    responses: list[tuple[int, str]] = []
    errors: list[BaseException] = []
    entered, release = _block_first_client_create(monkeypatch)

    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"IDS{suffix}", f"Idem Stale Agency {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=username,
            password=password,
        )
        _seed_idempotency_record(
            conn,
            agency_id=agency_id,
            idem_key=idem_key,
            payload=payload,
            state="in_progress",
            lease_until=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
        conn.commit()

        token = token_for(username, password)

        def _submit(request_id: str) -> None:
            try:
                status_code, idem_status, body = _post_client(
                    payload=payload,
                    headers=_auth_headers(token=token, idem_key=idem_key, request_id=request_id),
                )
                responses.append((status_code, idem_status))
                if status_code == 201 and isinstance(body, dict) and "id" in body:
                    created_client_ids.add(int(body["id"]))
            except BaseException as exc:  # pragma: no cover - surfaced via assertion
                errors.append(exc)

        first = threading.Thread(target=_submit, args=("takeover-winner",))
        second = threading.Thread(target=_submit, args=("takeover-contender",))
        first.start()
        assert entered.wait(timeout=10)
        second.start()
        time.sleep(0.25)
        release.set()
        first.join(timeout=15)
        second.join(timeout=15)

        assert not first.is_alive()
        assert not second.is_alive()
        assert not errors
        assert len(responses) == 2
        assert all(status_code < 500 for status_code, _ in responses)
        assert any(status_code == 201 for status_code, _ in responses)
        assert all(
            idem_status in {"created", "replayed", "in_progress"} for _, idem_status in responses
        )
        assert len(created_client_ids) == 1
        assert (
            _count_clients_for_ids(
                conn,
                agency_id=agency_id,
                client_ids=list(created_client_ids),
            )
            == 1
        )
        idem_row = _idempotency_row_summary(conn, agency_id=agency_id, idem_key=idem_key)
        assert str(idem_row["state"]) == "completed"
        assert int(idem_row["attempt"]) == 2
        assert idem_row["lease_until"] is None
    finally:
        conn.rollback()
        conn.close()
        if agency_id:
            cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)


def test_failed_transient_recovery_is_safe_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    username = f"idem_recover_mgr_{suffix}"
    password = "StrongTestPass_123!"
    idem_key = f"idem-recover-{suffix}"
    phone = _phone_from_suffix("21372", suffix)
    payload = {"family_name": f"Recover {suffix}", "phone": phone}

    agency_id = 0
    user_id = 0
    created_client_ids: set[int] = set()
    responses: list[tuple[int, str]] = []
    errors: list[BaseException] = []
    entered, release = _block_first_client_create(monkeypatch)

    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"IDF{suffix}", f"Idem Recover Agency {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=username,
            password=password,
        )
        _seed_idempotency_record(
            conn,
            agency_id=agency_id,
            idem_key=idem_key,
            payload=payload,
            state="failed_transient",
            lease_until=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
        conn.commit()

        token = token_for(username, password)

        def _submit(request_id: str) -> None:
            try:
                status_code, idem_status, body = _post_client(
                    payload=payload,
                    headers=_auth_headers(token=token, idem_key=idem_key, request_id=request_id),
                )
                responses.append((status_code, idem_status))
                if status_code == 201 and isinstance(body, dict) and "id" in body:
                    created_client_ids.add(int(body["id"]))
            except BaseException as exc:  # pragma: no cover - surfaced via assertion
                errors.append(exc)

        first = threading.Thread(target=_submit, args=("recover-winner",))
        second = threading.Thread(target=_submit, args=("recover-contender",))
        first.start()
        assert entered.wait(timeout=10)
        second.start()
        time.sleep(0.25)
        release.set()
        first.join(timeout=15)
        second.join(timeout=15)

        assert not first.is_alive()
        assert not second.is_alive()
        assert not errors
        assert len(responses) == 2
        assert all(status_code < 500 for status_code, _ in responses)
        assert any(status_code == 201 for status_code, _ in responses)
        assert all(
            idem_status in {"created", "replayed", "in_progress"} for _, idem_status in responses
        )
        assert len(created_client_ids) == 1
        assert (
            _count_clients_for_ids(
                conn,
                agency_id=agency_id,
                client_ids=list(created_client_ids),
            )
            == 1
        )
        idem_row = _idempotency_row_summary(conn, agency_id=agency_id, idem_key=idem_key)
        assert str(idem_row["state"]) == "completed"
        assert int(idem_row["attempt"]) == 2
        assert idem_row["lease_until"] is None
    finally:
        conn.rollback()
        conn.close()
        if agency_id:
            cleanup_import_test_agency(agency_id=agency_id, user_id=user_id)
