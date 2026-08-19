from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import django
from django.contrib.auth.hashers import make_password
from django.test import Client
from dotenv import load_dotenv
from psycopg.rows import dict_row

from core.env_files import resolve_env_file

_ENV_LOADED = False
_DJANGO_READY = False


def ensure_django() -> None:
    global _DJANGO_READY
    if _DJANGO_READY:
        return
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    django.setup()
    _DJANGO_READY = True


def load_env_once() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    repo_root = Path(__file__).resolve().parents[3]
    base_dir = repo_root / "server"
    env_path = resolve_env_file(repo_root, base_dir)
    if env_path.exists():
        load_dotenv(env_path)
    _ENV_LOADED = True


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required for integration tests")
    return value


def admin_conn() -> Any:
    import psycopg

    load_env_once()
    return psycopg.connect(
        (
            f"host={os.environ.get('POSTGRES_HOST', 'localhost')} "
            f"port={os.environ.get('POSTGRES_PORT', '5432')} "
            f"dbname={require_env('POSTGRES_DB')} "
            f"user={require_env('POSTGRES_ADMIN_USER')} "
            f"password={require_env('POSTGRES_ADMIN_PASSWORD')}"
        ),
        row_factory=dict_row,
    )


def _resync_serial(conn: Any, table: str, column: str = "id") -> None:
    if table == "accounts_agency":
        max_expr = "(SELECT COALESCE(MAX(id), 1) FROM accounts_agency)"
        sequence_name = "accounts_agency_id_seq"
    elif table == "accounts_user":
        max_expr = "(SELECT COALESCE(MAX(id), 1) FROM accounts_user)"
        sequence_name = "accounts_user_id_seq"
    else:
        raise ValueError(f"unsupported sequence table: {table}")
    conn.execute(
        f"""
        SELECT setval(
            %s::regclass,
            GREATEST(
                {max_expr},
                (SELECT last_value FROM {sequence_name})
            ),
            true
        )
        """,
        (sequence_name,),
    )


def _execute_insert_with_sequence_retry(
    conn: Any, table: str, query: str, params: tuple[object, ...]
) -> int:
    import psycopg

    savepoint_name = f"sp_{table}_{uuid.uuid4().hex[:8]}"
    conn.execute(f"SAVEPOINT {savepoint_name}")
    try:
        row = conn.execute(query, params).fetchone()
    except psycopg.errors.UniqueViolation:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
        _resync_serial(conn, table)
        row = conn.execute(query, params).fetchone()
    finally:
        conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
    assert row is not None
    return int(row["id"])


def create_agency(conn: Any, code: str, label: str) -> int:
    _resync_serial(conn, "accounts_agency")
    return _execute_insert_with_sequence_retry(
        conn,
        "accounts_agency",
        """
        INSERT INTO accounts_agency (
            legal_name, display_name, agency_code,
            kbis_number, phone_number, phone_number_enc, email,
            address_line1, address_line1_enc, address_line2, address_line2_enc, city, city_enc, postal_code, country,
            is_active, max_users, max_managers, max_agents_per_manager,
            created_at, updated_at
        )
        VALUES (
            %s, %s, %s,
            '', '', '', '',
            '', '', '', '', '', '', '', '',
            true, 3, 1, 2,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        RETURNING id
        """,
        (label, label, code),
    )


def create_manager_user(conn: Any, *, agency_id: int, username: str, password: str) -> int:
    _resync_serial(conn, "accounts_user")
    return _execute_insert_with_sequence_retry(
        conn,
        "accounts_user",
        """
        INSERT INTO accounts_user (
            password, last_login, is_superuser, username,
            first_name, first_name_enc, first_name_search_src,
            last_name, last_name_enc, last_name_search_src,
            email,
            is_staff, is_active, date_joined,
            role, agency_id, manager_id, access_scope, is_owner, can_hard_delete,
            can_import, import_granted_by_id, timezone, locale,
            mfa_totp_secret, mfa_totp_secret_enc
        )
        VALUES (
            %s, NULL, false, %s, '', '', '', '', '', '', '',
            false, true, CURRENT_TIMESTAMP,
            'manager', %s, NULL, 'agency', false, false,
            false, NULL, '', '',
            '', ''
        )
        RETURNING id
        """,
        (make_password(password), username, agency_id),
    )


def detected_import_columns(headers: list[str]) -> list[dict[str, object]]:
    return [
        {
            "index": index,
            "header": header,
            "detected_type": "unknown",
            "confidence": 1.0,
            "sample_values": [],
        }
        for index, header in enumerate(headers)
    ]


def make_import_test_user_and_agency(prefix: str) -> tuple[int, int, object]:
    from django.contrib.auth import get_user_model

    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"{prefix}{uuid.uuid4().hex[:6]}", f"{prefix} Agency")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"{prefix.lower()}_{uuid.uuid4().hex[:8]}",
            password="StrongTestPass_123!",
        )
        conn.commit()
    finally:
        conn.close()
    user = get_user_model().objects.get(id=user_id)
    return agency_id, user_id, user


def cleanup_import_test_agency(*, agency_id: int, user_id: int | None = None) -> None:
    cleanup = admin_conn()
    resolved_user_id = int(user_id or 0)
    try:
        cleanup.execute("SET session_replication_role = replica")
        cleanup.execute("DELETE FROM match_pairs WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM match_candidates WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM task_failures WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM agency_settings WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM surface_cache_generation WHERE agency_id = %s", (agency_id,))
        cleanup.execute(
            """
            DELETE FROM notification_reads
            WHERE notification_id IN (
                SELECT id
                FROM notifications
                WHERE agency_id = %s
            )
               OR user_id = %s
            """,
            (agency_id, resolved_user_id),
        )
        cleanup.execute("DELETE FROM notifications WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM accounts_userinvite WHERE agency_id = %s", (agency_id,))
        cleanup.execute(
            """
            DELETE FROM imports_importreviewitem
            WHERE job_id IN (
                SELECT id
                FROM imports_importjob
                WHERE agency_id = %s
            )
            """,
            (agency_id,),
        )
        cleanup.execute(
            """
            DELETE FROM imports_importreviewgroup
            WHERE job_id IN (
                SELECT id
                FROM imports_importjob
                WHERE agency_id = %s
            )
            """,
            (agency_id,),
        )
        cleanup.execute(
            """
            DELETE FROM imports_importworkflowstate
            WHERE job_id IN (
                SELECT id
                FROM imports_importjob
                WHERE agency_id = %s
            )
            """,
            (agency_id,),
        )
        cleanup.execute(
            """
            DELETE FROM imports_importchunkphase
            WHERE chunk_id IN (
                SELECT id
                FROM imports_importchunk
                WHERE agency_id = %s
            )
            """,
            (agency_id,),
        )
        cleanup.execute(
            "DELETE FROM imports_importartifactmanifest WHERE agency_id = %s",
            (agency_id,),
        )
        cleanup.execute("DELETE FROM imports_importrowaudit WHERE agency_id = %s", (agency_id,))
        cleanup.execute(
            "DELETE FROM imports_importdeadletterrow WHERE agency_id = %s", (agency_id,)
        )
        cleanup.execute(
            "DELETE FROM imports_importagencyprofile WHERE agency_id = %s", (agency_id,)
        )
        cleanup.execute("DELETE FROM imports_importchunk WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM imports_importjob WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM demande_locations WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM offer_locations WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM match_counts_cache WHERE agency_id = %s", (agency_id,))
        cleanup.execute(
            "DELETE FROM offer_photos WHERE offer_id IN (SELECT id FROM offers WHERE agency_id = %s)",
            (agency_id,),
        )
        cleanup.execute("DELETE FROM visits WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM contracts WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM demandes WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM offers WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM listings WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM custom_locations WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM match_rebuild_state WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_id,))
        cleanup.execute(
            """
            DELETE FROM auth_security_events
            WHERE agency_id = %s
               OR user_id = %s
               OR user_id IN (
                   SELECT id
                   FROM accounts_user
                   WHERE agency_id = %s
               )
            """,
            (agency_id, resolved_user_id, agency_id),
        )
        cleanup.execute(
            """
            DELETE FROM storage_events
            WHERE agency_id = %s
               OR user_id = %s
               OR storage_id IN (
                   SELECT id
                   FROM storage_objects
                   WHERE agency_id = %s OR user_id = %s
               )
            """,
            (agency_id, resolved_user_id, agency_id, resolved_user_id),
        )
        cleanup.execute("DELETE FROM storage_usage WHERE agency_id = %s", (agency_id,))
        cleanup.execute(
            "DELETE FROM storage_objects WHERE agency_id = %s OR user_id = %s",
            (agency_id, resolved_user_id),
        )
        cleanup.execute("DELETE FROM api_idempotency_records WHERE agency_id = %s", (agency_id,))
        cleanup.execute(
            """
            DELETE FROM token_blacklist_blacklistedtoken
            WHERE token_id IN (
                SELECT id
                FROM token_blacklist_outstandingtoken
                WHERE user_id = %s
                   OR user_id IN (
                       SELECT id
                       FROM accounts_user
                       WHERE agency_id = %s
                   )
            )
            """,
            (resolved_user_id, agency_id),
        )
        cleanup.execute(
            """
            DELETE FROM token_blacklist_outstandingtoken
            WHERE user_id = %s
               OR user_id IN (
                   SELECT id
                   FROM accounts_user
                   WHERE agency_id = %s
               )
            """,
            (resolved_user_id, agency_id),
        )
        cleanup.execute(
            """
            DELETE FROM accounts_usersession
            WHERE user_id = %s
               OR user_id IN (
                   SELECT id
                   FROM accounts_user
                   WHERE agency_id = %s
               )
            """,
            (resolved_user_id, agency_id),
        )
        cleanup.execute(
            "DELETE FROM accounts_user WHERE agency_id = %s OR id = %s",
            (agency_id, resolved_user_id),
        )
        cleanup.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        cleanup.execute("SET session_replication_role = origin")
        cleanup.commit()
    except Exception:
        cleanup.rollback()
        try:
            cleanup.execute("SET session_replication_role = origin")
            cleanup.commit()
        except Exception:
            cleanup.rollback()
        raise
    finally:
        cleanup.close()


def create_import_pending_review_item(
    *,
    job: Any,
    row_ordinal: int = 1,
    entity_type: str = "client",
    topology_side: str = "client_side",
    suggested_action: str = "review_ambiguous",
    suggested_existing_id: int = 0,
    suggested_confidence: float = 0.0,
    raw_data: dict[str, object] | None = None,
    normalized_data: dict[str, object] | None = None,
    candidate_matches: list[dict[str, object]] | None = None,
) -> tuple[Any, Any]:
    from server.imports.models import ImportReviewGroup, ImportReviewItem

    group = ImportReviewGroup.objects.create(
        job=job,
        group_key=f"{entity_type}:{row_ordinal}:pending",
        group_kind=ImportReviewGroup.Kind.SINGLE_ROW,
        status=ImportReviewGroup.Status.PENDING,
        issue_group="possible_duplicate",
        issue_title="Review required",
        issue_summary="This row still needs review.",
        entity_type=entity_type,
        topology_side=topology_side,
        root_identity={"row": row_ordinal},
        root_label=f"{entity_type}:{row_ordinal}",
        root_row_ordinal=row_ordinal,
        item_count=1,
        pending_item_count=1,
        blocking_item_count=0,
        suggested_group_action=suggested_action,
        search_text=f"{entity_type} {row_ordinal}",
    )
    item = ImportReviewItem.objects.create(
        job=job,
        group=group,
        row_ordinal=row_ordinal,
        entity_type=entity_type,
        topology_side=topology_side,
        issue_group="possible_duplicate",
        issue_title="Review required",
        issue_summary="This row still needs review.",
        raw_data=raw_data or {"family_name": "Review User", "phone": "0555001001"},
        normalized_data=normalized_data or {"family_name": "Review User", "phone": "0555001001"},
        candidate_matches=candidate_matches or [],
        suggested_action=suggested_action,
        suggested_existing_id=suggested_existing_id,
        suggested_confidence=suggested_confidence,
        search_text=f"{entity_type} {row_ordinal}",
    )
    return group, item


def token_for(username: str, password: str) -> str:
    client = Client()
    response = client.post(
        "/api/auth/token/",
        data=json.dumps({"username": username, "password": password}),
        content_type="application/json",
        HTTP_HOST="localhost",
    )
    assert response.status_code == 200, response.content.decode("utf-8", errors="ignore")
    payload = response.json()
    token = payload.get("access")
    assert isinstance(token, str) and token
    return token
