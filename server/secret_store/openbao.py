from __future__ import annotations

import json
import logging
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class OpenBaoError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenBaoConfig:
    addrs: tuple[str, ...]
    namespace: str | None
    token: str | None
    token_file: str | None
    approle_file: str | None
    role_id: str | None
    secret_id: str | None
    timeout: float
    verify_ssl: bool


def _load_approle_credentials(path_value: str) -> tuple[str | None, str | None]:
    path = Path(path_value.strip())
    if not path.exists():
        raise OpenBaoError(f"BAO_APPROLE_FILE not found: {path}")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise OpenBaoError(f"Failed to parse BAO_APPROLE_FILE at {path}: {exc}") from exc

    role_id = str(parsed.get("app_role_id") or parsed.get("role_id") or "").strip() or None
    secret_id = str(parsed.get("app_secret_id") or parsed.get("secret_id") or "").strip() or None
    return role_id, secret_id


def _looks_like_windows_path(value: str) -> bool:
    cleaned = value.strip()
    if len(cleaned) < 3:
        return False
    return cleaned[1:3] in {":\\", ":/"}


def normalize_secret_path(path: str) -> str:
    cleaned = path.strip().strip("/")
    if not cleaned:
        raise OpenBaoError("OpenBao secret path is empty.")
    if "/data/" in cleaned or "/metadata/" in cleaned:
        return cleaned
    segments = cleaned.split("/")
    if len(segments) <= 1:
        return cleaned
    mount = segments[0]
    key = "/".join(segments[1:])
    return f"{mount}/data/{key}"


def _build_config() -> OpenBaoConfig:
    raw_addrs = os.environ.get("BAO_ADDRS", "").strip()
    if raw_addrs:
        addrs = tuple(
            addr.strip().rstrip("/") for addr in raw_addrs.split(",") if addr.strip().rstrip("/")
        )
    else:
        addrs = (os.environ.get("BAO_ADDR", "http://openbao:8200").rstrip("/"),)
    if not addrs:
        raise OpenBaoError("OpenBao address list is empty (BAO_ADDR/BAO_ADDRS).")
    namespace = os.environ.get("BAO_NAMESPACE") or None
    token_file = os.environ.get("BAO_TOKEN_FILE") or None
    token = None
    if token_file:
        token_path = token_file.strip()
        if os.name != "nt" and _looks_like_windows_path(token_path):
            raise OpenBaoError(
                "BAO_TOKEN_FILE points to a Windows host path inside non-Windows runtime: "
                f"{token_path}. Use container path via BAO_TOKEN_FILE_DOCKER."
            )
        if token_path:
            try:
                token = open(token_path, encoding="utf-8").read().strip() or None
            except OSError as exc:
                raise OpenBaoError(f"Failed to read BAO_TOKEN_FILE at {token_path}: {exc}") from exc
    if not token:
        token = os.environ.get("BAO_TOKEN") or None
    approle_file = os.environ.get("BAO_APPROLE_FILE") or None
    if approle_file and os.name != "nt" and _looks_like_windows_path(approle_file):
        raise OpenBaoError(
            "BAO_APPROLE_FILE points to a Windows host path inside non-Windows runtime: "
            f"{approle_file}. Use container path via BAO_APPROLE_FILE_DOCKER."
        )
    role_id = os.environ.get("BAO_ROLE_ID") or None
    secret_id = os.environ.get("BAO_SECRET_ID") or None
    if not (role_id and secret_id) and approle_file:
        file_role_id, file_secret_id = _load_approle_credentials(approle_file)
        role_id = role_id or file_role_id
        secret_id = secret_id or file_secret_id
    timeout = float(os.environ.get("BAO_TIMEOUT", "5"))
    requested_verify_ssl = os.environ.get("BAO_VERIFY_SSL", "1") != "0"
    verify_ssl = requested_verify_ssl and all(
        addr.strip().lower().startswith("https://") for addr in addrs
    )
    if requested_verify_ssl and not verify_ssl:
        logger.warning(
            "BAO_VERIFY_SSL=1 ignored because BAO_ADDR/BAO_ADDRS contains non-HTTPS endpoint(s). "
            "Use https:// with BAO_VERIFY_SSL=1, or set BAO_VERIFY_SSL=0 for http://."
        )
    return OpenBaoConfig(
        addrs=addrs,
        namespace=namespace,
        token=token,
        token_file=token_file,
        approle_file=approle_file,
        role_id=role_id,
        secret_id=secret_id,
        timeout=timeout,
        verify_ssl=verify_ssl,
    )


def _ssl_context(verify_ssl: bool) -> ssl.SSLContext | None:
    if verify_ssl:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float,
    verify_ssl: bool,
) -> dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if headers:
        for key, value in headers.items():
            req.add_header(key, value)
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    context = _ssl_context(verify_ssl)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = ""
        raise OpenBaoError(f"OpenBao HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OpenBaoError(f"OpenBao connection failed: {exc}") from exc
    if not body:
        return {}
    parsed = json.loads(body)
    return parsed if isinstance(parsed, dict) else {}


def _resolve_token(config: OpenBaoConfig, headers: dict[str, str]) -> str:
    if config.token:
        return config.token
    if config.role_id and config.secret_id:
        payload = {"role_id": config.role_id, "secret_id": config.secret_id}
        last_error: OpenBaoError | None = None
        for addr in config.addrs:
            login_url = f"{addr}/v1/auth/approle/login"
            try:
                data = _request_json(
                    "POST",
                    login_url,
                    headers=headers,
                    payload=payload,
                    timeout=config.timeout,
                    verify_ssl=config.verify_ssl,
                )
            except OpenBaoError as exc:
                last_error = exc
                continue
            token = (data.get("auth") or {}).get("client_token")
            if token:
                return str(token)
            last_error = OpenBaoError("OpenBao AppRole login failed (missing token).")
        if last_error is not None:
            raise last_error
    raise OpenBaoError("OpenBao token or AppRole credentials are required.")


def fetch_secret_data(path: str) -> dict[str, Any]:
    """Fetch secret payload from OpenBao (KV v1 or v2)."""
    config = _build_config()
    headers: dict[str, str] = {}
    if config.namespace:
        headers["X-Vault-Namespace"] = config.namespace
    token = _resolve_token(config, headers)
    headers["X-Vault-Token"] = token
    normalized_path = normalize_secret_path(path)

    last_error: OpenBaoError | None = None
    data: dict[str, Any] | None = None
    for addr in config.addrs:
        url = f"{addr}/v1/{normalized_path}"
        try:
            data = _request_json(
                "GET",
                url,
                headers=headers,
                timeout=config.timeout,
                verify_ssl=config.verify_ssl,
            )
            break
        except OpenBaoError as exc:
            if "OpenBao HTTP 404" in str(exc):
                last_error = OpenBaoError(
                    "OpenBao secret path not found: "
                    f"{normalized_path}. Ensure OpenBao bootstrap seeded this path (openbao-seed). "
                    f"Raw: {exc}"
                )
                continue
            last_error = exc
            continue
    if data is None:
        if last_error is not None:
            raise last_error
        raise OpenBaoError("OpenBao request failed with no response data.")
    payload = data.get("data")
    if payload is None:
        return {}
    # KV v2 nests actual data in data.data
    if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], dict):
        return payload["data"]
    if isinstance(payload, dict):
        return payload
    return {}
