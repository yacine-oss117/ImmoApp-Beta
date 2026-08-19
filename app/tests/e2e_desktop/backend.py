from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import requests
from requests import Response

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    create_agency,
    create_manager_user,
    ensure_django,
)

ensure_django()

from server.accounts.models import UserSession  # noqa: E402
from server.imports.models import ImportJob  # noqa: E402
from server.pg.schema import ensure_schema  # noqa: E402
from server.pg.uow import use_actor_context, use_security_context  # noqa: E402
from server.services import clients as clients_service  # noqa: E402
from server.services import demandes as demandes_service  # noqa: E402
from server.services import e2e_control as e2e_control  # noqa: E402
from server.services import listings as listings_service  # noqa: E402
from server.services import matches as matches_service  # noqa: E402
from server.services import mfa_totp as mfa_totp  # noqa: E402
from server.services import offers as offers_service  # noqa: E402

_SCHEMA_READY = False
_SCHEMA_READY_LOCK = threading.Lock()
_REPO_ROOT = Path(__file__).resolve().parents[3]
_E2E_OWNER_TOTP_SECRET = "JBSWY3DPEHPK3PXP"


@dataclass(frozen=True)
class DesktopUser:
    agency_id: int
    user_id: int
    username: str
    password: str


@dataclass(frozen=True)
class MatchSeed:
    client_id: int
    demande_id: int
    listing_id: int
    offer_id: int
    client_name: str
    listing_owner: str
    location: str


@dataclass(frozen=True)
class BackendPreflightResult:
    base_url: str
    expected_code_identity: dict[str, object]
    actual_identity: dict[str, Any] | None
    missing_routes: tuple[str, ...]
    identity_match: bool


@dataclass(frozen=True)
class FrontDoorPreflightResult:
    base_url: str
    health_status: int
    identity_status: int
    front_door_header: str
    identity: dict[str, Any]


def numeric_suffix(length: int = 6) -> str:
    width = max(1, int(length))
    return str(uuid.uuid4().int % (10**width)).zfill(width)


def normalize_base_url(base_url: str) -> str:
    return str(base_url).rstrip("/")


def _coerce_payload_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def ensure_backend_ready(
    base_url: str,
    *,
    timeout: float = 10.0,
) -> BackendPreflightResult:
    normalized = normalize_base_url(base_url)
    _ensure_health_ready(normalized, timeout=timeout)
    _ensure_auth_endpoint_ready(normalized, timeout=timeout)
    expected_identity = expected_checkout_code_identity()
    return _ensure_backend_identity_ready(
        normalized,
        timeout=timeout,
        expected_code_identity=expected_identity,
    )


def ensure_front_door_ready(
    base_url: str,
    *,
    timeout: float = 10.0,
) -> FrontDoorPreflightResult:
    normalized = normalize_base_url(base_url)
    deadline = time.monotonic() + timeout
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            health = requests.get(
                f"{normalized}/api/v1/health/",
                timeout=2.0,
            )
            identity = requests.get(
                f"{normalized}/api/v1/hub/front-door/identity/",
                timeout=2.0,
            )
            header = str(identity.headers.get("X-ImmoApp-Front-Door") or "")
            payload = identity.json()
            if (
                health.status_code == 200
                and identity.status_code == 200
                and header.lower() == "caddy"
                and isinstance(payload, dict)
                and payload.get("kind") == "immoapp_hub_front_door_identity"
                and int(str(payload.get("schema_version") or "0")) == 1
            ):
                return FrontDoorPreflightResult(
                    base_url=normalized,
                    health_status=int(health.status_code),
                    identity_status=int(identity.status_code),
                    front_door_header=header,
                    identity=payload,
                )
            last_error = (
                "health={health} identity={identity} front-door-header={header!r} "
                "kind={kind!r} schema={schema!r}"
            ).format(
                health=health.status_code,
                identity=identity.status_code,
                header=header,
                kind=payload.get("kind") if isinstance(payload, dict) else type(payload).__name__,
                schema=payload.get("schema_version") if isinstance(payload, dict) else "",
            )
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.5)
    raise RuntimeError(
        "Desktop E2E Hub front-door preflight failed at "
        f"{normalized}/api/v1/hub/front-door/identity/. Last error: {last_error}"
    )


def expected_checkout_code_identity() -> dict[str, object]:
    return cast(dict[str, object], e2e_control.build_code_identity(_REPO_ROOT))


def expected_checkout_identity_payload() -> dict[str, object]:
    return {
        "code_identity": expected_checkout_code_identity(),
        "build_identity": e2e_control.build_product_identity(_REPO_ROOT),
        "server_files_fingerprint": {
            "aggregate_sha256": e2e_control.build_source_fingerprint(_REPO_ROOT),
            "files": e2e_control.build_file_fingerprints(_REPO_ROOT),
        },
        "required_routes": list(e2e_control.REQUIRED_E2E_ROUTE_TEMPLATES),
    }


def _ensure_backend_identity_ready(
    base_url: str,
    *,
    timeout: float,
    expected_code_identity: dict[str, object],
) -> BackendPreflightResult:
    user = create_desktop_user(prefix="e2epreflight", can_import=False)
    try:
        token = auth_token(base_url, user)
        identity = _json_request(
            method="GET",
            url=f"{base_url}/api/v1/e2e/runtime/identity/",
            token=token,
            timeout=timeout,
            expected_code_identity=expected_code_identity,
        )
    finally:
        cleanup_desktop_user(user)

    route_presence = identity.get("route_presence")
    present_routes = route_presence if isinstance(route_presence, dict) else {}
    missing_routes = tuple(
        route
        for route in e2e_control.REQUIRED_E2E_ROUTE_TEMPLATES
        if present_routes.get(route) is not True
    )
    code_identity = identity.get("code_identity")
    actual_code_identity = code_identity if isinstance(code_identity, dict) else {}
    expected_fingerprint = str(expected_code_identity.get("source_fingerprint") or "")
    actual_fingerprint = str(actual_code_identity.get("source_fingerprint") or "")
    expected_git_sha = str(expected_code_identity.get("git_sha") or "")
    actual_git_sha = str(actual_code_identity.get("git_sha") or "")
    git_matches = not (expected_git_sha and actual_git_sha) or expected_git_sha == actual_git_sha
    runtime_identity_match = (
        bool(expected_fingerprint) and expected_fingerprint == actual_fingerprint and git_matches
    )
    e2e_enabled = identity.get("e2e_test_mode") is True
    runtime_source_mode = str(identity.get("runtime_source_mode") or "unknown")
    build_identity = identity.get("build_identity")
    actual_build_identity = build_identity if isinstance(build_identity, dict) else {}
    build_code_identity = actual_build_identity.get("code_identity")
    actual_build_code_identity = (
        build_code_identity if isinstance(build_code_identity, dict) else {}
    )
    build_fingerprint = str(actual_build_code_identity.get("source_fingerprint") or "")
    build_identity_required = runtime_source_mode == "image"
    build_identity_match = not build_identity_required or (
        bool(build_fingerprint) and build_fingerprint == expected_fingerprint
    )
    identity_match = runtime_identity_match and build_identity_match
    if runtime_source_mode == "synced_container":
        raise RuntimeError(
            _format_backend_identity_error(
                base_url=base_url,
                reason=(
                    "Backend reports runtime_source_mode=synced_container. Product desktop E2E "
                    "does not support copied-file container sync; rebuild the backend image from "
                    "this checkout."
                ),
                expected_code_identity=expected_code_identity,
                actual_identity=identity,
                missing_routes=missing_routes,
            )
        )
    if not e2e_enabled or missing_routes or not identity_match:
        reasons: list[str] = []
        if not e2e_enabled:
            reasons.append("E2E backend mode is disabled.")
        if missing_routes:
            reasons.append("Required E2E routes are missing.")
        if not runtime_identity_match:
            reasons.append("Running backend code identity does not match this checkout.")
        if build_identity_required and not actual_build_identity:
            reasons.append("Backend image build identity is missing.")
        elif not build_identity_match:
            reasons.append("Backend image build identity does not match this checkout.")
        raise RuntimeError(
            _format_backend_identity_error(
                base_url=base_url,
                reason=" ".join(reasons),
                expected_code_identity=expected_code_identity,
                actual_identity=identity,
                missing_routes=missing_routes,
            )
        )
    return BackendPreflightResult(
        base_url=base_url,
        expected_code_identity=expected_code_identity,
        actual_identity=identity,
        missing_routes=missing_routes,
        identity_match=True,
    )


def _format_backend_identity_error(
    *,
    base_url: str,
    reason: str,
    expected_code_identity: dict[str, object] | None = None,
    actual_identity: dict[str, Any] | None = None,
    missing_routes: tuple[str, ...] = (),
    route_path: str | None = None,
) -> str:
    expected = expected_code_identity or expected_checkout_code_identity()
    actual_code: dict[str, object] = {}
    actual_build_code: dict[str, object] = {}
    runtime_source_mode = "unknown"
    if actual_identity is not None:
        raw_actual_code = actual_identity.get("code_identity")
        if isinstance(raw_actual_code, dict):
            actual_code = {str(key): value for key, value in raw_actual_code.items()}
        raw_build_identity = actual_identity.get("build_identity")
        if isinstance(raw_build_identity, dict):
            raw_build_code = raw_build_identity.get("code_identity")
            if isinstance(raw_build_code, dict):
                actual_build_code = {str(key): value for key, value in raw_build_code.items()}
        runtime_source_mode = str(actual_identity.get("runtime_source_mode") or "unknown")
    lines = [
        "Desktop E2E backend preflight failed.",
        f"Reason: {reason}",
        f"Base URL: {base_url}",
    ]
    if route_path:
        lines.append(f"Route: {route_path}")
    lines.extend(
        [
            f"Expected fingerprint: {expected.get('source_fingerprint') or '<missing>'}",
            f"Actual fingerprint: {actual_code.get('source_fingerprint') or '<missing>'}",
            "Actual image build fingerprint: "
            f"{actual_build_code.get('source_fingerprint') or '<missing>'}",
            f"Expected git SHA: {expected.get('git_sha') or '<unavailable>'}",
            f"Actual git SHA: {actual_code.get('git_sha') or '<unavailable>'}",
            f"Backend runtime source mode: {runtime_source_mode}",
        ]
    )
    if missing_routes:
        lines.append(f"Missing E2E routes: {', '.join(missing_routes)}")
    lines.append(
        "Rebuild/restart the Docker backend from this checkout with: "
        "powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_e2e_desktop.ps1 "
        "-Suite smoke -RebuildBackend"
    )
    lines.append("Copied-file container sync is unsupported for product desktop E2E.")
    return "\n".join(lines)


def _ensure_health_ready(base_url: str, *, timeout: float) -> None:
    deadline = time.monotonic() + max(float(timeout), 60.0)
    last_error: Exception | None = None
    last_status: int | None = None
    last_detail = ""
    while time.monotonic() < deadline:
        try:
            response = requests.get(
                f"{base_url}/api/v1/health/ready/",
                timeout=min(float(timeout), 8.0),
            )
            if response.status_code == 200:
                return
            last_status = response.status_code
            last_detail = response.text.strip()
        except requests.RequestException as exc:  # pragma: no cover - exercised in live runs
            last_error = exc
        time.sleep(0.5)
    if last_status is not None:
        raise RuntimeError(
            f"Desktop E2E backend readiness failed at {base_url}/api/v1/health/ready/ "
            f"(status {last_status}). {last_detail}"
        )
    raise RuntimeError(
        f"Desktop E2E backend is not reachable at {base_url}. Start the local backend stack first."
    ) from last_error


def _ensure_auth_endpoint_ready(base_url: str, *, timeout: float) -> None:
    deadline = time.monotonic() + max(float(timeout), 10.0)
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = requests.post(
                f"{base_url}/api/auth/token/",
                json={"username": "__desktop_e2e_probe__", "password": "__desktop_e2e_probe__"},
                timeout=min(timeout, 8.0),
            )
            if response.status_code < 500:
                return
            last_error = RuntimeError(
                f"Auth endpoint returned status {response.status_code}: {response.text.strip()}"
            )
        except requests.RequestException as exc:  # pragma: no cover - exercised in live runs
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(
        f"Desktop E2E backend auth endpoint is not ready at {base_url}/api/auth/token/."
    ) from last_error


def ensure_seed_schema_ready() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_READY_LOCK:
        if _SCHEMA_READY:
            return
        ensure_schema()
        _SCHEMA_READY = True


def create_desktop_user(*, prefix: str, can_import: bool = False) -> DesktopUser:
    ensure_seed_schema_ready()
    suffix = uuid.uuid4().hex[:8]
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"{prefix.upper()}_{suffix}", f"{prefix} Agency {suffix}")
        username = f"{prefix.lower()}_{suffix}"
        password = "StrongTestPass_123!"
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=username,
            password=password,
        )
        conn.execute(
            """
            UPDATE accounts_user
            SET can_import = %s
            WHERE id = %s
            """,
            (bool(can_import), user_id),
        )
        conn.commit()
        return DesktopUser(
            agency_id=int(agency_id),
            user_id=int(user_id),
            username=username,
            password=password,
        )
    finally:
        conn.close()


def create_owner_user_for_agency(*, agency_id: int, prefix: str) -> DesktopUser:
    ensure_seed_schema_ready()
    suffix = uuid.uuid4().hex[:8]
    conn = admin_conn()
    try:
        username = f"{prefix.lower()}_{suffix}"
        password = "StrongTestPass_123!"
        user_id = create_manager_user(
            conn,
            agency_id=int(agency_id),
            username=username,
            password=password,
        )
        conn.execute(
            """
            UPDATE accounts_user
            SET is_owner = TRUE,
                mfa_totp_enabled = TRUE,
                mfa_totp_secret = %s,
                mfa_totp_secret_enc = '',
                mfa_totp_enrolled_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (_E2E_OWNER_TOTP_SECRET, user_id),
        )
        conn.commit()
        return DesktopUser(
            agency_id=int(agency_id),
            user_id=int(user_id),
            username=username,
            password=password,
        )
    finally:
        conn.close()


def cleanup_desktop_user(user: DesktopUser) -> None:
    conn = admin_conn()
    try:
        agency_id = int(user.agency_id)
        user_id = int(user.user_id)
        conn.execute("SET session_replication_role = replica")
        conn.execute("DELETE FROM match_pairs WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM match_candidates WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM task_failures WHERE agency_id = %s", (agency_id,))
        conn.execute(
            """
            DELETE FROM notification_reads
            WHERE notification_id IN (
                SELECT id
                FROM notifications
                WHERE agency_id = %s
            )
               OR user_id = %s
            """,
            (agency_id, user_id),
        )
        conn.execute("DELETE FROM notifications WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM accounts_userinvite WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM agency_settings WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM surface_cache_generation WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM match_counts_cache WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM demande_locations WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM offer_locations WHERE agency_id = %s", (agency_id,))
        conn.execute(
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
        conn.execute(
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
        conn.execute(
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
        conn.execute(
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
        conn.execute(
            "DELETE FROM imports_importartifactmanifest WHERE agency_id = %s", (agency_id,)
        )
        conn.execute("DELETE FROM imports_importchunk WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM imports_importdeadletterrow WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM imports_importrowaudit WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM imports_importagencyprofile WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM imports_importjob WHERE agency_id = %s", (agency_id,))
        conn.execute(
            "DELETE FROM offer_photos WHERE offer_id IN (SELECT id FROM offers WHERE agency_id = %s)",
            (agency_id,),
        )
        conn.execute("DELETE FROM offers WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM listings WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM demandes WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM visits WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM contracts WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM custom_locations WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM match_rebuild_state WHERE agency_id = %s", (agency_id,))
        conn.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_id,))
        conn.execute(
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
            (agency_id, user_id, agency_id),
        )
        conn.execute(
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
            (agency_id, user_id, agency_id, user_id),
        )
        conn.execute("DELETE FROM storage_usage WHERE agency_id = %s", (agency_id,))
        conn.execute(
            "DELETE FROM storage_objects WHERE agency_id = %s OR user_id = %s",
            (agency_id, user_id),
        )
        conn.execute("DELETE FROM api_idempotency_records WHERE agency_id = %s", (agency_id,))
        conn.execute(
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
            (user_id, agency_id),
        )
        conn.execute(
            "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s OR user_id IN "
            "(SELECT id FROM accounts_user WHERE agency_id = %s)",
            (user_id, agency_id),
        )
        conn.execute(
            """
            DELETE FROM accounts_usersession
            WHERE user_id = %s
               OR user_id IN (
                   SELECT id
                   FROM accounts_user
                   WHERE agency_id = %s
               )
            """,
            (user_id, agency_id),
        )
        conn.execute(
            "DELETE FROM accounts_user WHERE agency_id = %s OR id = %s", (agency_id, user_id)
        )
        conn.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        conn.execute("SET session_replication_role = origin")
        conn.commit()
    except Exception:
        try:
            conn.execute("SET session_replication_role = origin")
        except Exception:
            pass
        conn.rollback()
        raise
    finally:
        conn.close()


def latest_import_job(*, user_id: int, filename: str) -> ImportJob | None:
    return cast(
        ImportJob | None,
        ImportJob.objects.filter(user_id=int(user_id), filename=str(filename))
        .order_by("-created_at")
        .first(),
    )


def wait_for_import_job(
    *,
    user_id: int,
    filename: str,
    predicate: Callable[[ImportJob], bool],
    timeout: float = 60.0,
    interval: float = 0.25,
) -> ImportJob:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = latest_import_job(user_id=user_id, filename=filename)
        if job is not None and predicate(job):
            return job
        time.sleep(interval)
    raise AssertionError(f"Timed out waiting for import job {filename!r} for user {user_id}")


def client_exists(*, agency_id: int, phone: str) -> bool:
    with use_security_context(agency_id=agency_id, is_superuser=False):
        return bool(clients_service.find_client_ids_by_phone(phone))


def listing_exists(*, agency_id: int, phone: str) -> bool:
    with use_security_context(agency_id=agency_id, is_superuser=False):
        return bool(listings_service.find_listing_ids_by_phone(phone))


def fetch_client_row(*, agency_id: int, phone: str) -> dict[str, object] | None:
    with use_security_context(agency_id=agency_id, is_superuser=False):
        payload = e2e_control.inspect_entity_state(entity_type="client", phone=phone)
    visible_row = payload.get("visible_row")
    return (
        {str(key): value for key, value in visible_row.items()}
        if isinstance(visible_row, dict)
        else None
    )


def fetch_listing_row(*, agency_id: int, phone: str) -> dict[str, object] | None:
    with use_security_context(agency_id=agency_id, is_superuser=False):
        payload = e2e_control.inspect_entity_state(entity_type="listing", phone=phone)
    visible_row = payload.get("visible_row")
    return (
        {str(key): value for key, value in visible_row.items()}
        if isinstance(visible_row, dict)
        else None
    )


def count_clients(*, agency_id: int) -> int:
    conn = admin_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM clients WHERE agency_id = %s",
            (agency_id,),
        ).fetchone()
        return int((row or {}).get("count") or 0)
    finally:
        conn.close()


def count_listings(*, agency_id: int) -> int:
    conn = admin_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM listings WHERE agency_id = %s",
            (agency_id,),
        ).fetchone()
        return int((row or {}).get("count") or 0)
    finally:
        conn.close()


def _e2e_route_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    prefix = "api/v1/"
    if not path.startswith(prefix):
        return None
    route = path[len(prefix) :].strip("/")
    if not route.startswith("e2e/"):
        return None
    return f"{route}/"


def _raise_for_backend_response(
    response: Response,
    *,
    url: str,
    expected_code_identity: dict[str, object] | None = None,
    actual_identity: dict[str, Any] | None = None,
) -> None:
    route_path = _e2e_route_from_url(url)
    if response.status_code == 404 and route_path is not None:
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else url
        raise RuntimeError(
            _format_backend_identity_error(
                base_url=base_url,
                reason="E2E control endpoints are disabled or the running backend is stale.",
                expected_code_identity=expected_code_identity,
                actual_identity=actual_identity,
                route_path=route_path,
            )
        )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = response.text.strip()
        if detail:
            raise requests.HTTPError(f"{exc}; response body: {detail}", response=response) from exc
        raise


def _authed_request(
    *,
    method: str,
    base_url: str,
    user: DesktopUser,
    path: str,
    params: dict[str, object] | None = None,
    payload: dict[str, object] | None = None,
    timeout: float = 15.0,
) -> Response:
    token = auth_token(base_url, user)
    url = f"{normalize_base_url(base_url)}/api/v1/{path.strip('/').rstrip('/')}/"
    request_params: dict[str, str | int | float] | None = None
    if params is not None:
        request_params = {
            str(key): value for key, value in params.items() if isinstance(value, (str, int, float))
        }
    response = requests.request(
        method=method,
        url=url,
        params=request_params,
        json=payload or None,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    _raise_for_backend_response(response, url=url)
    return response


def _api_items_from_list_response(response: Response) -> list[dict[str, object]]:
    payload = response.json()
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, dict)]


def _matching_api_row(
    *,
    items: list[dict[str, object]],
    family_name: str | None = None,
    phone: str | None = None,
) -> dict[str, object] | None:
    normalized_family_name = str(family_name or "").strip()
    normalized_phone = str(phone or "").strip()
    exact_matches: list[dict[str, object]] = []
    for item in items:
        item_family_name = str(item.get("family_name") or "").strip()
        item_phone = str(item.get("phone") or "").strip()
        if normalized_family_name and item_family_name != normalized_family_name:
            continue
        if normalized_phone and item_phone != normalized_phone:
            continue
        exact_matches.append(item)
    if not exact_matches:
        return None
    return max(exact_matches, key=lambda item: _coerce_payload_int(item.get("id")))


def _search_clients(*, base_url: str, user: DesktopUser, search: str) -> list[dict[str, object]]:
    response = _authed_request(
        method="GET",
        base_url=base_url,
        user=user,
        path="clients",
        params={"search": search, "limit": 50, "offset": 0, "include_deleted": 0},
    )
    return _api_items_from_list_response(response)


def _search_listings(*, base_url: str, user: DesktopUser, search: str) -> list[dict[str, object]]:
    response = _authed_request(
        method="GET",
        base_url=base_url,
        user=user,
        path="listings",
        params={"search": search, "limit": 50, "offset": 0, "include_deleted": 0},
    )
    return _api_items_from_list_response(response)


def api_client_exists(*, base_url: str, user: DesktopUser, phone: str) -> bool:
    return (
        _matching_api_row(
            items=_search_clients(base_url=base_url, user=user, search=phone),
            phone=phone,
        )
        is not None
    )


def api_listing_exists(*, base_url: str, user: DesktopUser, phone: str) -> bool:
    return (
        _matching_api_row(
            items=_search_listings(base_url=base_url, user=user, search=phone),
            phone=phone,
        )
        is not None
    )


def api_create_client(
    *,
    base_url: str,
    user: DesktopUser,
    family_name: str,
    phone: str,
    remarks: str = "",
) -> int:
    response = _authed_request(
        method="POST",
        base_url=base_url,
        user=user,
        path="clients",
        payload={
            "family_name": family_name,
            "phone": phone,
            "remarks": remarks,
            "status": "active",
        },
    )
    payload = response.json()
    return _coerce_payload_int(payload.get("id") if isinstance(payload, dict) else None)


def api_create_listing(
    *,
    base_url: str,
    user: DesktopUser,
    family_name: str,
    phone: str,
    remarks: str = "",
) -> int:
    response = _authed_request(
        method="POST",
        base_url=base_url,
        user=user,
        path="listings",
        payload={
            "family_name": family_name,
            "phone": phone,
            "remarks": remarks,
            "status": "available",
        },
    )
    payload = response.json()
    return _coerce_payload_int(payload.get("id") if isinstance(payload, dict) else None)


def api_create_demande(
    *,
    base_url: str,
    user: DesktopUser,
    client_id: int,
    payload: dict[str, object],
) -> int:
    response = _authed_request(
        method="POST",
        base_url=base_url,
        user=user,
        path=f"clients/{int(client_id)}/demandes",
        payload=payload,
    )
    response_payload = response.json()
    return _coerce_payload_int(
        response_payload.get("id") if isinstance(response_payload, dict) else None
    )


def api_create_offer(
    *,
    base_url: str,
    user: DesktopUser,
    listing_id: int,
    payload: dict[str, object],
) -> int:
    response = _authed_request(
        method="POST",
        base_url=base_url,
        user=user,
        path=f"listings/{int(listing_id)}/offers",
        payload=payload,
    )
    response_payload = response.json()
    return _coerce_payload_int(
        response_payload.get("id") if isinstance(response_payload, dict) else None
    )


def api_find_client_row(
    *,
    base_url: str,
    user: DesktopUser,
    search: str,
    family_name: str | None = None,
    phone: str | None = None,
) -> dict[str, object] | None:
    payload = api_inspect_entity(
        base_url=base_url,
        user=user,
        entity_type="client",
        family_name=family_name or search,
        phone=phone,
    )
    visible_row = payload.get("visible_row")
    if not isinstance(visible_row, dict):
        return None
    return {str(key): value for key, value in visible_row.items()}


def api_find_listing_row(
    *,
    base_url: str,
    user: DesktopUser,
    search: str,
    family_name: str | None = None,
    phone: str | None = None,
) -> dict[str, object] | None:
    payload = api_inspect_entity(
        base_url=base_url,
        user=user,
        entity_type="listing",
        family_name=family_name or search,
        phone=phone,
    )
    visible_row = payload.get("visible_row")
    if not isinstance(visible_row, dict):
        return None
    return {str(key): value for key, value in visible_row.items()}


def api_fetch_client_row(
    *, base_url: str, user: DesktopUser, phone: str
) -> dict[str, object] | None:
    matched_row = _matching_api_row(
        items=_search_clients(base_url=base_url, user=user, search=phone),
        phone=phone,
    )
    if matched_row is None:
        return None
    client_id = _coerce_payload_int(matched_row.get("id"))
    if client_id <= 0:
        return None
    detail_response = _authed_request(
        method="GET",
        base_url=base_url,
        user=user,
        path=f"clients/{client_id}",
        params={"include_deleted": 0},
    )
    payload = detail_response.json()
    return dict(payload) if isinstance(payload, dict) else None


def api_fetch_listing_row(
    *,
    base_url: str,
    user: DesktopUser,
    phone: str,
) -> dict[str, object] | None:
    matched_row = _matching_api_row(
        items=_search_listings(base_url=base_url, user=user, search=phone),
        phone=phone,
    )
    if matched_row is None:
        return None
    listing_id = _coerce_payload_int(matched_row.get("id"))
    if listing_id <= 0:
        return None
    detail_response = _authed_request(
        method="GET",
        base_url=base_url,
        user=user,
        path=f"listings/{listing_id}",
        params={"include_deleted": 0},
    )
    payload = detail_response.json()
    return dict(payload) if isinstance(payload, dict) else None


def api_fetch_client_by_id(
    *,
    base_url: str,
    user: DesktopUser,
    client_id: int,
) -> dict[str, object] | None:
    try:
        response = _authed_request(
            method="GET",
            base_url=base_url,
            user=user,
            path=f"clients/{int(client_id)}",
            params={"include_deleted": 0},
        )
    except requests.exceptions.HTTPError as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code == 404:
            return None
        raise
    payload = response.json()
    return dict(payload) if isinstance(payload, dict) else None


def api_fetch_listing_by_id(
    *,
    base_url: str,
    user: DesktopUser,
    listing_id: int,
) -> dict[str, object] | None:
    try:
        response = _authed_request(
            method="GET",
            base_url=base_url,
            user=user,
            path=f"listings/{int(listing_id)}",
            params={"include_deleted": 0},
        )
    except requests.exceptions.HTTPError as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code == 404:
            return None
        raise
    payload = response.json()
    return dict(payload) if isinstance(payload, dict) else None


def api_fetch_client_demandes(
    *,
    base_url: str,
    user: DesktopUser,
    client_id: int,
    include_deleted: bool = False,
) -> list[dict[str, object]]:
    response = _authed_request(
        method="GET",
        base_url=base_url,
        user=user,
        path=f"clients/{int(client_id)}/demandes",
        params={"limit": 50, "offset": 0, "include_deleted": int(include_deleted)},
    )
    return _api_items_from_list_response(response)


def api_fetch_demande(
    *,
    base_url: str,
    user: DesktopUser,
    demande_id: int,
    include_deleted: bool = False,
) -> dict[str, object] | None:
    try:
        response = _authed_request(
            method="GET",
            base_url=base_url,
            user=user,
            path=f"demandes/{int(demande_id)}",
            params={"include_deleted": int(include_deleted)},
        )
    except requests.exceptions.HTTPError as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code == 404:
            return None
        raise
    payload = response.json()
    return dict(payload) if isinstance(payload, dict) else None


def api_fetch_deleted_demandes(*, base_url: str, user: DesktopUser) -> list[dict[str, object]]:
    response = _authed_request(
        method="GET",
        base_url=base_url,
        user=user,
        path="demandes/deleted",
        params={"limit": 200, "offset": 0},
    )
    return _api_items_from_list_response(response)


def api_fetch_listing_offers(
    *,
    base_url: str,
    user: DesktopUser,
    listing_id: int,
    include_deleted: bool = False,
) -> list[dict[str, object]]:
    response = _authed_request(
        method="GET",
        base_url=base_url,
        user=user,
        path=f"listings/{int(listing_id)}/offers",
        params={"limit": 50, "offset": 0, "include_deleted": int(include_deleted)},
    )
    return _api_items_from_list_response(response)


def api_fetch_offer(
    *,
    base_url: str,
    user: DesktopUser,
    offer_id: int,
    include_deleted: bool = False,
) -> dict[str, object] | None:
    try:
        response = _authed_request(
            method="GET",
            base_url=base_url,
            user=user,
            path=f"offers/{int(offer_id)}",
            params={"include_deleted": int(include_deleted)},
        )
    except requests.exceptions.HTTPError as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code == 404:
            return None
        raise
    payload = response.json()
    return dict(payload) if isinstance(payload, dict) else None


def api_fetch_offer_photos(
    *,
    base_url: str,
    user: DesktopUser,
    offer_id: int,
    include_deleted: bool = False,
) -> list[dict[str, object]]:
    response = _authed_request(
        method="GET",
        base_url=base_url,
        user=user,
        path=f"offers/{int(offer_id)}/photos",
        params={"include_deleted": int(include_deleted)},
    )
    return _api_items_from_list_response(response)


def fetch_storage_object_row(
    *,
    agency_id: int,
    storage_id: str,
) -> dict[str, object] | None:
    conn = admin_conn()
    try:
        row = conn.execute(
            """
            SELECT id, agency_id, user_id, role, purpose, status, content_type,
                   size_bytes, deleted_at, bucket, object_key
            FROM storage_objects
            WHERE id = %s AND agency_id = %s
            """,
            (storage_id, int(agency_id)),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def api_fetch_deleted_offers(*, base_url: str, user: DesktopUser) -> list[dict[str, object]]:
    response = _authed_request(
        method="GET",
        base_url=base_url,
        user=user,
        path="offers/deleted",
        params={"limit": 200, "offset": 0},
    )
    return _api_items_from_list_response(response)


def api_fetch_contracts(
    *,
    base_url: str,
    user: DesktopUser,
    status: str | None = None,
    contract_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    response = _authed_request(
        method="GET",
        base_url=base_url,
        user=user,
        path="crm/contracts",
        params={
            "status": status or "",
            "contract_type": contract_type or "",
            "limit": int(limit),
            "offset": 0,
        },
    )
    return _api_items_from_list_response(response)


def api_fetch_contract(
    *,
    base_url: str,
    user: DesktopUser,
    contract_id: int,
) -> dict[str, object] | None:
    try:
        response = _authed_request(
            method="GET",
            base_url=base_url,
            user=user,
            path=f"crm/contracts/{int(contract_id)}",
        )
    except requests.exceptions.HTTPError as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code == 404:
            return None
        raise
    payload = response.json()
    return dict(payload) if isinstance(payload, dict) else None


def api_fetch_deleted_contracts(
    *,
    base_url: str,
    user: DesktopUser,
    limit: int = 100,
) -> list[dict[str, object]]:
    response = _authed_request(
        method="GET",
        base_url=base_url,
        user=user,
        path="crm/contracts/deleted",
        params={"limit": int(limit), "offset": 0},
    )
    return _api_items_from_list_response(response)


def api_inspect_entity(
    *,
    base_url: str,
    user: DesktopUser,
    entity_type: str,
    record_id: int | None = None,
    phone: str | None = None,
    family_name: str | None = None,
) -> dict[str, Any]:
    response = _authed_request(
        method="GET",
        base_url=base_url,
        user=user,
        path="e2e/entities/inspect",
        params={
            "entity_type": entity_type,
            "record_id": record_id,
            "phone": phone or "",
            "family_name": family_name or "",
        },
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("E2E inspect endpoint returned a non-object payload")
    return {str(key): value for key, value in payload.items()}


def active_session_count(*, user_id: int) -> int:
    orm_count = int(
        UserSession.objects.filter(user_id=int(user_id), revoked_at__isnull=True).count()
    )
    conn = admin_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM token_blacklist_outstandingtoken WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        token_count = int((row or {}).get("count") or 0)
    finally:
        conn.close()
    return max(orm_count, token_count)


def active_session_ids(*, user_id: int) -> list[str]:
    rows = (
        UserSession.objects.filter(user_id=int(user_id), revoked_at__isnull=True)
        .order_by("-created_at")
        .values_list("session_id", flat=True)
    )
    return [str(value) for value in rows]


def newest_active_session_id(*, user_id: int) -> str | None:
    session_ids = active_session_ids(user_id=user_id)
    return session_ids[0] if session_ids else None


def user_is_active(*, user_id: int) -> bool:
    conn = admin_conn()
    try:
        row = conn.execute(
            "SELECT is_active FROM accounts_user WHERE id = %s",
            (int(user_id),),
        ).fetchone()
        return bool(row and row.get("is_active"))
    finally:
        conn.close()


def insert_existing_client(
    *,
    agency_id: int,
    user_id: int,
    family_name: str,
    phone: str,
    remarks: str,
) -> int:
    with use_security_context(agency_id=agency_id, is_superuser=False):
        with use_actor_context(actor_id=user_id, actor_role="manager", actor_is_owner=False):
            return int(
                clients_service.upsert_client(
                    {
                        "family_name": family_name,
                        "phone": phone,
                        "remarks": remarks,
                        "status": "active",
                    },
                    actor=f"e2e:{user_id}",
                )
            )


def insert_existing_listing(
    *,
    agency_id: int,
    user_id: int,
    family_name: str,
    phone: str,
    remarks: str,
) -> int:
    with use_security_context(agency_id=agency_id, is_superuser=False):
        with use_actor_context(actor_id=user_id, actor_role="manager", actor_is_owner=False):
            return int(
                listings_service.upsert_listing(
                    {
                        "family_name": family_name,
                        "phone": phone,
                        "remarks": remarks,
                        "status": "available",
                    },
                    actor=f"e2e:{user_id}",
                )
            )


def seed_match_entities(
    *,
    user: DesktopUser,
    client_name: str,
    listing_owner: str,
    base_url: str | None = None,
) -> MatchSeed:
    client_phone = f"213555{numeric_suffix(6)}"
    listing_phone = f"213666{numeric_suffix(6)}"
    demande_payload: dict[str, object] = {
        "action": "buy",
        "action_id": 1,
        "type": "apartment",
        "type_id": 1,
        "wilaya": "Algiers",
        "wilaya_id": 16,
        "locations": "",
        "budget_min": 100,
        "budget_max": 300,
        "surface_min": 60,
        "surface_max": 120,
        "beds_min": 2,
        "floor_min": 0,
        "floor_max": 8,
        "elevator": 1,
        "accessibility_required": 1,
    }
    offer_payload: dict[str, object] = {
        "action": "sell",
        "action_id": 3,
        "type": "apartment",
        "type_id": 1,
        "status": "available",
        "wilaya": "Algiers",
        "wilaya_id": 16,
        "location": "Hydra",
        "beds": 3,
        "surface": 90,
        "budget": 200,
        "floor": 2,
        "elevator": 1,
        "accessibility_supported": 1,
        "remarks": "desktop e2e offer",
    }
    if base_url:
        client_id = api_create_client(
            base_url=base_url,
            user=user,
            family_name=client_name,
            phone=client_phone,
            remarks="desktop e2e match client",
        )
        demande_id = api_create_demande(
            base_url=base_url,
            user=user,
            client_id=client_id,
            payload=demande_payload,
        )
        listing_id = api_create_listing(
            base_url=base_url,
            user=user,
            family_name=listing_owner,
            phone=listing_phone,
            remarks="desktop e2e match listing",
        )
        offer_id = api_create_offer(
            base_url=base_url,
            user=user,
            listing_id=listing_id,
            payload=offer_payload,
        )
        return MatchSeed(
            client_id=client_id,
            demande_id=demande_id,
            listing_id=listing_id,
            offer_id=offer_id,
            client_name=client_name,
            listing_owner=listing_owner,
            location="Hydra",
        )

    with use_security_context(agency_id=user.agency_id, is_superuser=False):
        with use_actor_context(actor_id=user.user_id, actor_role="manager", actor_is_owner=False):
            client_id = int(
                clients_service.upsert_client(
                    {
                        "family_name": client_name,
                        "phone": client_phone,
                        "remarks": "desktop e2e match client",
                        "status": "active",
                    },
                    actor=f"e2e:{user.user_id}",
                )
            )
            demande_id = int(
                demandes_service.create_demande(
                    client_id,
                    demande_payload,
                    actor=f"e2e:{user.user_id}",
                )
            )
            listing_id = int(
                listings_service.upsert_listing(
                    {
                        "family_name": listing_owner,
                        "phone": listing_phone,
                        "remarks": "desktop e2e match listing",
                        "status": "available",
                    },
                    actor=f"e2e:{user.user_id}",
                )
            )
            offer_id = int(
                offers_service.create_offer(
                    listing_id,
                    offer_payload,
                    actor=f"e2e:{user.user_id}",
                )
            )
            return MatchSeed(
                client_id=client_id,
                demande_id=demande_id,
                listing_id=listing_id,
                offer_id=offer_id,
                client_name=client_name,
                listing_owner=listing_owner,
                location="Hydra",
            )


def fetch_match_count(*, agency_id: int, client_id: int) -> int:
    with use_security_context(agency_id=agency_id, is_superuser=False):
        return int(matches_service.count_matches_for_single_client(client_id))


def api_fetch_client_matches(
    *,
    base_url: str,
    user: DesktopUser,
    client_id: int,
    limit: int = 50,
) -> dict[str, Any]:
    response = _authed_request(
        method="GET",
        base_url=base_url,
        user=user,
        path=f"matches/client/{int(client_id)}",
        params={"limit": int(limit), "threshold": 0.0},
    )
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    item = payload.get("item")
    if isinstance(item, dict):
        return {str(key): value for key, value in item.items()}
    return {str(key): value for key, value in payload.items()}


def api_client_match_total(*, base_url: str, user: DesktopUser, client_id: int) -> int:
    payload = api_fetch_client_matches(base_url=base_url, user=user, client_id=client_id)
    if "total_unique_offers" in payload:
        return int(payload.get("total_unique_offers", 0) or 0)
    demande_results = list(payload.get("demande_results", []) or [])
    total_matches = 0
    for raw_result in demande_results:
        if not isinstance(raw_result, dict):
            continue
        total_matches += int(raw_result.get("total_count", 0) or 0)
        total_matches += len(list(raw_result.get("matches", []) or []))
    return total_matches


def fetch_agency_display_name(*, agency_id: int) -> str:
    conn = admin_conn()
    try:
        row = conn.execute(
            "SELECT display_name FROM accounts_agency WHERE id = %s",
            (agency_id,),
        ).fetchone()
        return str((row or {}).get("display_name") or "")
    finally:
        conn.close()


def update_agency_display_name(*, agency_id: int, display_name: str) -> None:
    conn = admin_conn()
    try:
        conn.execute(
            "UPDATE accounts_agency SET display_name = %s WHERE id = %s",
            (display_name, agency_id),
        )
        conn.commit()
    finally:
        conn.close()


def api_fetch_agency_settings(*, base_url: str, user: DesktopUser) -> dict[str, str]:
    response = _authed_request(
        method="GET",
        base_url=base_url,
        user=user,
        path="settings/agency",
    )
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    settings = payload.get("settings")
    if not isinstance(settings, dict):
        return {}
    return {str(key): str(value) for key, value in settings.items()}


def auth_token(base_url: str, user: DesktopUser) -> str:
    response = requests.post(
        f"{normalize_base_url(base_url)}/api/auth/token/",
        json={"username": user.username, "password": user.password},
        timeout=15.0,
    )
    response.raise_for_status()
    payload = response.json()
    token = str(payload.get("access") or "")
    if not token:
        raise AssertionError("Auth response did not include an access token")
    return token


def _json_request(
    *,
    method: str,
    url: str,
    token: str,
    payload: dict[str, object] | None = None,
    timeout: float = 15.0,
    expected_code_identity: dict[str, object] | None = None,
    actual_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = requests.request(
        method=method,
        url=url,
        json=payload if payload is not None else None,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    _raise_for_backend_response(
        response,
        url=url,
        expected_code_identity=expected_code_identity,
        actual_identity=actual_identity,
    )
    value = response.json()
    return dict(value) if isinstance(value, dict) else {}


def _current_totp_code(secret: str) -> str:
    period = int(getattr(mfa_totp, "_TOTP_PERIOD_SECONDS", 30))
    counter = int(datetime.now(timezone.utc).timestamp()) // period
    return str(mfa_totp._hotp(secret, counter))


def step_up_token(*, base_url: str, user: DesktopUser) -> str:
    token = auth_token(base_url, user)
    payload = _json_request(
        method="POST",
        url=f"{normalize_base_url(base_url)}/api/auth/step-up/",
        token=token,
        payload={
            "password": user.password,
            "mfa_code": _current_totp_code(_E2E_OWNER_TOTP_SECRET),
        },
    )
    step_up = str(payload.get("step_up_token") or "").strip()
    if not step_up:
        raise AssertionError("Step-up API did not return a token")
    return step_up


def deactivate_user_via_api(
    *,
    base_url: str,
    owner: DesktopUser,
    target_user_id: int,
    step_up: str,
) -> None:
    token = auth_token(base_url, owner)
    url = f"{normalize_base_url(base_url)}/api/v1/users/{int(target_user_id)}/"
    response = requests.delete(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Immoapp-Step-Up": step_up,
        },
        timeout=15.0,
    )
    _raise_for_backend_response(response, url=url)
    if response.status_code != 204:
        raise AssertionError(f"Expected user deactivation HTTP 204, got {response.status_code}")


def publish_notification(
    *, base_url: str, user: DesktopUser, title: str, body: str
) -> dict[str, Any]:
    token = auth_token(base_url, user)
    return _json_request(
        method="POST",
        url=f"{normalize_base_url(base_url)}/api/v1/e2e/notifications/publish/",
        token=token,
        payload={"title": title, "body": body, "user_id": user.user_id},
    )


def schedule_next_import_pause(
    *, base_url: str, user: DesktopUser, seconds: float
) -> dict[str, Any]:
    token = auth_token(base_url, user)
    return _json_request(
        method="POST",
        url=f"{normalize_base_url(base_url)}/api/v1/e2e/imports/pause-next/",
        token=token,
        payload={"seconds": float(seconds)},
    )


def inject_fault(
    *,
    base_url: str,
    user: DesktopUser,
    route_template: str,
    status_code: int,
    detail: str,
    code: str,
) -> dict[str, Any]:
    token = auth_token(base_url, user)
    return _json_request(
        method="POST",
        url=f"{normalize_base_url(base_url)}/api/v1/e2e/faults/inject/",
        token=token,
        payload={
            "route_template": route_template,
            "status_code": int(status_code),
            "detail": detail,
            "code": code,
        },
    )


def revoke_other_sessions(*, base_url: str, user: DesktopUser) -> dict[str, Any]:
    token = auth_token(base_url, user)
    return _json_request(
        method="POST",
        url=f"{normalize_base_url(base_url)}/api/v1/e2e/auth/revoke-other-sessions/",
        token=token,
        payload={},
    )


def revoke_session_by_id(*, base_url: str, user: DesktopUser, session_id: str) -> dict[str, Any]:
    token = auth_token(base_url, user)
    return _json_request(
        method="POST",
        url=f"{normalize_base_url(base_url)}/api/v1/e2e/auth/revoke-session/",
        token=token,
        payload={"session_id": str(session_id)},
    )


def notification_count(*, agency_id: int, user_id: int) -> int:
    conn = admin_conn()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM notifications
            WHERE agency_id = %s AND user_id = %s
            """,
            (agency_id, user_id),
        ).fetchone()
        return int((row or {}).get("count") or 0)
    finally:
        conn.close()


def write_client_import_csv(path: Path, *, family_name: str, phone: str, remarks: str = "") -> Path:
    if str(remarks or "").strip():
        path.write_text(
            "family_name,phone,remarks\n" f"{family_name},{phone},{remarks}\n",
            encoding="utf-8",
        )
    else:
        path.write_text(
            "family_name,phone\n" f"{family_name},{phone}\n",
            encoding="utf-8",
        )
    return path


def write_requests_only_csv(path: Path) -> Path:
    path.write_text(
        "action,type,budget_min\n" "buy,apartment,1000000\n",
        encoding="utf-8",
    )
    return path
