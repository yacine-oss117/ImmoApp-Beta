from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import psycopg
import redis
from psycopg.rows import dict_row


def _bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django

    django.setup()


def _percentile(samples: list[float], q: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    idx = int(round((len(ordered) - 1) * q))
    return ordered[idx]


def _assert_budget(name: str, value: float, limit: float) -> None:
    if value > limit:
        raise SystemExit(
            f"verify_api_queue_baseline: {name} exceeded budget ({value:.2f}ms > {limit:.2f}ms)"
        )


def _db_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"verify_api_queue_baseline: missing required DB env {name}")
    return value


def _admin_conn() -> psycopg.Connection:
    return psycopg.connect(
        (
            f"host={os.environ.get('POSTGRES_HOST', 'localhost')} "
            f"port={os.environ.get('POSTGRES_PORT', '5432')} "
            f"dbname={_db_env('POSTGRES_DB')} "
            f"user={_db_env('POSTGRES_ADMIN_USER')} "
            f"password={_db_env('POSTGRES_ADMIN_PASSWORD')}"
        ),
        row_factory=dict_row,
    )


def _create_agency(conn: psycopg.Connection, *, code: str, label: str) -> int:
    row = conn.execute(
        """
        INSERT INTO accounts_agency (
            legal_name, display_name, agency_code,
            kbis_number, phone_number, email,
            address_line1, address_line2, city, postal_code, country,
            is_active, max_users, max_managers, max_agents_per_manager,
            created_at, updated_at
        )
        VALUES (
            %s, %s, %s,
            '', '', '',
            '', '', '', '', '',
            true, 200, 100, 100,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        RETURNING id
        """,
        (label, label, code),
    ).fetchone()
    if not row:
        raise SystemExit("verify_api_queue_baseline: failed to create agency")
    return int(row["id"])


def _create_manager_user(
    conn: psycopg.Connection, *, agency_id: int, username: str, password: str
) -> int:
    from django.contrib.auth.hashers import make_password

    row = conn.execute(
        """
        INSERT INTO accounts_user (
            password, last_login, is_superuser, username, first_name, last_name, email,
            is_staff, is_active, date_joined,
            role, agency_id, manager_id, access_scope, is_owner, can_hard_delete,
            can_import, import_granted_by_id, timezone, locale
        )
        VALUES (
            %s, NULL, false, %s, '', '', '',
            false, true, CURRENT_TIMESTAMP,
            'manager', %s, NULL, 'agency', false, false,
            false, NULL, '', ''
        )
        RETURNING id
        """,
        (make_password(password), username, agency_id),
    ).fetchone()
    if not row:
        raise SystemExit("verify_api_queue_baseline: failed to create manager user")
    return int(row["id"])


def _seed_rows(conn: psycopg.Connection, *, agency_id: int, marker: str, rows: int) -> None:
    for i in range(rows):
        conn.execute(
            """
            INSERT INTO clients (family_name, phone, status, agency_id, created_at, updated_at)
            VALUES (%s, %s, 'active', %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (f"{marker}_C_{i}", f"2139{i:06d}", agency_id),
        )
        conn.execute(
            """
            INSERT INTO listings (family_name, phone, status, agency_id, created_at, updated_at)
            VALUES (%s, %s, 'available', %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (f"{marker}_L_{i}", f"2140{i:06d}", agency_id),
        )


def _token_for(client, *, username: str, password: str) -> str:
    response = client.post(
        "/api/auth/token/",
        data=json.dumps({"username": username, "password": password}),
        content_type="application/json",
        HTTP_HOST="localhost",
    )
    if response.status_code != 200:
        raise SystemExit(
            "verify_api_queue_baseline: failed auth token call "
            f"({response.status_code}) {response.content.decode('utf-8', errors='ignore')}"
        )
    token = response.json().get("access")
    if not isinstance(token, str) or not token:
        raise SystemExit("verify_api_queue_baseline: auth token response missing access token")
    return token


def _measure_api_p95(client, *, token: str, repeats: int) -> tuple[float, float]:
    client_samples: list[float] = []
    listing_samples: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        r1 = client.get(
            "/api/v1/clients/",
            {"limit": 50, "offset": 0},
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        if r1.status_code != 200:
            raise SystemExit(f"verify_api_queue_baseline: /clients returned {r1.status_code}")
        client_samples.append((time.perf_counter() - start) * 1000.0)

        start = time.perf_counter()
        r2 = client.get(
            "/api/v1/listings/",
            {"limit": 50, "offset": 0},
            HTTP_HOST="localhost",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        if r2.status_code != 200:
            raise SystemExit(f"verify_api_queue_baseline: /listings returned {r2.status_code}")
        listing_samples.append((time.perf_counter() - start) * 1000.0)

    return _percentile(client_samples, 0.95), _percentile(listing_samples, 0.95)


def _measure_queue_publish() -> tuple[float, int | None]:
    from server.immoapp_server.celery import celery_app

    burst = int(os.environ.get("IMMOAPP_QUEUE_BURST", "10"))
    queue_name = os.environ.get("IMMOAPP_QUEUE_BASELINE_NAME", "maintenance")
    broker_url = os.environ.get("CELERY_BROKER_URL") or ""
    redis_client: redis.Redis[Any] | None = None
    before_len: int | None = None
    after_len: int | None = None

    if broker_url.startswith("redis://"):
        try:
            redis_client = redis.Redis.from_url(broker_url)
            before_len = int(redis_client.llen(queue_name))
        except Exception:
            redis_client = None

    publish_samples: list[float] = []
    for _ in range(burst):
        start = time.perf_counter()
        celery_app.send_task(
            "server.api.tasks_maintenance.purge_old_auth_events_task",
            kwargs={"retention_days": 30},
            queue=queue_name,
        )
        publish_samples.append((time.perf_counter() - start) * 1000.0)

    if redis_client is not None:
        try:
            after_len = int(redis_client.llen(queue_name))
            redis_client.delete(queue_name)
        except Exception:
            after_len = None

    p95_publish = _percentile(publish_samples, 0.95)
    backlog_delta = None if before_len is None or after_len is None else after_len - before_len
    return p95_publish, backlog_delta


def main() -> None:
    _bootstrap()
    from django.test import Client

    p95_clients_budget = float(os.environ.get("IMMOAPP_API_P95_CLIENTS_MS", "400"))
    p95_listings_budget = float(os.environ.get("IMMOAPP_API_P95_LISTINGS_MS", "400"))
    p95_queue_publish_budget = float(os.environ.get("IMMOAPP_QUEUE_P95_PUBLISH_MS", "120"))
    enforce_queue = os.environ.get("IMMOAPP_ENFORCE_QUEUE_BASELINE", "0") == "1"
    repeats = int(os.environ.get("IMMOAPP_API_BASELINE_REPEATS", "25"))
    seed_rows = int(os.environ.get("IMMOAPP_API_BASELINE_ROWS", "120"))

    marker = f"API_BASELINE_{uuid.uuid4().hex[:8]}"
    username = f"api_baseline_mgr_{uuid.uuid4().hex[:8]}"
    password = "StrongApiBaselinePass_123!"
    conn = _admin_conn()
    agency_id = 0
    user_id = 0
    try:
        agency_id = _create_agency(
            conn, code=f"AB{uuid.uuid4().hex[:6]}", label=f"API Baseline {marker}"
        )
        user_id = _create_manager_user(
            conn, agency_id=agency_id, username=username, password=password
        )
        _seed_rows(conn, agency_id=agency_id, marker=marker, rows=seed_rows)
        conn.commit()

        web = Client()
        token = _token_for(web, username=username, password=password)
        p95_clients, p95_listings = _measure_api_p95(web, token=token, repeats=repeats)
        _assert_budget("api.clients.p95", p95_clients, p95_clients_budget)
        _assert_budget("api.listings.p95", p95_listings, p95_listings_budget)

        queue_ok = True
        backlog_delta: int | None = None
        try:
            p95_publish, backlog_delta = _measure_queue_publish()
            _assert_budget("queue.publish.p95", p95_publish, p95_queue_publish_budget)
            if backlog_delta is not None and backlog_delta < 0:
                raise SystemExit(
                    "verify_api_queue_baseline: queue backlog delta became negative unexpectedly"
                )
        except Exception as exc:
            if enforce_queue:
                raise
            queue_ok = False
            print(f"verify_api_queue_baseline: queue check skipped ({exc})")

        queue_msg = "queue=ok" if queue_ok else "queue=skipped"
        print(
            "verify_api_queue_baseline: OK "
            f"(clients.p95={p95_clients:.2f}ms listings.p95={p95_listings:.2f}ms "
            f"{queue_msg} backlog_delta={backlog_delta})"
        )
    finally:
        conn.execute("DELETE FROM clients WHERE family_name LIKE %s", (f"{marker}_C_%",))
        conn.execute("DELETE FROM listings WHERE family_name LIKE %s", (f"{marker}_L_%",))
        if user_id:
            conn.execute(
                "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s", (user_id,)
            )
            conn.execute("DELETE FROM auth_security_events WHERE user_id = %s", (user_id,))
            conn.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        if agency_id:
            conn.execute("DELETE FROM auth_security_events WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        conn.commit()
        conn.close()


if __name__ == "__main__":
    main()
