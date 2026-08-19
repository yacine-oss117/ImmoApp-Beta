"""Small Redis-backed control surface for native desktop E2E flows."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

import redis

_E2E_MODE_ENV = "IMMOAPP_E2E_TEST_MODE"
_VALKEY_URL_ENV = "VALKEY_URL"
_DEFAULT_VALKEY_URL = "redis://127.0.0.1:6379/1"
_KEY_PREFIX = "immoapp:e2e"
_CONTROL_TTL_SECONDS = 600
_VISIBLE_ROW_INTERNAL_SUFFIXES = ("_search_idx",)
E2E_BUILD_IDENTITY_FILE = ".immoapp-build-identity.json"
REQUIRED_E2E_ROUTE_TEMPLATES = (
    "e2e/runtime/identity/",
    "e2e/entities/inspect/",
    "e2e/notifications/publish/",
    "e2e/imports/pause-next/",
    "e2e/faults/inject/",
    "e2e/auth/revoke-session/",
    "e2e/auth/revoke-other-sessions/",
)
E2E_PRODUCT_IDENTITY_ROOTS = (
    "server",
    "core",
    "requirements/server.txt",
    "deployment/docker",
)
_PRODUCT_IDENTITY_IGNORED_DIR_NAMES = frozenset(
    {
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tmp",
    }
)
_PRODUCT_IDENTITY_IGNORED_FILE_NAMES = frozenset({E2E_BUILD_IDENTITY_FILE})
_PRODUCT_IDENTITY_IGNORED_SUFFIXES = (".pyc", ".pyo", ".pyd", ".log")


@dataclass(frozen=True)
class E2ERouteFault:
    status_code: int
    detail: str
    code: str

    def payload(self) -> dict[str, object]:
        return {
            "detail": self.detail,
            "code": self.code,
        }


def e2e_test_mode_enabled() -> bool:
    raw = str(os.environ.get(_E2E_MODE_ENV, "") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _e2e_control_active() -> bool:
    return e2e_test_mode_enabled()


def _raise_e2e_control_disabled(operation: str) -> NoReturn:
    raise RuntimeError(f"Desktop E2E control operation '{operation}' requires {_E2E_MODE_ENV}=1.")


def normalize_route_template(value: str) -> str:
    normalized = str(value or "").strip().lstrip("/")
    if normalized.startswith("api/v1/"):
        normalized = normalized[7:]
    return normalized


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_identity_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().lstrip("/")


def _identity_path_is_ignored(relative_path: str) -> bool:
    relative = _normalize_identity_path(relative_path)
    if not relative:
        return True
    parts = tuple(part for part in relative.split("/") if part)
    if not parts:
        return True
    if any(part in _PRODUCT_IDENTITY_IGNORED_DIR_NAMES for part in parts[:-1]):
        return True
    filename = parts[-1]
    if filename in _PRODUCT_IDENTITY_IGNORED_FILE_NAMES:
        return True
    return any(filename.endswith(suffix) for suffix in _PRODUCT_IDENTITY_IGNORED_SUFFIXES)


def file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def iter_product_identity_files(
    root: Path,
    roots: Iterable[str] = E2E_PRODUCT_IDENTITY_ROOTS,
) -> tuple[str, ...]:
    normalized_root = root.resolve()
    files: set[str] = set()
    for raw_relative_root in roots:
        relative_root = _normalize_identity_path(raw_relative_root)
        if not relative_root or _identity_path_is_ignored(relative_root):
            continue
        candidate = normalized_root / Path(*relative_root.split("/"))
        if candidate.is_file():
            files.add(relative_root)
            continue
        if not candidate.is_dir():
            files.add(relative_root)
            continue
        for child in candidate.rglob("*"):
            if not child.is_file():
                continue
            relative = child.relative_to(normalized_root).as_posix()
            if _identity_path_is_ignored(relative):
                continue
            files.add(relative)
    return tuple(sorted(files))


def build_file_fingerprints(
    root: Path,
    relative_files: Iterable[str] | None = None,
) -> dict[str, str | None]:
    normalized_root = root.resolve()
    fingerprints: dict[str, str | None] = {}
    source_files = (
        iter_product_identity_files(normalized_root)
        if relative_files is None
        else tuple(sorted(relative_files))
    )
    for raw_relative in source_files:
        relative = _normalize_identity_path(raw_relative)
        fingerprints[relative] = file_sha256(normalized_root / Path(*relative.split("/")))
    return fingerprints


def build_source_fingerprint(
    root: Path,
    relative_files: Iterable[str] | None = None,
) -> str:
    normalized_root = root.resolve()
    digest = hashlib.sha256()
    source_files = (
        iter_product_identity_files(normalized_root)
        if relative_files is None
        else tuple(sorted(relative_files))
    )
    for raw_relative in source_files:
        relative = _normalize_identity_path(raw_relative)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        path = normalized_root / Path(*relative.split("/"))
        try:
            digest.update(path.read_bytes())
        except FileNotFoundError:
            digest.update(b"__IMMOAPP_MISSING_IDENTITY_FILE__")
        digest.update(b"\0")
    return digest.hexdigest()


def build_product_identity(root: Path) -> dict[str, object]:
    normalized_root = root.resolve()
    relative_files = iter_product_identity_files(normalized_root)
    fingerprints = build_file_fingerprints(normalized_root, relative_files)
    aggregate_sha256 = build_source_fingerprint(normalized_root, relative_files)
    return {
        "identity_kind": "e2e_product_source",
        "product_identity_roots": list(E2E_PRODUCT_IDENTITY_ROOTS),
        "code_identity": build_code_identity(normalized_root, relative_files=relative_files),
        "server_files_fingerprint": {
            "aggregate_sha256": aggregate_sha256,
            "file_count": len(fingerprints),
            "files": fingerprints,
        },
    }


def read_build_identity(root: Path) -> dict[str, object] | None:
    path = root.resolve() / E2E_BUILD_IDENTITY_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def write_build_identity(root: Path, output_path: Path | None = None) -> Path:
    normalized_root = root.resolve()
    target = output_path or (normalized_root / E2E_BUILD_IDENTITY_FILE)
    payload = build_product_identity(normalized_root)
    target.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def _public_files_fingerprint(value: object) -> dict[str, object]:
    fingerprint = value if isinstance(value, dict) else {}
    file_count = fingerprint.get("file_count")
    return {
        "aggregate_sha256": str(fingerprint.get("aggregate_sha256") or ""),
        "file_count": int(file_count) if isinstance(file_count, int) else 0,
    }


def _public_product_identity(value: object) -> dict[str, object] | None:
    identity = value if isinstance(value, dict) else None
    if identity is None:
        return None
    code_identity = identity.get("code_identity")
    return {
        "identity_kind": str(identity.get("identity_kind") or ""),
        "product_identity_roots": list(E2E_PRODUCT_IDENTITY_ROOTS),
        "code_identity": code_identity if isinstance(code_identity, dict) else {},
        "server_files_fingerprint": _public_files_fingerprint(
            identity.get("server_files_fingerprint")
        ),
    }


def _run_git(root: Path, *args: str) -> str | None:
    if not (root / ".git").exists():
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def build_code_identity(
    root: Path,
    *,
    relative_files: Iterable[str] | None = None,
) -> dict[str, object]:
    normalized_root = root.resolve()
    git_sha = _run_git(normalized_root, "rev-parse", "HEAD")
    dirty_output = _run_git(normalized_root, "status", "--short")
    source_fingerprint = build_source_fingerprint(normalized_root, relative_files)
    return {
        "git_sha": git_sha,
        "dirty": bool(dirty_output) if dirty_output is not None else None,
        "source_fingerprint": source_fingerprint,
        "identity_kind": "git_and_fingerprint" if git_sha else "fingerprint",
        "fingerprint_scope": "e2e_product_source",
    }


def _process_start_time() -> float | None:
    try:
        import psutil

        return float(psutil.Process(os.getpid()).create_time())
    except Exception:
        return None


def _runtime_source_mode(root: Path) -> str:
    if (root / ".git").exists():
        return "bind_mount"
    if str(root).replace("\\", "/").rstrip("/") == "/app":
        return "image"
    if Path("/.dockerenv").exists():
        return "image"
    return "unknown"


def _safe_root_hint(root: Path) -> str:
    normalized = str(root).replace("\\", "/").rstrip("/")
    if normalized == "/app" or normalized.startswith("/app/"):
        return normalized
    return root.name


def required_route_presence() -> dict[str, bool]:
    from server.api.route_registry import iter_registered_routes

    registered = {spec.path for spec in iter_registered_routes()}
    return {route: route in registered for route in REQUIRED_E2E_ROUTE_TEMPLATES}


def runtime_identity() -> dict[str, object]:
    root = repo_root()
    product_identity = build_product_identity(root)
    return {
        "ok": True,
        "e2e_test_mode": e2e_test_mode_enabled(),
        "backend_pid": os.getpid(),
        "process_start_time": _process_start_time(),
        "runtime_source_mode": _runtime_source_mode(root),
        "app_root": _safe_root_hint(root),
        "code_identity": product_identity["code_identity"],
        "server_files_fingerprint": _public_files_fingerprint(
            product_identity["server_files_fingerprint"]
        ),
        "build_identity": _public_product_identity(read_build_identity(root)),
        "route_presence": required_route_presence(),
    }


def _redis_client() -> redis.Redis:
    url = str(os.environ.get(_VALKEY_URL_ENV, _DEFAULT_VALKEY_URL) or _DEFAULT_VALKEY_URL)
    return cast(redis.Redis, redis.from_url(url, decode_responses=True))


def _coerce_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    try:
        return int(str(value))
    except ValueError:
        return 0


def _control_key(*parts: object) -> str:
    rendered = [str(part).strip() for part in parts if str(part).strip()]
    return ":".join([_KEY_PREFIX, *rendered])


def _consume_text(key: str) -> str | None:
    client = _redis_client()
    pipe = client.pipeline(transaction=True)
    pipe.get(key)
    pipe.delete(key)
    raw_value, _deleted = pipe.execute()
    return str(raw_value).strip() if raw_value is not None else None


def _delete_keys(*keys: str) -> None:
    rendered = [str(key).strip() for key in keys if str(key).strip()]
    if not rendered:
        return
    _redis_client().delete(*rendered)


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return None
    if isinstance(value, dict):
        safe_mapping: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if key.endswith(_VISIBLE_ROW_INTERNAL_SUFFIXES):
                continue
            safe_mapping[key] = _json_safe_value(raw_value)
        return safe_mapping
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    return value


def _json_safe_visible_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    normalized = _json_safe_value(row)
    return normalized if isinstance(normalized, dict) else None


def publish_user_notification(
    *,
    agency_id: int | None,
    user_id: int,
    event_type: str,
    title: str,
    body: str,
    data: dict[str, object] | None = None,
) -> None:
    if not _e2e_control_active():
        _raise_e2e_control_disabled("publish_user_notification")

    from server.api.notifications import record_and_notify

    record_and_notify(
        agency_id=agency_id,
        scope="user",
        event_type=event_type,
        title=title,
        body=body,
        user_id=user_id,
        data=data or {},
        actor="desktop-e2e",
    )


def schedule_next_import_pause(*, user_id: int, seconds: float) -> float:
    if not _e2e_control_active():
        _raise_e2e_control_disabled("schedule_next_import_pause")

    normalized_seconds = max(1.0, min(float(seconds), 60.0))
    _redis_client().setex(
        _control_key("import-pause-next", user_id),
        _CONTROL_TTL_SECONDS,
        f"{normalized_seconds:.3f}",
    )
    return normalized_seconds


def arm_pending_import_pause_for_job(*, user_id: int, job_id: str) -> float | None:
    if not _e2e_control_active():
        return None

    raw_value = _consume_text(_control_key("import-pause-next", user_id))
    if not raw_value:
        return None
    try:
        seconds = max(1.0, min(float(raw_value), 60.0))
    except ValueError:
        return None
    job_key = normalize_route_template(job_id)
    _redis_client().setex(
        _control_key("import-pause-job", job_key),
        _CONTROL_TTL_SECONDS,
        f"{seconds:.3f}",
    )
    _redis_client().setex(
        _control_key("import-pause-armed", job_key),
        _CONTROL_TTL_SECONDS,
        f"{seconds:.3f}",
    )
    return seconds


def pause_armed_for_job(*, job_id: str) -> bool:
    if not _e2e_control_active():
        return False

    return bool(
        _redis_client().exists(_control_key("import-pause-armed", normalize_route_template(job_id)))
    )


def clear_import_pause_for_job(*, job_id: str) -> None:
    if not _e2e_control_active():
        return

    job_key = normalize_route_template(job_id)
    _delete_keys(
        _control_key("import-pause-job", job_key),
        _control_key("import-pause-armed", job_key),
    )


def _job_cancel_requested(job_id: str) -> bool:
    if not _e2e_control_active():
        return False

    try:
        from server.services.import_chunk_workflow import workflow_payload
        from server.services.import_jobs import get_job_by_id

        job = get_job_by_id(job_id=job_id)
        if job is None:
            return True
        from server.imports.models import ImportJob

        if job.status != ImportJob.Status.RUNNING:
            return True
        payload = workflow_payload(job)
        return bool(payload.get("cancel_requested", False))
    except Exception:
        return False


def maybe_pause_import_job(*, job_id: str) -> float:
    if not _e2e_control_active():
        return 0.0

    normalized_job_id = normalize_route_template(job_id)
    raw_value = _consume_text(_control_key("import-pause-job", normalized_job_id))
    if not raw_value:
        return 0.0
    try:
        seconds = max(0.0, min(float(raw_value), 60.0))
    except ValueError:
        return 0.0
    deadline = time.monotonic() + seconds
    while True:
        if _job_cancel_requested(normalized_job_id):
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.1, remaining))
    return seconds


def inject_route_fault(
    *,
    user_id: int,
    route_template: str,
    status_code: int,
    detail: str,
    code: str,
) -> None:
    if not _e2e_control_active():
        _raise_e2e_control_disabled("inject_route_fault")

    payload = {
        "status_code": int(status_code),
        "detail": str(detail),
        "code": str(code),
    }
    _redis_client().setex(
        _control_key("route-fault", user_id, normalize_route_template(route_template)),
        _CONTROL_TTL_SECONDS,
        json.dumps(payload, ensure_ascii=True, sort_keys=True),
    )


def consume_route_fault(*, user_id: int, route_template: str) -> E2ERouteFault | None:
    if not _e2e_control_active():
        return None

    raw_value = _consume_text(
        _control_key("route-fault", user_id, normalize_route_template(route_template))
    )
    if not raw_value:
        return None
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    try:
        status_code = int(parsed.get("status_code", 0) or 0)
    except (TypeError, ValueError):
        return None
    if status_code < 400 or status_code > 599:
        return None
    detail = str(parsed.get("detail", "") or "Injected E2E fault.")
    code = str(parsed.get("code", "") or "E2E_FAULT")
    return E2ERouteFault(status_code=status_code, detail=detail, code=code)


def inspect_entity_state(
    *,
    entity_type: str,
    record_id: int | None = None,
    phone: str | None = None,
    family_name: str | None = None,
) -> dict[str, object]:
    normalized_type = str(entity_type or "").strip().lower()
    table_name = {
        "client": "clients",
        "clients": "clients",
        "listing": "listings",
        "listings": "listings",
    }.get(normalized_type)
    if table_name is None:
        raise ValueError("entity_type must be 'client' or 'listing'")

    resolved_record_id = int(record_id) if record_id is not None else None
    normalized_phone = str(phone or "").strip()
    normalized_family_name = str(family_name or "").strip()
    if (
        (resolved_record_id is None or resolved_record_id <= 0)
        and not normalized_phone
        and not normalized_family_name
    ):
        raise ValueError("record_id, phone, or family_name is required")

    get_entity_by_id: Callable[[int], Any | None]
    if table_name == "clients":
        from server.services.clients import get_client_by_id as get_entity_by_id
    else:
        from server.services.listings import get_listing_by_id as get_entity_by_id

    from server.pg.uow import admin_transaction

    select_columns = """
        id,
        agency_id,
        family_name,
        phone,
        status,
        owner_user_id,
        owner_role,
        visibility,
        deleted_at,
        row_version
    """
    admin_row: dict[str, object] | None = None
    with admin_transaction(schema="public") as session:
        if resolved_record_id is not None and resolved_record_id > 0:
            row = session.execute(
                f"""
                SELECT {select_columns}
                FROM {table_name}
                WHERE id = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (resolved_record_id,),
            ).fetchone()
            if row is not None:
                admin_row = dict(row)
                resolved_record_id = _coerce_int(admin_row.get("id"))
        else:
            from server.pg.uow import get_current_agency_id

            current_agency_id = int(get_current_agency_id() or 0)
            if current_agency_id <= 0:
                raise ValueError(
                    "current agency context is required for visible-field entity inspection"
                )
            candidate_rows = session.execute(
                f"""
                SELECT {select_columns}
                FROM {table_name}
                WHERE agency_id = %s
                ORDER BY id DESC
                LIMIT 200
                """,
                (current_agency_id,),
            ).fetchall()
            for row in candidate_rows:
                candidate_admin = dict(row)
                candidate_record_id = _coerce_int(candidate_admin.get("id"))
                if candidate_record_id <= 0:
                    continue
                visible_entity = get_entity_by_id(candidate_record_id)
                visible_row = (
                    _json_safe_visible_row(dict(visible_entity.to_dict()))
                    if visible_entity is not None
                    else None
                )
                if visible_row is None:
                    continue
                visible_phone = str(visible_row.get("phone") or "").strip()
                visible_family_name = str(visible_row.get("family_name") or "").strip()
                if normalized_phone and visible_phone != normalized_phone:
                    continue
                if normalized_family_name and visible_family_name != normalized_family_name:
                    continue
                admin_row = candidate_admin
                resolved_record_id = candidate_record_id
                break

    if admin_row is None or not resolved_record_id or resolved_record_id <= 0:
        return {
            "exists": False,
            "entity_type": "client" if table_name == "clients" else "listing",
            "record_id": int(resolved_record_id or 0),
            "phone": normalized_phone,
            "admin_row": None,
            "visible_to_current_user": False,
            "visible_row": None,
        }

    visible_entity = get_entity_by_id(resolved_record_id)
    visible_row = (
        _json_safe_visible_row(dict(visible_entity.to_dict()))
        if visible_entity is not None
        else None
    )
    return {
        "exists": True,
        "entity_type": "client" if table_name == "clients" else "listing",
        "record_id": int(resolved_record_id),
        "phone": str(admin_row.get("phone") or normalized_phone),
        "admin_row": admin_row,
        "visible_to_current_user": visible_entity is not None,
        "visible_row": visible_row,
    }


__all__ = [
    "E2ERouteFault",
    "E2E_BUILD_IDENTITY_FILE",
    "E2E_PRODUCT_IDENTITY_ROOTS",
    "REQUIRED_E2E_ROUTE_TEMPLATES",
    "arm_pending_import_pause_for_job",
    "build_code_identity",
    "build_file_fingerprints",
    "build_product_identity",
    "build_source_fingerprint",
    "clear_import_pause_for_job",
    "consume_route_fault",
    "e2e_test_mode_enabled",
    "file_sha256",
    "inspect_entity_state",
    "inject_route_fault",
    "iter_product_identity_files",
    "maybe_pause_import_job",
    "normalize_route_template",
    "pause_armed_for_job",
    "publish_user_notification",
    "read_build_identity",
    "repo_root",
    "required_route_presence",
    "runtime_identity",
    "schedule_next_import_pause",
    "write_build_identity",
]
