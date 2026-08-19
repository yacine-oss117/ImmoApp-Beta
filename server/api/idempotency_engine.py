"""Postgres-backed idempotency engine."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import cast

import psycopg
from psycopg.types.json import Jsonb
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from core.contracts.http_policy import RoutePolicy
from core.contracts.idempotency_canonical_json import (
    canonical_body_hash,
    canonical_json_dumps,
    canonical_query_hash,
)
from core.contracts.idempotency_contract import (
    ERR_IN_PROGRESS,
    ERR_KEY_REUSE_MISMATCH,
    ERR_TAMPERED,
    ERR_UNVERIFIABLE,
    IDEMPOTENCY_HEADER,
    IDEMPOTENCY_HMAC_PAYLOAD_VERSION,
    IDEMPOTENCY_IN_PROGRESS_WAIT_SECONDS,
    IDEMPOTENCY_MAX_RESPONSE_BYTES,
    IDEMPOTENCY_RESPONSE_HEADERS_ALLOWLIST,
    IDEMPOTENCY_RETRY_AFTER_SECONDS,
    IDEMPOTENCY_TTL_SECONDS_DEFAULT,
    LEGACY_IDEMPOTENCY_HEADER,
    IdempotencyScope,
)
from core.contracts.idempotency_replay_policy import sanitize_replay_payload
from core.contracts.semantic_header_registry import normalize_semantic_headers
from server.api.route_registry import get_route_policy, resolve_route_template
from server.pg.uow import PgSession, admin_transaction, get_uow
from server.secret_store.loader import load_secrets
from server.secret_store.openbao import OpenBaoError, fetch_secret_data

logger = logging.getLogger(__name__)
_HMAC_KEYRING_REFRESH_TTL_SECONDS_DEFAULT = 60.0
_HMAC_KEYRING_CACHE_STATE: _CachedHmacKeyring | None = None


@dataclass(frozen=True)
class _CachedHmacKeyring:
    keyring: dict[str, str]
    active_key_id: str | None
    refresh_after_monotonic: float


@dataclass(frozen=True)
class _PersistedIdempotencyRecord:
    record_id: int
    created_at: datetime | None
    expires_at: datetime | None


@dataclass(frozen=True)
class IdempotencyContext:
    scope: IdempotencyScope
    canonical_body_hash: str
    normalized_query_hash: str
    semantic_headers_hash: str
    policy: RoutePolicy | None
    raw_key_header: str
    lease_owner: str
    record_id: int = 0
    created_at: datetime | None = None
    expires_at: datetime | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _extract_idempotency_header(request: Request) -> tuple[str | None, str]:
    raw = str(request.headers.get(IDEMPOTENCY_HEADER, "")).strip()
    if raw:
        return raw, IDEMPOTENCY_HEADER
    legacy = str(request.headers.get(LEGACY_IDEMPOTENCY_HEADER, "")).strip()
    if legacy:
        return legacy, LEGACY_IDEMPOTENCY_HEADER
    return None, IDEMPOTENCY_HEADER


def _effective_agency_id(request: Request) -> int:
    user = getattr(request, "user", None)
    agency_id = getattr(user, "agency_id", None)
    if isinstance(agency_id, int) and agency_id > 0:
        return agency_id
    return 0


def _normalized_route(request: Request) -> str:
    resolver = getattr(request, "resolver_match", None)
    route = str(getattr(resolver, "route", "") or "")
    path = str(getattr(request, "path", "") or "")
    return resolve_route_template(route, request_path=path)


def _query_dict(request: Request) -> dict[str, list[str]]:
    query = getattr(request, "query_params", None)
    if query is None:
        return {}
    if hasattr(query, "lists"):
        return {str(k): [str(v) for v in values] for k, values in query.lists()}
    return {str(k): [str(v)] for k, v in dict(query).items()}


def _body_hash(request: Request) -> str:
    payload = request.data if request.data is not None else {}
    return canonical_body_hash(payload)


def _semantic_headers_hash(request: Request) -> str:
    normalized = normalize_semantic_headers({str(k): str(v) for k, v in request.headers.items()})
    digest = hashlib.sha256(canonical_json_dumps(normalized).encode("utf-8")).hexdigest()
    return digest


def _secrets_backend() -> str:
    return (os.environ.get("IMMOAPP_SECRETS_BACKEND") or "openbao").strip().lower()


def _allow_env_secrets() -> bool:
    return (os.environ.get("IMMOAPP_ALLOW_ENV_SECRETS") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _idempotency_hmac_refresh_ttl_seconds() -> float:
    raw = os.environ.get(
        "IMMOAPP_IDEMPOTENCY_HMAC_REFRESH_TTL_SECONDS",
        str(_HMAC_KEYRING_REFRESH_TTL_SECONDS_DEFAULT),
    ).strip()
    try:
        ttl = float(raw)
    except ValueError:
        return _HMAC_KEYRING_REFRESH_TTL_SECONDS_DEFAULT
    return max(0.0, min(ttl, 3600.0))


def _invalidate_hmac_keyring_cache() -> None:
    """Internal process-local cache reset for tests and same-process refresh paths only."""
    global _HMAC_KEYRING_CACHE_STATE
    _HMAC_KEYRING_CACHE_STATE = None


def _parse_keyring_from_mapping(mapping: dict[str, object]) -> tuple[dict[str, str], str | None]:
    keyring: dict[str, str] = {}
    active_key_id = str(mapping.get("IMMOAPP_IDEMPOTENCY_HMAC_ACTIVE_KEY_ID") or "").strip() or None

    raw_json = str(mapping.get("IMMOAPP_IDEMPOTENCY_HMAC_KEYS_JSON") or "").strip()
    if raw_json:
        try:
            parsed = json.loads(raw_json)
        except Exception:
            logger.warning("Invalid IMMOAPP_IDEMPOTENCY_HMAC_KEYS_JSON payload", exc_info=True)
            parsed = {}
        if isinstance(parsed, dict):
            for key_id, key_value in parsed.items():
                kid = str(key_id).strip()
                secret = str(key_value).strip()
                if kid and secret:
                    keyring[kid] = secret

    raw_key = str(mapping.get("IMMOAPP_IDEMPOTENCY_HMAC_KEY") or "").strip()
    raw_key_id = str(mapping.get("IMMOAPP_IDEMPOTENCY_HMAC_KEY_ID") or "").strip() or None
    if raw_key:
        fallback_id = raw_key_id or active_key_id or "default"
        keyring[fallback_id] = raw_key
        if active_key_id is None:
            active_key_id = fallback_id

    prefix = "IMMOAPP_IDEMPOTENCY_HMAC_KEY_"
    for env_key, env_value in mapping.items():
        if not isinstance(env_key, str) or not env_key.startswith(prefix):
            continue
        if env_key in {
            "IMMOAPP_IDEMPOTENCY_HMAC_KEY_ID",
            "IMMOAPP_IDEMPOTENCY_HMAC_KEYS_JSON",
            "IMMOAPP_IDEMPOTENCY_HMAC_KEY_ACTIVE",
        }:
            continue
        suffix = env_key[len(prefix) :].strip()
        secret = str(env_value).strip()
        if suffix and secret:
            keyring[suffix] = secret
            if active_key_id is None:
                active_key_id = suffix

    return keyring, active_key_id


def _load_openbao_hmac_keyring() -> tuple[dict[str, str], str | None]:
    path = (os.environ.get("IMMOAPP_SECRETS_PATH") or "secret/data/immoapp").strip()
    try:
        secrets = fetch_secret_data(path)
    except OpenBaoError:
        logger.warning("Failed to load idempotency HMAC keyring from OpenBao", exc_info=True)
        return {}, None
    if not isinstance(secrets, dict):
        return {}, None
    return _parse_keyring_from_mapping(secrets)


def _load_idempotency_hmac_keyring() -> tuple[dict[str, str], str | None]:
    backend = _secrets_backend()
    strict_openbao = backend == "openbao" and not _allow_env_secrets()
    keyring: dict[str, str] = {}
    active_key_id: str | None = None

    if backend == "openbao":
        keyring, active_key_id = _load_openbao_hmac_keyring()
        if not keyring:
            try:
                load_secrets()
                keyring, active_key_id = _parse_keyring_from_mapping(dict(os.environ))
            except Exception:
                logger.warning(
                    "Failed to refresh idempotency HMAC keyring from OpenBao", exc_info=True
                )
                keyring, active_key_id = {}, None

    if not keyring and (backend != "openbao" or _allow_env_secrets()):
        keyring, active_key_id = _parse_keyring_from_mapping(dict(os.environ))

    if strict_openbao and not keyring:
        raise RuntimeError(
            "OpenBao-only policy active but no idempotency HMAC key was loaded from OpenBao."
        )

    if active_key_id is None and keyring:
        active_key_id = sorted(keyring.keys())[0]

    return keyring, active_key_id


def _idempotency_hmac_keyring(*, force_refresh: bool = False) -> tuple[dict[str, str], str | None]:
    """Load the cached keyring with TTL refresh and optional same-process forced reload."""
    global _HMAC_KEYRING_CACHE_STATE
    now = time.monotonic()
    if not force_refresh and _HMAC_KEYRING_CACHE_STATE is not None:
        if now < _HMAC_KEYRING_CACHE_STATE.refresh_after_monotonic:
            return (
                _HMAC_KEYRING_CACHE_STATE.keyring,
                _HMAC_KEYRING_CACHE_STATE.active_key_id,
            )
    keyring, active_key_id = _load_idempotency_hmac_keyring()
    _HMAC_KEYRING_CACHE_STATE = _CachedHmacKeyring(
        keyring=keyring,
        active_key_id=active_key_id,
        refresh_after_monotonic=now + _idempotency_hmac_refresh_ttl_seconds(),
    )
    return keyring, active_key_id


def _resolve_hmac_key(
    *,
    signature_key_id: str | None = None,
    force_refresh: bool = False,
) -> tuple[str | None, str | None]:
    keyring, active_key_id = _idempotency_hmac_keyring(force_refresh=force_refresh)
    if not keyring:
        return None, None
    if signature_key_id:
        key = keyring.get(signature_key_id)
        if key:
            return key, signature_key_id
        return None, signature_key_id
    if active_key_id and active_key_id in keyring:
        return keyring[active_key_id], active_key_id
    fallback_id = sorted(keyring.keys())[0]
    return keyring[fallback_id], fallback_id


def _compute_record_hmac(row: dict[str, object], *, key: str | None) -> str | None:
    if not key:
        return None
    payload = {
        "agency_id": row.get("agency_id"),
        "normalized_route": row.get("normalized_route"),
        "method": row.get("method"),
        "idempotency_key": row.get("idempotency_key"),
        "canonical_body_hash": row.get("canonical_body_hash"),
        "normalized_query_hash": row.get("normalized_query_hash"),
        "semantic_headers_hash": row.get("semantic_headers_hash"),
        "status_code": row.get("status_code"),
        "response_body_hash": row.get("response_body_hash"),
        "response_content_type": row.get("response_content_type"),
        "response_headers_json": row.get("response_headers_json"),
        "created_at": row.get("created_at"),
        "expires_at": row.get("expires_at"),
        "payload_version": IDEMPOTENCY_HMAC_PAYLOAD_VERSION,
    }
    msg = canonical_json_dumps(payload).encode("utf-8")
    return hmac.new(key.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _normalize_hmac_row(row: dict[str, object]) -> dict[str, object]:
    normalized = dict(row)
    for field_name in ("created_at", "expires_at"):
        value = normalized.get(field_name)
        if hasattr(value, "isoformat"):
            normalized[field_name] = value.isoformat()
    return normalized


def _coerce_int(value: object, *, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _coerce_storage_payload(
    payload: object,
) -> dict[str, object] | list[object] | str | None:
    if payload is None or isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return cast(dict[str, object], payload)
    if isinstance(payload, list):
        return cast(list[object], payload)
    if isinstance(payload, tuple):
        return list(payload)
    return {"value": str(payload)}


def _build_replay_response(row: dict[str, object], raw_key: str) -> Response:
    payload = row.get("response_body_json")
    status_code = _coerce_int(row.get("status_code"), default=status.HTTP_200_OK)
    response = Response(payload, status=status_code)
    headers = row.get("response_headers_json") or {}
    if isinstance(headers, dict):
        for name, value in headers.items():
            if str(name) in IDEMPOTENCY_RESPONSE_HEADERS_ALLOWLIST and value is not None:
                response[str(name)] = str(value)
    response[IDEMPOTENCY_HEADER] = raw_key
    response[LEGACY_IDEMPOTENCY_HEADER] = raw_key
    response["Idempotency-Status"] = "replayed"
    return response


def _mismatch_response() -> Response:
    return Response(
        {
            "code": ERR_KEY_REUSE_MISMATCH,
            "detail": "Idempotency key conflict",
        },
        status=status.HTTP_409_CONFLICT,
    )


def _in_progress_response(raw_key: str) -> Response:
    response = Response(
        {
            "code": ERR_IN_PROGRESS,
            "detail": "Idempotent request is in progress",
            "retry_after_seconds": IDEMPOTENCY_RETRY_AFTER_SECONDS,
        },
        status=status.HTTP_202_ACCEPTED,
    )
    response["Retry-After"] = str(IDEMPOTENCY_RETRY_AFTER_SECONDS)
    response[IDEMPOTENCY_HEADER] = raw_key
    response[LEGACY_IDEMPOTENCY_HEADER] = raw_key
    response["Idempotency-Status"] = "in_progress"
    return response


def _tampered_response(code: str) -> Response:
    return Response(
        {
            "code": code,
            "detail": "Idempotency record integrity check failed",
            "action": "CONTACT_SUPPORT",
            "retryable": False,
        },
        status=status.HTTP_409_CONFLICT,
    )


def _record_expiry() -> datetime:
    ttl = int(
        os.environ.get("IMMOAPP_IDEMPOTENCY_TTL_SECONDS", str(IDEMPOTENCY_TTL_SECONDS_DEFAULT))
    )
    ttl = max(60, min(ttl, 7 * 24 * 60 * 60))
    return _utc_now() + timedelta(seconds=ttl)


def _completed_replay_or_integrity_error(
    row: dict[str, object],
    *,
    raw_key: str,
) -> Response:
    payload_version = str(row.get("hmac_payload_version") or "")
    if payload_version and payload_version != IDEMPOTENCY_HMAC_PAYLOAD_VERSION:
        return _tampered_response(ERR_UNVERIFIABLE)
    signature_key_id = str(row.get("signature_key_id") or "").strip() or None
    hmac_key, _ = _resolve_hmac_key(signature_key_id=signature_key_id)
    if signature_key_id and hmac_key is None:
        # Rotation can happen between TTL refresh windows. Retry once with a forced
        # same-process reload before declaring the persisted record unverifiable.
        hmac_key, _ = _resolve_hmac_key(signature_key_id=signature_key_id, force_refresh=True)
    expected_hmac = _compute_record_hmac(_normalize_hmac_row(row), key=hmac_key)
    stored_hmac = str(row.get("record_hmac") or "")
    if stored_hmac and expected_hmac is None:
        return _tampered_response(ERR_UNVERIFIABLE)
    if expected_hmac and stored_hmac and not hmac.compare_digest(expected_hmac, stored_hmac):
        return _tampered_response(ERR_TAMPERED)
    return _build_replay_response(row, raw_key)


def _wait_for_completion(scope: IdempotencyScope, *, raw_key: str) -> Response:
    row = _fetch_record(scope, for_update=False)
    if row is None:
        return _in_progress_response(raw_key)
    state = str(row.get("state") or "in_progress")
    if state == "completed":
        return _completed_replay_or_integrity_error(dict(row), raw_key=raw_key)
    return _in_progress_response(raw_key)


def _fetch_record(
    scope: IdempotencyScope,
    *,
    for_update: bool,
) -> dict[str, object] | None:
    context = get_uow().transaction if for_update else get_uow().session
    with context() as session:
        lock_sql = " FOR UPDATE" if for_update else ""
        row = session.execute(
            f"""
            SELECT *
            FROM api_idempotency_records
            WHERE agency_id = %s
              AND normalized_route = %s
              AND method = %s
              AND idempotency_key = %s
            {lock_sql}
            """,
            (
                scope.agency_id,
                scope.normalized_route,
                scope.method,
                scope.idempotency_key,
            ),
        ).fetchone()
        return row


def _select_locked_record(
    session: PgSession,
    *,
    scope: IdempotencyScope,
) -> dict[str, object] | None:
    return session.execute(
        """
        SELECT *
        FROM api_idempotency_records
        WHERE agency_id = %s
          AND normalized_route = %s
          AND method = %s
          AND idempotency_key = %s
        FOR UPDATE
        """,
        (
            scope.agency_id,
            scope.normalized_route,
            scope.method,
            scope.idempotency_key,
        ),
    ).fetchone()


def _try_insert_in_progress_record(
    session: PgSession,
    *,
    context: IdempotencyContext,
    lease_until: datetime,
    expires_at: datetime,
) -> _PersistedIdempotencyRecord | None:
    row = session.execute(
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
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'in_progress', 1, %s, %s, %s, NOW())
        ON CONFLICT DO NOTHING
        RETURNING id, created_at, expires_at
        """,
        (
            context.scope.agency_id,
            context.scope.normalized_route,
            context.scope.method,
            context.scope.idempotency_key,
            context.canonical_body_hash,
            context.normalized_query_hash,
            context.semantic_headers_hash,
            context.lease_owner,
            lease_until,
            expires_at,
        ),
    ).fetchone()
    if row is None:
        return None
    return _PersistedIdempotencyRecord(
        record_id=_coerce_int(dict(row).get("id"), default=0),
        created_at=cast(datetime | None, dict(row).get("created_at")),
        expires_at=cast(datetime | None, dict(row).get("expires_at")),
    )


def check_idempotency(request: Request) -> tuple[IdempotencyContext | None, Response | None]:
    method = str(request.method or "GET").upper()
    normalized_route = _normalized_route(request)
    policy = get_route_policy(normalized_route)
    raw_key, header_name = _extract_idempotency_header(request)
    enforce_write_key = (os.environ.get("IMMOAPP_ENFORCE_IDEMPOTENCY_KEY_WRITE") or "").strip() in {
        "1",
        "true",
        "True",
    }
    if not raw_key:
        if (
            enforce_write_key
            and policy is not None
            and policy.retry_class == "IDEMPOTENCY_KEY_WRITE"
            and method in {"POST", "PUT", "PATCH", "DELETE"}
        ):
            return None, Response(
                {
                    "code": "IDEMPOTENCY_KEY_REQUIRED",
                    "detail": "Idempotency-Key is required for this write endpoint",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return None, None
    if len(raw_key) > 255:
        return None, Response(
            {"detail": "Idempotency-Key is too long"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    scope = IdempotencyScope(
        agency_id=_effective_agency_id(request),
        normalized_route=normalized_route,
        method=method,
        idempotency_key=raw_key,
    )
    body_hash = _body_hash(request)
    query_hash = canonical_query_hash(_query_dict(request))
    semantic_hash = _semantic_headers_hash(request)
    lease_owner = str(request.headers.get("X-Request-Id", "") or f"req-{uuid.uuid4()}")
    context = IdempotencyContext(
        scope=scope,
        canonical_body_hash=body_hash,
        normalized_query_hash=query_hash,
        semantic_headers_hash=semantic_hash,
        policy=policy,
        raw_key_header=header_name,
        lease_owner=lease_owner,
    )

    now = _utc_now()
    lease_until = now + timedelta(seconds=IDEMPOTENCY_IN_PROGRESS_WAIT_SECONDS)
    expires_at = _record_expiry()
    try:
        with get_uow().transaction() as session:
            session.execute("SET LOCAL lock_timeout = '250ms'")
            inserted = _try_insert_in_progress_record(
                session,
                context=context,
                lease_until=lease_until,
                expires_at=expires_at,
            )
            if inserted is not None:
                return (
                    replace(
                        context,
                        record_id=inserted.record_id,
                        created_at=inserted.created_at,
                        expires_at=inserted.expires_at,
                    ),
                    None,
                )

            row = _select_locked_record(session, scope=scope)
            if row is None:
                inserted = _try_insert_in_progress_record(
                    session,
                    context=context,
                    lease_until=lease_until,
                    expires_at=expires_at,
                )
                if inserted is not None:
                    return (
                        replace(
                            context,
                            record_id=inserted.record_id,
                            created_at=inserted.created_at,
                            expires_at=inserted.expires_at,
                        ),
                        None,
                    )
            if row is None:
                return None, _in_progress_response(raw_key)

            if (
                str(row.get("canonical_body_hash", "")) != body_hash
                or str(row.get("normalized_query_hash", "")) != query_hash
                or str(row.get("semantic_headers_hash", "")) != semantic_hash
            ):
                return None, _mismatch_response()

            state = str(row.get("state") or "in_progress")
            if state == "completed":
                return None, _completed_replay_or_integrity_error(dict(row), raw_key=raw_key)

            active_lease_until = row.get("lease_until")
            if isinstance(active_lease_until, datetime) and active_lease_until > now:
                return None, _wait_for_completion(scope, raw_key=raw_key)

            session.execute(
                """
                UPDATE api_idempotency_records
                SET state = 'in_progress',
                    attempt = COALESCE(attempt, 0) + 1,
                    lease_owner = %s,
                    lease_until = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (lease_owner, lease_until, _coerce_int(row.get("id"), default=0)),
            )
            return (
                replace(
                    context,
                    record_id=_coerce_int(row.get("id"), default=0),
                    created_at=cast(datetime | None, row.get("created_at")),
                    expires_at=cast(datetime | None, row.get("expires_at")),
                ),
                None,
            )

    except psycopg.Error as exc:
        if getattr(exc, "sqlstate", None) == "42P01":
            logger.exception("api_idempotency_records is missing; run Alembic migrations")
        raise
    return context, None


def _extract_replay_headers(response: Response) -> dict[str, str]:
    headers: dict[str, str] = {}
    for header in IDEMPOTENCY_RESPONSE_HEADERS_ALLOWLIST:
        value = response.headers.get(header)
        if value is None:
            continue
        headers[header] = str(value)
    return headers


def _response_payload_for_storage(
    payload: object,
) -> tuple[dict[str, object] | list[object] | str | None, str]:
    normalized_payload = _coerce_storage_payload(payload)
    try:
        dumped = canonical_json_dumps(normalized_payload)
    except Exception:
        dumped = canonical_json_dumps({"value": str(payload)})
        normalized_payload = {"value": str(payload)}
    if len(dumped.encode("utf-8")) > IDEMPOTENCY_MAX_RESPONSE_BYTES:
        normalized_payload = {"detail": "response_omitted_due_to_size_cap"}
        dumped = canonical_json_dumps(normalized_payload)
    return normalized_payload, dumped


def store_idempotency(
    context: IdempotencyContext | None,
    response: Response,
    request: Request,
) -> Response:
    if context is None:
        return response
    _ = request

    status_code = int(response.status_code)
    if status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
        with get_uow().transaction() as session:
            session.execute(
                """
                DELETE FROM api_idempotency_records
                WHERE agency_id = %s
                  AND normalized_route = %s
                  AND method = %s
                  AND idempotency_key = %s
                """,
                (
                    context.scope.agency_id,
                    context.scope.normalized_route,
                    context.scope.method,
                    context.scope.idempotency_key,
                ),
            )
        response[IDEMPOTENCY_HEADER] = context.scope.idempotency_key
        response[LEGACY_IDEMPOTENCY_HEADER] = context.scope.idempotency_key
        response["Idempotency-Status"] = "skipped_auth_state"
        return response

    replay_mode = context.policy.replay_mode if context.policy is not None else "NONE"
    policy_id = context.policy.policy_id if context.policy is not None else ""
    replay_payload = sanitize_replay_payload(
        response.data,
        policy_id=policy_id,
        replay_mode=replay_mode,
    )
    payload, dumped_payload = _response_payload_for_storage(replay_payload)
    response_headers = _extract_replay_headers(response)
    state = "failed_transient" if status_code >= 500 else "completed"
    response_content_type = str(response.headers.get("Content-Type") or "application/json")
    response_body_hash = hashlib.sha256(dumped_payload.encode("utf-8")).hexdigest()
    if context.record_id <= 0 or context.created_at is None or context.expires_at is None:
        raise RuntimeError("Idempotency context is missing persisted row metadata.")
    active_hmac_key, active_key_id = _resolve_hmac_key()
    sign_row = _normalize_hmac_row(
        {
            "agency_id": context.scope.agency_id,
            "normalized_route": context.scope.normalized_route,
            "method": context.scope.method,
            "idempotency_key": context.scope.idempotency_key,
            "canonical_body_hash": context.canonical_body_hash,
            "normalized_query_hash": context.normalized_query_hash,
            "semantic_headers_hash": context.semantic_headers_hash,
            "status_code": status_code,
            "response_body_hash": response_body_hash,
            "response_content_type": response_content_type,
            "response_headers_json": response_headers,
            "created_at": context.created_at,
            "expires_at": context.expires_at,
        }
    )
    record_hmac = _compute_record_hmac(sign_row, key=active_hmac_key)

    try:
        with get_uow().transaction() as session:
            session.execute(
                """
                UPDATE api_idempotency_records
                SET state = %s,
                    status_code = %s,
                    response_content_type = %s,
                    response_headers_json = %s,
                    response_body_json = %s,
                    response_body_hash = %s,
                    response_size_bytes = %s,
                    record_hmac = %s,
                    signature_key_id = %s,
                    hmac_payload_version = %s,
                    lease_until = NULL,
                    updated_at = NOW()
                WHERE id = %s
                  AND agency_id = %s
                  AND normalized_route = %s
                  AND method = %s
                  AND idempotency_key = %s
                """,
                (
                    state,
                    status_code,
                    response_content_type,
                    Jsonb(response_headers),
                    Jsonb(payload),
                    response_body_hash,
                    len(dumped_payload.encode("utf-8")),
                    record_hmac,
                    active_key_id if record_hmac else None,
                    IDEMPOTENCY_HMAC_PAYLOAD_VERSION if record_hmac else None,
                    context.record_id,
                    context.scope.agency_id,
                    context.scope.normalized_route,
                    context.scope.method,
                    context.scope.idempotency_key,
                ),
            )
    except psycopg.Error as exc:
        if getattr(exc, "sqlstate", None) == "42P01":
            logger.exception("api_idempotency_records is missing; run Alembic migrations")
        raise

    response[IDEMPOTENCY_HEADER] = context.scope.idempotency_key
    response[LEGACY_IDEMPOTENCY_HEADER] = context.scope.idempotency_key
    response["Idempotency-Status"] = "created"
    if context.raw_key_header == LEGACY_IDEMPOTENCY_HEADER:
        response["Deprecation"] = "true"
    if state == "failed_transient":
        response["Retry-After"] = str(IDEMPOTENCY_RETRY_AFTER_SECONDS)
    return response


def purge_expired_idempotency_records(*, limit: int = 2000) -> int:
    # Maintenance purge runs outside tenant request scope; use admin transaction
    # so it does not depend on ambient tenant contextvars.
    with admin_transaction() as session:
        row = session.execute(
            """
            WITH doomed AS (
                SELECT id
                FROM api_idempotency_records
                WHERE expires_at < NOW()
                  AND state <> 'in_progress'
                ORDER BY expires_at
                LIMIT %s
            )
            DELETE FROM api_idempotency_records
            WHERE id IN (SELECT id FROM doomed)
            RETURNING id
            """,
            (int(limit),),
        ).fetchall()
    return len(row)


__all__ = [
    "IdempotencyContext",
    "check_idempotency",
    "purge_expired_idempotency_records",
    "store_idempotency",
]
