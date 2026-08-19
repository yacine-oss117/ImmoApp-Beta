"""HTTP client for the ImmoApp REST API with token-based authentication."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from app.services.api_config import get_api_base_url, get_api_config
from app.services.offline_state import get_offline_mode

from . import api_client_auth as _auth
from .api_client_auth import (
    _get_token,
    clear_persisted_session,
    clear_session_credentials,
    get_access_token,
    peek_access_token,
    set_session_access_token,
    set_session_credentials,
)
from .api_client_circuit import (
    _RETRY_ATTEMPTS,
    circuit_check,
    get_api_circuit_snapshot,
    record_api_failure,
    record_api_success,
    retry_backoff,
    should_retry_status,
    should_trip_circuit,
)
from .api_client_errors import ApiError
from .api_client_requests import close_session, get_requests, get_session
from .api_client_utils import (
    JsonValue,
    as_dict,
    as_dict_list,
    build_url,
    compact_error_text,
    format_error_payload,
    get_api_timeout,
)
from .api_types import RequestFiles, RequestParams
from .api_write_queue import (
    enqueue_api_mutation,
    pending_api_mutation_count,
)
from .offline_account_scope import OfflineAccountScope, get_active_account_scope

logger = logging.getLogger(__name__)

# Keep private monkeypatch targets stable for offline auth tests.
_refresh_access_token = _auth._refresh_access_token
_login_with_creds = _auth._login_with_creds


@dataclass(frozen=True)
class MutationDispatchResult:
    """Result of a resilient mutation dispatch attempt."""

    payload: JsonValue | None
    queued: bool
    queue_id: str | None = None


def _parse_error_response(response: object) -> tuple[str, str | None, object | None]:
    text = str(getattr(response, "text", "") or "")
    message = compact_error_text(text)
    payload: object | None = None
    code: str | None = None
    json_loader = getattr(response, "json", None)
    if not callable(json_loader):
        return message, code, payload
    try:
        payload = json_loader()
    except ValueError:
        return message, code, payload
    message = format_error_payload(payload, text)
    if isinstance(payload, dict):
        raw_code = payload.get("code")
        if isinstance(raw_code, str) and raw_code.strip():
            code = raw_code.strip()
    return message, code, payload


def api_enabled() -> bool:
    """Check if the API client is configured and ready to use."""
    return get_api_base_url() is not None


def reset_api_session() -> None:
    """Clear cached session/token (call after credentials change)."""
    set_session_access_token(None)
    close_session()


def _build_request_headers(headers: Mapping[str, str] | None = None) -> dict[str, str]:
    request_headers: dict[str, str] = {"Accept": "application/json"}
    token = _get_token()
    config = get_api_config()
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    if config.schema:
        request_headers["X-Immoapp-Schema"] = config.schema
    if headers:
        request_headers.update({str(k): str(v) for k, v in headers.items()})
    return request_headers


def _send_request(
    method: str,
    path: str,
    *,
    params: RequestParams | None = None,
    json_body: Mapping[str, object] | None = None,
    files: RequestFiles | None = None,
    prefix_api: bool = True,
    headers: Mapping[str, str] | None = None,
    enforce_offline_guard: bool = True,
    timeout: float | None = None,
) -> JsonValue | None:
    """Send an authenticated HTTP request to the API."""
    if enforce_offline_guard and get_offline_mode():
        raise RuntimeError("Offline mode enabled: API requests are disabled.")
    url = build_url(path, prefix_api=prefix_api)
    request_headers = _build_request_headers(headers=headers)
    requests = get_requests()
    session = get_session()

    circuit_check()
    response = None
    request_timeout = float(timeout) if timeout is not None else get_api_timeout()
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            response = session.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                files=files,
                headers=request_headers,
                timeout=request_timeout,
            )
        except requests.RequestException as exc:
            record_api_failure()
            if attempt >= _RETRY_ATTEMPTS:
                raise RuntimeError(f"API request failed: {exc}") from exc
            retry_backoff(attempt)
            continue

        if response.status_code == 401 and get_api_config().username:
            # Retry once after re-auth.
            set_session_access_token(None)
            token = _get_token()
            if not token:
                message, code, payload = _parse_error_response(response)
                raise ApiError(401, message, code=code, payload=payload)
            request_headers["Authorization"] = f"Bearer {token}"
            response = session.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                files=files,
                headers=request_headers,
                timeout=request_timeout,
            )

        message, code, payload = _parse_error_response(response)
        if response.status_code >= 400 and should_retry_status(response.status_code):
            if should_trip_circuit(response.status_code, payload):
                record_api_failure()
            if attempt >= _RETRY_ATTEMPTS:
                break
            retry_backoff(attempt)
            continue

        if response.status_code >= 400:
            raise ApiError(response.status_code, message, code=code, payload=payload)

        record_api_success()
        break

    if response is None:
        raise RuntimeError("API request failed: no response")
    if response.status_code >= 400:
        message, code, payload = _parse_error_response(response)
        raise ApiError(response.status_code, message, code=code, payload=payload)

    if not response.text:
        return None
    try:
        payload = response.json()
    except ValueError:
        return cast(JsonValue, response.text)
    return cast(JsonValue, payload)


def _request(
    method: str,
    path: str,
    *,
    params: RequestParams | None = None,
    json_body: Mapping[str, object] | None = None,
    files: RequestFiles | None = None,
    prefix_api: bool = True,
    headers: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> JsonValue | None:
    """Make an authenticated HTTP request to the API."""
    return _send_request(
        method,
        path,
        params=params,
        json_body=json_body,
        files=files,
        prefix_api=prefix_api,
        headers=headers,
        enforce_offline_guard=True,
        timeout=timeout,
    )


def _should_queue_mutation_error(exc: Exception) -> bool:
    if isinstance(exc, ApiError):
        return should_retry_status(exc.status_code)
    return isinstance(exc, RuntimeError)


def _resilient_mutation(
    method: str,
    path: str,
    *,
    payload: Mapping[str, object] | None = None,
    params: RequestParams | None = None,
    headers: Mapping[str, str] | None = None,
    dedupe_key: str,
    label: str,
) -> MutationDispatchResult:
    try:
        response = _send_request(
            method,
            path,
            params=params,
            json_body=payload,
            headers=headers,
            enforce_offline_guard=True,
        )
    except Exception as exc:
        if not _should_queue_mutation_error(exc):
            raise
        queue_id = enqueue_api_mutation(
            method,
            path,
            json_body=dict(payload or {}),
            params=dict(params or {}),
            headers={str(k): str(v) for k, v in (headers or {}).items()},
            dedupe_key=dedupe_key,
            label=label,
        )
        logger.info("Queued API mutation %s %s (%s)", method, path, label)
        return MutationDispatchResult(payload=None, queued=True, queue_id=queue_id)
    return MutationDispatchResult(payload=response, queued=False, queue_id=None)


def api_get(
    path: str,
    params: RequestParams | None = None,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> JsonValue | None:
    """Make a GET request to the API."""
    return _request("GET", path, params=params, headers=headers, timeout=timeout)


def api_post(
    path: str,
    payload: Mapping[str, object] | None = None,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> JsonValue | None:
    """Make a POST request to the API with a JSON payload."""
    return _request("POST", path, json_body=payload or {}, headers=headers, timeout=timeout)


def api_post_resilient(
    path: str,
    payload: Mapping[str, object] | None = None,
    *,
    headers: Mapping[str, str] | None = None,
    dedupe_key: str,
    label: str,
) -> MutationDispatchResult:
    """POST a retryable mutation and queue it on transient connectivity failure."""
    return _resilient_mutation(
        "POST",
        path,
        payload=payload or {},
        headers=headers,
        dedupe_key=dedupe_key,
        label=label,
    )


def api_put(
    path: str,
    payload: Mapping[str, object] | None = None,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> JsonValue | None:
    """Make a PUT request to the API with a JSON payload."""
    return _request("PUT", path, json_body=payload or {}, headers=headers, timeout=timeout)


def api_put_resilient(
    path: str,
    payload: Mapping[str, object] | None = None,
    *,
    headers: Mapping[str, str] | None = None,
    dedupe_key: str,
    label: str,
) -> MutationDispatchResult:
    """PUT a retryable mutation and queue it on transient connectivity failure."""
    return _resilient_mutation(
        "PUT",
        path,
        payload=payload or {},
        headers=headers,
        dedupe_key=dedupe_key,
        label=label,
    )


def api_delete(
    path: str,
    params: RequestParams | None = None,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> JsonValue | None:
    """Make a DELETE request to the API."""
    return _request("DELETE", path, params=params, headers=headers, timeout=timeout)


def api_delete_resilient(
    path: str,
    params: RequestParams | None = None,
    *,
    headers: Mapping[str, str] | None = None,
    dedupe_key: str,
    label: str,
) -> MutationDispatchResult:
    """DELETE a retryable mutation and queue it on transient connectivity failure."""
    return _resilient_mutation(
        "DELETE",
        path,
        params=params,
        headers=headers,
        dedupe_key=dedupe_key,
        label=label,
    )


def api_upload(
    path: str, files: RequestFiles, payload: RequestParams | None = None
) -> JsonValue | None:
    """Make a POST request with file uploads."""
    return _request("POST", path, files=files, params=payload)


def flush_pending_api_mutations(
    limit: int = 50, *, scope: OfflineAccountScope | None = None
) -> dict[str, int]:
    """Replay queued API mutations in order until connectivity degrades again."""
    resolved_scope = scope or get_active_account_scope()
    if get_offline_mode():
        return {
            "flushed": 0,
            "pending": pending_api_mutation_count(scope=resolved_scope),
            "discarded": 0,
            "failed_permanent": 0,
        }
    if resolved_scope is None:
        return {"flushed": 0, "pending": 0, "discarded": 0, "failed_permanent": 0}
    from .offline_reconciler import replay_offline_operations

    return replay_offline_operations(limit, scope=resolved_scope)


__all__ = [
    "ApiError",
    "JsonValue",
    "RequestParams",
    "RequestFiles",
    "api_enabled",
    "get_access_token",
    "peek_access_token",
    "set_session_credentials",
    "clear_session_credentials",
    "clear_persisted_session",
    "set_session_access_token",
    "reset_api_session",
    "api_get",
    "api_post",
    "api_post_resilient",
    "api_put",
    "api_put_resilient",
    "api_delete",
    "api_delete_resilient",
    "api_upload",
    "MutationDispatchResult",
    "flush_pending_api_mutations",
    "get_api_circuit_snapshot",
    "as_dict",
    "as_dict_list",
]
