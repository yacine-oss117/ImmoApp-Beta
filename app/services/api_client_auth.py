"""Authentication helpers for API client."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from typing import Any, TypeVar, cast
from urllib.parse import urlparse

from app.services.api_client_circuit import reset_api_circuit
from app.services.api_client_errors import ApiError
from app.services.api_client_requests import get_requests, get_session
from app.services.api_client_utils import (
    build_url,
    format_error_payload,
    get_api_timeout,
    token_is_valid,
)
from app.services.api_config import get_api_config
from app.services.offline_state import get_offline_mode

logger = logging.getLogger(__name__)

_APP_NAME = "ImmoApp"

_access_token: str | None = None
_session_username: str | None = None
_session_password: str | None = None
_token_lock = threading.Lock()
_KEYRING_TIMEOUT_SECONDS = float(os.environ.get("IMMOAPP_KEYRING_TIMEOUT_SECONDS", "2.0"))
_KEYRING_DISABLED = os.environ.get("IMMOAPP_DISABLE_KEYRING", "0").strip() in {"1", "true", "yes"}
_KEYRING_RUNTIME_DISABLED = False
_KEYRING_PROBED = False
_KEYRING_DISABLE_REASON: str | None = None
_KEYRING_DISABLE_LOGGED = False
T = TypeVar("T")


def _sync_account_scope(token: str | None) -> None:
    try:
        from app.services.offline_account_scope import sync_account_scope_from_token

        sync_account_scope_from_token(token)
    except Exception:
        logger.debug("Failed to sync offline account scope from token", exc_info=True)


def _clear_account_scope() -> None:
    try:
        from app.services.offline_account_scope import clear_persisted_account_scope

        clear_persisted_account_scope()
    except Exception:
        logger.debug("Failed to clear persisted offline account scope", exc_info=True)


def _get_keyring() -> Any:
    """Load keyring lazily to avoid import-time backend probing overhead."""
    import keyring

    return keyring


def _probe_keyring_once() -> None:
    """
    Probe the keyring backend exactly once.

    On hosts without a usable backend (common in headless/dev environments),
    disable keyring persistence early so later auth paths stay deterministic.
    """
    global _KEYRING_PROBED
    if _KEYRING_PROBED or _KEYRING_DISABLED or _KEYRING_RUNTIME_DISABLED:
        return
    _KEYRING_PROBED = True
    try:
        keyring = _get_keyring()
        backend_getter = getattr(keyring, "get_keyring", None)
        if backend_getter is None:
            return
        backend = backend_getter()
        backend_module = str(getattr(type(backend), "__module__", ""))
        backend_name = str(getattr(type(backend), "__name__", ""))
        if backend_module.startswith("keyring.backends.fail"):
            _disable_keyring_runtime(
                reason="backend_unavailable",
                op_name="probe",
                level="info",
                message=(
                    f"Keyring backend unavailable ({backend_module}.{backend_name}); "
                    "using in-memory token persistence."
                ),
            )
    except Exception as exc:
        _disable_keyring_runtime(
            reason="probe_failed",
            op_name="probe",
            level="warning",
            message="Keyring probe failed; using in-memory token persistence for this process.",
            exc_info=exc,
        )


def _disable_keyring_runtime(
    *,
    reason: str,
    op_name: str,
    level: str = "warning",
    message: str | None = None,
    exc_info: BaseException | None = None,
) -> None:
    global _KEYRING_RUNTIME_DISABLED, _KEYRING_DISABLE_REASON, _KEYRING_DISABLE_LOGGED
    _KEYRING_RUNTIME_DISABLED = True
    _KEYRING_DISABLE_REASON = reason
    if _KEYRING_DISABLE_LOGGED:
        if exc_info is not None:
            logger.debug("Keyring disable details (suppressed duplicate).", exc_info=exc_info)
        return
    _KEYRING_DISABLE_LOGGED = True
    text = message or (
        f"Keyring persistence disabled for current process ({reason}) during {op_name}. "
        "Session persistence will use in-memory tokens only."
    )
    if level == "info":
        logger.info(text)
    else:
        logger.warning(text)
    if exc_info is not None:
        logger.debug("Keyring disable details.", exc_info=exc_info)


def _is_expected_keyring_unavailable(error: object) -> bool:
    if not isinstance(error, Exception):
        return False
    module = error.__class__.__module__
    name = error.__class__.__name__
    return module.startswith("keyring.errors") and name in {"NoKeyringError", "InitError"}


def _run_keyring_call(op_name: str, callback: Callable[[Any], T], default: T) -> T:
    """
    Run a keyring operation with a defensive timeout.

    Some backends can hang when probing OS credential stores. This guard keeps
    login/token flows responsive even when keyring is unhealthy.
    """
    global _KEYRING_RUNTIME_DISABLED, _KEYRING_DISABLE_REASON
    if _KEYRING_DISABLED:
        return default
    _probe_keyring_once()
    if _KEYRING_RUNTIME_DISABLED:
        return default

    result: dict[str, Any] = {"value": default, "error": None}

    def _runner() -> None:
        try:
            keyring = _get_keyring()
            result["value"] = callback(keyring)
        except Exception as exc:
            result["error"] = exc

    worker = threading.Thread(target=_runner, name=f"keyring-{op_name}", daemon=True)
    worker.start()
    worker.join(timeout=max(0.1, _KEYRING_TIMEOUT_SECONDS))
    if worker.is_alive():
        _disable_keyring_runtime(
            reason="timeout",
            op_name=op_name,
            message=(
                f"Keyring call timed out for {op_name}; "
                "using in-memory token persistence for this process."
            ),
        )
        return default

    error = result.get("error")
    if error is not None:
        if _is_expected_keyring_unavailable(error):
            _disable_keyring_runtime(
                reason="backend_unavailable",
                op_name=op_name,
                level="info",
                message=(
                    f"Keyring backend unavailable for {op_name}; "
                    "using in-memory token persistence."
                ),
            )
            return default

        _disable_keyring_runtime(
            reason="failure",
            op_name=op_name,
            message=(
                f"Keyring call failed for {op_name}; "
                "using in-memory token persistence for this process."
            ),
            exc_info=error,
        )
        return default
    return cast(T, result["value"])


def set_session_credentials(username: str, password: str) -> None:
    """Store credentials in memory for the current session only."""
    global _session_username, _session_password
    _session_username = username
    _session_password = password


def clear_session_credentials() -> None:
    """Clear in-memory credentials."""
    global _session_username, _session_password
    _session_username = None
    _session_password = None


def set_session_access_token(token: str | None) -> None:
    """Set in-memory access token (used for offline tests)."""
    global _access_token
    with _token_lock:
        _access_token = token
    if token:
        _sync_account_scope(token)
    else:
        _clear_account_scope()


def _iter_exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        next_exc = current.__cause__ or current.__context__
        current = next_exc if isinstance(next_exc, BaseException) else None
    return chain


def _is_connection_refused_error(exc: BaseException) -> bool:
    for candidate in _iter_exception_chain(exc):
        text = str(candidate).lower()
        if isinstance(candidate, ConnectionRefusedError):
            return True
        if (
            "connection refused" in text
            or "failed to establish a new connection" in text
            or "winerror 10061" in text
        ):
            return True
    return False


def _is_local_secure_base_url() -> bool:
    base_url = str(get_api_config().base_url or "").strip()
    if not base_url:
        return False
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").strip().lower()
    return parsed.scheme == "https" and host in {"localhost", "127.0.0.1"}


def _should_remember_session() -> bool:
    return bool(get_api_config().remember_session)


def _refresh_token_key(username: str) -> str:
    return f"{username}_refresh"


def _access_token_key(username: str) -> str:
    return f"{username}_access"


def _get_refresh_token(username: str) -> str | None:
    if not username or not _should_remember_session():
        return None
    return _run_keyring_call(
        "get_refresh_token",
        lambda keyring: cast(
            str | None, keyring.get_password(_APP_NAME, _refresh_token_key(username))
        ),
        None,
    )


def _get_cached_access_token(username: str) -> str | None:
    if not username or not _should_remember_session():
        return None
    return _run_keyring_call(
        "get_access_token",
        lambda keyring: cast(
            str | None, keyring.get_password(_APP_NAME, _access_token_key(username))
        ),
        None,
    )


def _store_refresh_token(username: str, refresh: str | None) -> None:
    if not username:
        return
    if not _should_remember_session() or not refresh:
        _clear_refresh_token(username)
        return
    _run_keyring_call(
        "store_refresh_token",
        lambda keyring: keyring.set_password(_APP_NAME, _refresh_token_key(username), refresh),
        None,
    )


def _store_access_token(username: str, access: str | None) -> None:
    if not username:
        return
    if not _should_remember_session() or not access:
        _clear_access_token(username)
        return
    _run_keyring_call(
        "store_access_token",
        lambda keyring: keyring.set_password(_APP_NAME, _access_token_key(username), access),
        None,
    )


def _delete_keyring_password(keyring: Any, key: str) -> None:
    """
    Best-effort credential removal.

    Missing credentials are a normal state during logout/cleanup and should
    not be treated as a backend failure that disables keyring persistence.
    """
    try:
        keyring.delete_password(_APP_NAME, key)
    except Exception as exc:
        keyring_errors = getattr(keyring, "errors", None)
        delete_error_type = getattr(keyring_errors, "PasswordDeleteError", None)
        if delete_error_type is not None and isinstance(exc, delete_error_type):
            logger.debug("Keyring entry already absent for key '%s'.", key)
            return
        raise


def _clear_refresh_token(username: str) -> None:
    if not username:
        return
    _run_keyring_call(
        "clear_refresh_token",
        lambda keyring: _delete_keyring_password(keyring, _refresh_token_key(username)),
        None,
    )


def _clear_access_token(username: str) -> None:
    if not username:
        return
    _run_keyring_call(
        "clear_access_token",
        lambda keyring: _delete_keyring_password(keyring, _access_token_key(username)),
        None,
    )


def clear_persisted_session(username: str | None = None) -> None:
    """Clear any stored refresh token."""
    config = get_api_config()
    _clear_refresh_token(username or config.username or "")
    _clear_access_token(username or config.username or "")
    _clear_account_scope()


def _login_with_creds(username: str, password: str, *, mfa_code: str | None = None) -> str | None:
    """Authenticate with the API using credentials and return an access token."""
    if not username or not password:
        return None
    requests = get_requests()
    session = get_session()
    payload: dict[str, str] = {"username": username, "password": password}
    if mfa_code:
        payload["mfa_code"] = str(mfa_code)
    try:
        url = build_url("/api/auth/token/", prefix_api=False)
        response = session.post(
            url,
            json=payload,
            timeout=get_api_timeout(),
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"API login failed: {exc}") from exc

    if response.status_code >= 400:
        message = response.text
        try:
            message = format_error_payload(response.json(), response.text)
        except ValueError:
            pass
        raise ApiError(response.status_code, message)

    try:
        payload = response.json()
    except ValueError as exc:
        raise ApiError(502, "Invalid auth response payload.") from exc
    access = payload.get("access")
    refresh = payload.get("refresh")
    if isinstance(refresh, str):
        _store_refresh_token(username, refresh)
    reset_api_circuit()
    if isinstance(access, str):
        _sync_account_scope(access)
        return access
    return None


def _refresh_access_token(username: str) -> str | None:
    """Refresh the access token using a stored refresh token."""
    refresh = _get_refresh_token(username)
    if not refresh:
        return None
    requests = get_requests()
    session = get_session()
    try:
        url = build_url("/api/auth/token/refresh/", prefix_api=False)
        response = session.post(
            url,
            json={"refresh": refresh},
            timeout=get_api_timeout(),
        )
    except requests.RequestException as exc:
        if _is_local_secure_base_url() and _is_connection_refused_error(exc):
            logger.info(
                "Token refresh skipped because the local secure server is not running yet: %s",
                exc,
            )
            return None
        logger.warning("Token refresh failed: %s", exc)
        return None

    if response.status_code >= 400:
        if response.status_code in (400, 401, 403):
            logger.info(
                "Token refresh rejected; re-login required (status=%s).", response.status_code
            )
        else:
            logger.warning("Token refresh rejected: %s", response.text)
        return None

    try:
        payload = response.json()
    except ValueError:
        logger.warning("Token refresh returned non-JSON payload; re-login required.")
        return None
    access = payload.get("access")
    new_refresh = payload.get("refresh")
    if isinstance(new_refresh, str):
        _store_refresh_token(username, new_refresh)
    if isinstance(access, str):
        reset_api_circuit()
        _sync_account_scope(access)
        return access
    return None


def _get_token(mfa_code: str | None = None) -> str | None:
    """Get the current access token, refreshing or logging in if necessary."""
    global _access_token, _session_password
    config = get_api_config()
    if config.token:
        return config.token
    with _token_lock:
        if _access_token:
            if get_offline_mode() and not token_is_valid(_access_token):
                _access_token = None
            else:
                return _access_token

        username = _session_username or config.username
        if get_offline_mode():
            cached = _get_cached_access_token(username or "")
            if cached and token_is_valid(cached):
                _access_token = cached
                return _access_token
            return None
        if username:
            _access_token = _refresh_access_token(username)
            if _access_token:
                _store_access_token(username, _access_token)
                return _access_token

        password = _session_password or config.password
        if username and password:
            _access_token = _login_with_creds(username, password, mfa_code=mfa_code)
            if _access_token:
                _store_access_token(username, _access_token)
            return _access_token

        return None


def peek_access_token() -> str | None:
    """Return in-memory access token without refresh/login network calls."""
    with _token_lock:
        return _access_token


def get_access_token(mfa_code: str | None = None) -> str | None:
    """Return the current access token (may trigger login)."""
    return _get_token(mfa_code=mfa_code)


__all__ = [
    "get_access_token",
    "set_session_credentials",
    "clear_session_credentials",
    "clear_persisted_session",
    "set_session_access_token",
    "peek_access_token",
]
