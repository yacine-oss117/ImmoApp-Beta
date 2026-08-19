from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from server.secret_store.required_keys import DEFAULT_OPENBAO_REQUIRED_KEYS


class RuntimeGuardError(RuntimeError):
    pass


def _info(message: str) -> None:
    print(f"openbao_runtime_guard: INFO: {message}")


def _warn(message: str) -> None:
    print(f"openbao_runtime_guard: WARNING: {message}", file=sys.stderr)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default))


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


def _looks_like_windows_path(value: str) -> bool:
    cleaned = value.strip()
    return len(cleaned) > 2 and cleaned[1:3] in {":\\", ":/"}


def _ssl_context(verify_ssl: bool) -> ssl.SSLContext | None:
    if verify_ssl:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    timeout: float,
    verify_ssl: bool,
    allow_status: set[int] | None = None,
) -> dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    for key, value in headers.items():
        req.add_header(key, value)
    if payload is not None:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context(verify_ssl)) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            if not raw.strip():
                return {}
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            return {"raw": parsed}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        if allow_status and exc.code in allow_status:
            return {"_status": exc.code, "_body": body}
        raise RuntimeGuardError(f"OpenBao HTTP {exc.code} on {method} {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeGuardError(f"OpenBao connection failure for {url}: {exc}") from exc


def _required_keys() -> list[str]:
    raw = _env("IMMOAPP_SECRETS_REQUIRED_KEYS", "").strip()
    if raw:
        configured = [item.strip() for item in raw.split(",") if item.strip()]
        return list(dict.fromkeys([*configured, "IMMOAPP_IDEMPOTENCY_HMAC_KEY"]))
    return list(DEFAULT_OPENBAO_REQUIRED_KEYS)


def _has_master_key(data: dict[str, str]) -> bool:
    if data.get("ALE_MASTER_KEY"):
        return True
    for key, value in data.items():
        if key.startswith("ALE_MASTER_KEY_V") and value:
            return True
    return False


def _validate_required(data: dict[str, str], required: list[str]) -> list[str]:
    missing: list[str] = []
    for key in required:
        if key == "ALE_MASTER_KEY":
            if not _has_master_key(data):
                missing.append("ALE_MASTER_KEY*")
            continue
        if key.endswith("*"):
            prefix = key[:-1]
            if not any(item.startswith(prefix) and data.get(item) for item in data):
                missing.append(key)
            continue
        if not data.get(key):
            missing.append(key)
    return missing


def _token_from_file(path: Path) -> str:
    if not path.exists():
        raise RuntimeGuardError(f"BAO_TOKEN_FILE not found: {path}")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeGuardError(f"BAO_TOKEN_FILE is empty: {path}")
    return token


def _token_from_approle(
    *,
    addr: str,
    timeout: float,
    verify_ssl: bool,
    role_id: str,
    secret_id: str,
) -> str:
    login = _request_json(
        "PUT",
        f"{addr}/v1/auth/approle/login",
        headers={},
        payload={"role_id": role_id, "secret_id": secret_id},
        timeout=timeout,
        verify_ssl=verify_ssl,
    )
    token = str(((login.get("auth") or {}).get("client_token")) or "").strip()
    if not token:
        raise RuntimeGuardError("AppRole login returned no client token.")
    return token


def _resolve_token(addr: str, timeout: float, verify_ssl: bool) -> str:
    token = _env("BAO_TOKEN", "").strip()
    if token:
        return token

    token_file = _env("BAO_TOKEN_FILE", "").strip()
    if token_file:
        path = Path(token_file)
        if os.name != "nt" and _looks_like_windows_path(str(path)):
            raise RuntimeGuardError(f"BAO_TOKEN_FILE must be container path: {path}")
        return _token_from_file(path)

    approle_file = _env("BAO_APPROLE_FILE", "").strip()
    if approle_file:
        path = Path(approle_file)
        if os.name != "nt" and _looks_like_windows_path(str(path)):
            raise RuntimeGuardError(f"BAO_APPROLE_FILE must be container path: {path}")
        if not path.exists():
            raise RuntimeGuardError(f"BAO_APPROLE_FILE not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        role_id = str(payload.get("app_role_id") or "").strip()
        secret_id = str(payload.get("app_secret_id") or "").strip()
        if not role_id or not secret_id:
            raise RuntimeGuardError(
                f"BAO_APPROLE_FILE is missing app_role_id/app_secret_id: {path}"
            )
        return _token_from_approle(
            addr=addr,
            timeout=timeout,
            verify_ssl=verify_ssl,
            role_id=role_id,
            secret_id=secret_id,
        )

    role_id = _env("BAO_ROLE_ID", "").strip()
    secret_id = _env("BAO_SECRET_ID", "").strip()
    if role_id and secret_id:
        return _token_from_approle(
            addr=addr,
            timeout=timeout,
            verify_ssl=verify_ssl,
            role_id=role_id,
            secret_id=secret_id,
        )

    raise RuntimeGuardError(
        "No OpenBao auth configured for runtime guard. "
        "Expected one of BAO_TOKEN, BAO_TOKEN_FILE, BAO_APPROLE_FILE, or BAO_ROLE_ID+BAO_SECRET_ID."
    )


def main() -> None:
    addr = _env("BAO_ADDR", "http://openbao:8200").strip().rstrip("/")
    if not addr:
        raise RuntimeGuardError("BAO_ADDR is empty.")
    secret_path = _env("IMMOAPP_SECRETS_PATH", "secret/data/immoapp/dev").strip().lstrip("/")
    if not secret_path:
        raise RuntimeGuardError("IMMOAPP_SECRETS_PATH is empty.")

    requested_verify_ssl = _truthy(_env("BAO_VERIFY_SSL", "1"))
    verify_ssl = requested_verify_ssl
    if addr.lower().startswith("http://"):
        verify_ssl = False
        if requested_verify_ssl:
            _info("BAO_ADDR uses HTTP; TLS verification disabled for this runtime.")
    elif not verify_ssl:
        _info("BAO_VERIFY_SSL=0; TLS verification disabled for OpenBao runtime.")
    timeout = float(_env("BAO_TIMEOUT", "5"))

    token = _resolve_token(addr, timeout, verify_ssl)
    headers = {"X-Vault-Token": token}
    namespace = _env("BAO_NAMESPACE", "").strip()
    if namespace:
        headers["X-Vault-Namespace"] = namespace

    read = _request_json(
        "GET",
        f"{addr}/v1/{secret_path}",
        headers=headers,
        timeout=timeout,
        verify_ssl=verify_ssl,
        allow_status={404},
    )
    if int(read.get("_status", 200)) == 404:
        raise RuntimeGuardError(
            "OpenBao secret path not found: "
            f"{secret_path}. Run init/seed pipeline before starting app services."
        )

    data_obj = read.get("data")
    if isinstance(data_obj, dict) and isinstance(data_obj.get("data"), dict):
        loaded = {str(k): str(v) for k, v in data_obj["data"].items() if v is not None}
    elif isinstance(data_obj, dict):
        loaded = {str(k): str(v) for k, v in data_obj.items() if v is not None}
    else:
        loaded = {}

    missing = _validate_required(loaded, _required_keys())
    if missing:
        raise RuntimeGuardError(
            "OpenBao secret path is present but missing required keys: " + ", ".join(missing)
        )

    print(f"openbao_runtime_guard: OK path={secret_path} keys={len(loaded)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - runtime guard
        print(f"openbao_runtime_guard: ERROR: {exc}", file=sys.stderr)
        raise
