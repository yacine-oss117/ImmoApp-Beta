from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _stderr(message: str) -> None:
    print(message, file=sys.stderr)


def _load_local_seed_defaults() -> None:
    appdata_root = Path(os.environ.get("IMMOAPP_APPDATA_ROOT", "C:/ProgramData/ImmoApp"))
    seed_path = appdata_root / "secrets" / "immoapp-dev-secrets.json"
    if not seed_path.exists():
        return
    try:
        payload = json.loads(seed_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    for key, value in payload.items():
        if isinstance(key, str) and isinstance(value, str):
            os.environ.setdefault(key, value)


def _force_host_runtime_endpoints() -> None:
    os.environ.setdefault("POSTGRES_HOST", "127.0.0.1")
    os.environ.setdefault("POSTGRES_PORT", "5432")
    os.environ.setdefault("PGCONNECT_TIMEOUT", "5")

    bao_addr = (os.environ.get("BAO_ADDR") or "").strip()
    if not bao_addr or "://openbao" in bao_addr:
        os.environ["BAO_ADDR"] = "http://127.0.0.1:8200"

    valkey_url = (os.environ.get("VALKEY_URL") or "").strip()
    if not valkey_url or "://valkey" in valkey_url:
        os.environ["VALKEY_URL"] = "redis://127.0.0.1:6379/1"

    channel_url = (os.environ.get("CHANNEL_LAYER_URL") or "").strip()
    if not channel_url or "://valkey" in channel_url:
        os.environ["CHANNEL_LAYER_URL"] = "redis://127.0.0.1:6379/3"

    storage_endpoint = (os.environ.get("STORAGE_ENDPOINT_URL") or "").strip()
    if not storage_endpoint or "://minio" in storage_endpoint:
        os.environ["STORAGE_ENDPOINT_URL"] = "http://127.0.0.1:9000"

    storage_clamd_host = (os.environ.get("STORAGE_CLAMD_HOST") or "").strip()
    if not storage_clamd_host or storage_clamd_host == "clamav":
        os.environ["STORAGE_CLAMD_HOST"] = "127.0.0.1"

    broker_url = (os.environ.get("CELERY_BROKER_URL") or "").strip()
    if "@rabbitmq" in broker_url:
        os.environ["CELERY_BROKER_URL"] = broker_url.replace("@rabbitmq", "@127.0.0.1")


def _force_admin_db_credentials() -> None:
    _load_local_seed_defaults()
    _force_host_runtime_endpoints()
    os.environ.setdefault("IMMOAPP_SECRETS_BACKEND", "env")
    os.environ.setdefault("IMMOAPP_ALLOW_ENV_SECRETS", "1")
    os.environ.setdefault("IMMOAPP_SECRETS_REQUIRED", "0")
    os.environ.setdefault("IMMOAPP_SECRETS_OVERWRITE", "0")
    os.environ.setdefault("IMMOAPP_SKIP_CELERY_APP", "1")
    os.environ.setdefault(
        "DJANGO_SECRET_KEY",
        "local-dev-sanitize-secret-key-not-for-production",
    )
    admin_user = (os.environ.get("POSTGRES_ADMIN_USER") or "immoapp").strip()
    admin_password = (os.environ.get("POSTGRES_ADMIN_PASSWORD") or "immoapp_admin_password").strip()
    if admin_user:
        os.environ["POSTGRES_ADMIN_USER"] = admin_user
        os.environ["POSTGRES_USER"] = admin_user
    if admin_password:
        os.environ["POSTGRES_ADMIN_PASSWORD"] = admin_password
        os.environ["POSTGRES_PASSWORD"] = admin_password


def _configure_django() -> None:
    _force_admin_db_credentials()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def _guard_local(*, force_local: bool) -> None:
    from django.conf import settings

    environment = (
        (
            os.environ.get("IMMOAPP_ENVIRONMENT")
            or os.environ.get("DJANGO_ENV")
            or os.environ.get("ENVIRONMENT")
            or ""
        )
        .strip()
        .lower()
    )
    if not force_local:
        raise RuntimeError("Refusing to sanitize without --force-local.")
    if environment in {"prod", "production"}:
        raise RuntimeError("Refusing to sanitize a production environment.")
    if (
        not bool(getattr(settings, "DEBUG", False))
        and os.environ.get("IMMOAPP_ALLOW_DESTRUCTIVE_LOCAL_SANITIZE", "0").strip() != "1"
    ):
        raise RuntimeError(
            "Refusing to sanitize with DEBUG disabled unless "
            "IMMOAPP_ALLOW_DESTRUCTIVE_LOCAL_SANITIZE=1 is set."
        )


def _truncate_non_preserved_tables(*, preserve_tables: set[str]) -> int:
    from django.db import connection, transaction

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = current_schema()
            ORDER BY tablename
            """)
        table_names = [
            str(row[0]).strip()
            for row in cursor.fetchall()
            if isinstance(row[0], str) and str(row[0]).strip()
        ]
    truncatable = [name for name in table_names if name not in preserve_tables]
    if not truncatable:
        return 0
    quoted = ", ".join(f'"{name}"' for name in truncatable)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")
    return len(truncatable)


def _purge_storage_bucket() -> int:
    try:
        from server.services.storage_client import ClientError, get_storage_client
        from server.services.storage_config import get_storage_config
    except Exception:
        return 0
    try:
        client = get_storage_client()
        config = get_storage_config()
    except Exception:
        return 0

    deleted = 0
    continuation_token: str | None = None
    while True:
        kwargs: dict[str, object] = {"Bucket": config.bucket}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token
        try:
            response = client.list_objects_v2(**kwargs)
        except ClientError:
            return deleted
        contents = response.get("Contents", []) if isinstance(response, dict) else []
        objects = [
            {"Key": item["Key"]}
            for item in contents
            if isinstance(item, dict) and isinstance(item.get("Key"), str)
        ]
        if objects:
            client.delete_objects(
                Bucket=config.bucket,
                Delete={"Objects": objects, "Quiet": True},
            )
            deleted += len(objects)
        if not bool(response.get("IsTruncated")):
            break
        continuation_token = str(response.get("NextContinuationToken") or "").strip() or None
        if continuation_token is None:
            break
    return deleted


def _clear_caches() -> int:
    from django.conf import settings
    from django.core.cache import caches

    cleared = 0
    for alias in settings.CACHES.keys():
        try:
            caches[alias].clear()
            cleared += 1
        except Exception:
            continue
    return cleared


def _purge_broker_queues() -> int:
    broker_url = (os.environ.get("CELERY_BROKER_URL") or "").strip()
    if not broker_url:
        return 0
    try:
        from kombu import Connection, Queue
    except Exception:
        return 0
    purged = 0
    queue_names = [
        "celery",
        "imports",
        "maintenance",
        "match_pairs",
        "rebuild_batch",
    ]
    try:
        with Connection(broker_url, connect_timeout=3) as conn:
            channel = conn.channel()
            for queue_name in queue_names:
                try:
                    queue = Queue(queue_name)
                    purged += int(queue(channel).purge() or 0)
                except Exception:
                    continue
    except Exception:
        return purged
    return purged


def _preserved_tables() -> set[str]:
    return {
        "accounts_user",
        "accounts_agency",
        "alembic_version",
        "auth_group",
        "auth_group_permissions",
        "auth_permission",
        "django_content_type",
        "django_migrations",
    }


class AccountSanitizeSummary(TypedDict):
    deleted_users: int
    deleted_agencies: int
    remaining_admin_id: int
    preserved_usernames: list[str]
    preserved_agency_ids: list[int]


def _sanitize_accounts(
    *,
    admin_username: str,
    preserved_usernames: set[str] | None = None,
) -> AccountSanitizeSummary:
    from django.db.models import Q

    from server.accounts.models import Agency, User

    preserved_names = {str(admin_username).strip().lower()}
    for username in preserved_usernames or set():
        normalized = str(username).strip().lower()
        if normalized:
            preserved_names.add(normalized)
    admin_user = (
        User.objects.filter(username=str(admin_username), is_superuser=True).order_by("id").first()
    )
    if admin_user is None:
        raise RuntimeError(f"Admin superuser '{admin_username}' was not found.")

    query = Q(id=admin_user.id)
    for username in sorted(preserved_names):
        query |= Q(username__iexact=username)
    preserved_users = list(User.objects.filter(query).order_by("id"))
    preserved_name_set = {str(user.username).strip().lower() for user in preserved_users}
    missing_names = sorted(preserved_names - preserved_name_set)
    if missing_names:
        raise RuntimeError("Preserved username(s) were not found: " + ", ".join(missing_names))

    preserved_user_ids = {int(user.id) for user in preserved_users}
    preserved_agency_ids = {
        int(user.agency_id) for user in preserved_users if getattr(user, "agency_id", None)
    }

    invalid_agents = [
        str(user.username)
        for user in preserved_users
        if user.role == User.ROLE_AGENT
        and user.manager_id is not None
        and int(user.manager_id) not in preserved_user_ids
    ]
    if invalid_agents:
        raise RuntimeError(
            "Refusing to preserve agent user(s) without their manager: "
            + ", ".join(sorted(invalid_agents))
        )

    deleted_users, _ = User.objects.exclude(id__in=preserved_user_ids).delete()
    agencies_qs = Agency.objects.all()
    if preserved_agency_ids:
        agencies_qs = agencies_qs.exclude(id__in=preserved_agency_ids)
    deleted_agencies, _ = agencies_qs.delete()
    admin_user.agency = None
    admin_user.manager = None
    admin_user.role = User.ROLE_SUPER_ADMIN
    admin_user.access_scope = User.SCOPE_AGENCY
    admin_user.is_owner = False
    admin_user.can_hard_delete = True
    admin_user.can_import = True
    admin_user.import_granted_by = None
    admin_user.save(validate=False)
    return {
        "deleted_users": int(deleted_users),
        "deleted_agencies": int(deleted_agencies),
        "remaining_admin_id": int(admin_user.id),
        "preserved_usernames": sorted(str(user.username) for user in preserved_users),
        "preserved_agency_ids": sorted(preserved_agency_ids),
    }


def _restore_runtime_primitives() -> None:
    from server.pg.schema import ensure_schema

    ensure_schema()


def _print_summary(summary: Iterable[tuple[str, object]]) -> None:
    for key, value in summary:
        print(f"{key}: {value}")


def _summary_list(summary: object, key: str) -> list[object]:
    if not isinstance(summary, dict):
        return []
    value = summary.get(key, [])
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sanitize local/dev state and keep only preserved user accounts."
    )
    parser.add_argument("--force-local", action="store_true")
    parser.add_argument("--admin-username", default="admin")
    parser.add_argument(
        "--preserve-username",
        action="append",
        default=[],
        help="Additional username to preserve alongside the admin superuser.",
    )
    args = parser.parse_args()

    try:
        _configure_django()
        _guard_local(force_local=bool(args.force_local))
        truncated_tables = _truncate_non_preserved_tables(preserve_tables=_preserved_tables())
        preserved_usernames = {
            str(username).strip()
            for username in list(args.preserve_username)
            if str(username).strip()
        }
        if preserved_usernames:
            account_summary = _sanitize_accounts(
                admin_username=str(args.admin_username),
                preserved_usernames=preserved_usernames,
            )
        else:
            account_summary = _sanitize_accounts(admin_username=str(args.admin_username))
        _restore_runtime_primitives()
        deleted_objects = _purge_storage_bucket()
        cleared_caches = _clear_caches()
        purged_messages = _purge_broker_queues()
    except Exception as exc:
        _stderr(f"sanitize_local_dev_state failed: {exc}")
        return 1

    _print_summary(
        [
            ("truncated_tables", truncated_tables),
            ("deleted_users", account_summary["deleted_users"]),
            ("deleted_agencies", account_summary["deleted_agencies"]),
            ("remaining_admin_id", account_summary["remaining_admin_id"]),
            (
                "preserved_usernames",
                ",".join(
                    str(value)
                    for value in _summary_list(account_summary, "preserved_usernames")
                    if str(value).strip()
                ),
            ),
            (
                "preserved_agency_ids",
                ",".join(
                    str(v)
                    for v in _summary_list(account_summary, "preserved_agency_ids")
                    if str(v).strip()
                ),
            ),
            ("reference_primitives_restored", True),
            ("deleted_storage_objects", deleted_objects),
            ("cleared_cache_backends", cleared_caches),
            ("purged_broker_messages", purged_messages),
        ]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
