from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from server.secret_store.json_types import (
    JsonObject,
    JsonValue,
    normalize_json_object,
    normalize_json_value,
)


class InitError(RuntimeError):
    pass


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default))


def _ssl_context(verify_ssl: bool) -> ssl.SSLContext | None:
    if verify_ssl:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _looks_like_windows_path(value: str) -> bool:
    cleaned = value.strip()
    return len(cleaned) > 2 and cleaned[1:3] in {":\\", ":/"}


def _safe_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.strip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except Exception:
        pass


def _safe_read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    payload: JsonObject | None = None,
    timeout: float,
    verify_ssl: bool,
    allow_status: set[int] | None = None,
) -> JsonObject:
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
            body = resp.read().decode("utf-8", errors="ignore")
            if not body.strip():
                return {}
            parsed_body = json.loads(body)
            if isinstance(parsed_body, dict):
                return normalize_json_object(parsed_body)
            return {"raw": normalize_json_value(parsed_body)}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        if allow_status and exc.code in allow_status:
            parsed_response: JsonObject = {}
            if body.strip():
                try:
                    raw = json.loads(body)
                    if isinstance(raw, dict):
                        parsed_response = normalize_json_object(raw)
                except Exception:
                    parsed_response = {"raw_body": body}
            parsed_response["_status"] = exc.code
            return parsed_response
        raise InitError(f"OpenBao HTTP {exc.code} on {method} {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise InitError(f"OpenBao connection failed for {url}: {exc}") from exc


def _wait_for_api(addr: str, timeout: float, verify_ssl: bool, max_attempts: int = 60) -> None:
    url = f"{addr}/v1/sys/health"
    for _ in range(max_attempts):
        try:
            _request_json(
                "GET",
                url,
                headers={},
                timeout=timeout,
                verify_ssl=verify_ssl,
                allow_status={200, 429, 472, 473, 501, 503},
            )
            return
        except InitError:
            time.sleep(1.0)
    raise InitError(f"OpenBao API did not become reachable: {url}")


def _get_init_status(addr: str, timeout: float, verify_ssl: bool) -> bool:
    data = _request_json(
        "GET",
        f"{addr}/v1/sys/init",
        headers={},
        timeout=timeout,
        verify_ssl=verify_ssl,
    )
    return bool(data.get("initialized"))


def _get_sealed(addr: str, timeout: float, verify_ssl: bool) -> bool:
    data = _request_json(
        "GET",
        f"{addr}/v1/sys/seal-status",
        headers={},
        timeout=timeout,
        verify_ssl=verify_ssl,
    )
    return bool(data.get("sealed"))


def _initialize_openbao(addr: str, timeout: float, verify_ssl: bool) -> tuple[str, str]:
    data = _request_json(
        "PUT",
        f"{addr}/v1/sys/init",
        headers={},
        payload={"secret_shares": 1, "secret_threshold": 1},
        timeout=timeout,
        verify_ssl=verify_ssl,
    )
    root_token = str(data.get("root_token") or "").strip()
    keys_value = data.get("keys_base64") or data.get("keys") or []
    keys: list[JsonValue] = keys_value if isinstance(keys_value, list) else []
    unseal_key = str(keys[0] if keys else "").strip()
    if not root_token:
        raise InitError("OpenBao init did not return root_token.")
    if not unseal_key:
        raise InitError("OpenBao init did not return unseal key.")
    return root_token, unseal_key


def _unseal_openbao(addr: str, timeout: float, verify_ssl: bool, unseal_key: str) -> None:
    _request_json(
        "PUT",
        f"{addr}/v1/sys/unseal",
        headers={},
        payload={"key": unseal_key},
        timeout=timeout,
        verify_ssl=verify_ssl,
    )
    if _get_sealed(addr, timeout, verify_ssl):
        raise InitError("OpenBao remains sealed after unseal attempt.")


def _validate_admin_token(addr: str, timeout: float, verify_ssl: bool, token: str) -> None:
    _request_json(
        "GET",
        f"{addr}/v1/sys/auth",
        headers={"X-Vault-Token": token},
        timeout=timeout,
        verify_ssl=verify_ssl,
    )


def main() -> None:
    addr = _env("BAO_ADDR", "http://openbao:8200").strip().rstrip("/")
    if not addr:
        raise InitError("BAO_ADDR is empty.")
    verify_ssl = _truthy(_env("BAO_VERIFY_SSL", "0"))
    if addr.lower().startswith("http://"):
        verify_ssl = False
    timeout = float(_env("BAO_TIMEOUT", "8"))

    token_file = Path(
        _env("BAO_BOOTSTRAP_TOKEN_FILE", "/run/immoapp-secrets/openbao.token").strip()
    )
    unseal_file = Path(_env("BAO_UNSEAL_KEY_FILE", "/run/immoapp-secrets/openbao.unseal").strip())
    bootstrap_token = _env("BAO_BOOTSTRAP_ADMIN_TOKEN", "").strip()

    if os.name != "nt":
        if _looks_like_windows_path(str(token_file)):
            raise InitError(f"BAO_BOOTSTRAP_TOKEN_FILE must be a container path: {token_file}")
        if _looks_like_windows_path(str(unseal_file)):
            raise InitError(f"BAO_UNSEAL_KEY_FILE must be a container path: {unseal_file}")

    _wait_for_api(addr, timeout, verify_ssl)
    initialized = _get_init_status(addr, timeout, verify_ssl)

    if not initialized:
        root_token, unseal_key = _initialize_openbao(addr, timeout, verify_ssl)
        _safe_write(token_file, root_token)
        _safe_write(unseal_file, unseal_key)
    else:
        root_token = _safe_read(token_file) or bootstrap_token
        if not root_token:
            raise InitError(
                "OpenBao already initialized but admin token file is missing/empty "
                "and BAO_BOOTSTRAP_ADMIN_TOKEN is not set."
            )
        if not token_file.exists():
            _safe_write(token_file, root_token)

    if _get_sealed(addr, timeout, verify_ssl):
        unseal_key = _safe_read(unseal_file)
        if not unseal_key:
            raise InitError(
                "OpenBao is sealed but unseal key file is missing/empty: " f"{unseal_file}"
            )
        _unseal_openbao(addr, timeout, verify_ssl, unseal_key)

    _validate_admin_token(addr, timeout, verify_ssl, root_token)
    print(f"openbao_runtime_init: ready addr={addr} token_file={token_file} sealed=false")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - operational script
        print(f"openbao_runtime_init: ERROR: {exc}", file=sys.stderr)
        raise
