from __future__ import annotations

import json
import os
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from server.secret_store.json_types import JsonObject, normalize_json_object, normalize_json_value
from server.secret_store.required_keys import DEFAULT_OPENBAO_REQUIRED_KEYS


class SeedError(RuntimeError):
    pass


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


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
    payload: JsonObject | None = None,
    timeout: float,
    verify_ssl: bool,
    retries: int = 8,
    retry_delay: float = 1.5,
) -> JsonObject:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=data, method=method)
    for key, value in headers.items():
        req.add_header(key, value)
    if payload is not None:
        req.add_header("Content-Type", "application/json")

    context = _ssl_context(verify_ssl)
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                if not body.strip():
                    return {}
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    return normalize_json_object(parsed)
                return {"raw": normalize_json_value(parsed)}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise SeedError(f"OpenBao HTTP {exc.code} on {method} {url}: {detail}") from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(retry_delay)
                continue
            raise SeedError(f"OpenBao connection failed for {url}: {exc}") from exc

    raise SeedError(f"OpenBao request failed for {url}: {last_error}")


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default))


def _resolve_admin_token() -> str:
    token = _env("BAO_TOKEN", "").strip()
    token_file = _env("BAO_TOKEN_FILE", "").strip()
    fallback = _env("BAO_BOOTSTRAP_ADMIN_TOKEN", "").strip()

    if token:
        return token

    if token_file:
        path = Path(token_file)
        if path.exists():
            file_token = path.read_text(encoding="utf-8").strip()
            if file_token:
                return file_token
            raise SeedError(f"BAO_TOKEN_FILE is empty: {path}")
        # Persist explicit fallback token if caller provided one.
        if fallback:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(fallback, encoding="utf-8")
            return fallback
        raise SeedError(f"BAO_TOKEN_FILE not found: {path}")

    if fallback:
        return fallback
    raise SeedError(
        "Missing OpenBao bootstrap token. Configure BAO_TOKEN_FILE or BAO_BOOTSTRAP_ADMIN_TOKEN."
    )


def _split_kv_path(secret_path: str) -> tuple[str, str]:
    normalized = secret_path.strip().strip("/")
    if not normalized:
        raise SeedError("IMMOAPP_SECRETS_PATH cannot be empty.")
    if "/data/" in normalized:
        mount, key = normalized.split("/data/", 1)
    else:
        parts = normalized.split("/", 1)
        mount = parts[0]
        key = parts[1] if len(parts) > 1 else ""
    key = key.strip("/")
    if not key:
        raise SeedError(
            f"Secret path '{secret_path}' is invalid. Expected KV v2 key path (e.g. secret/data/immoapp/dev)."
        )
    return mount, key


def _render_app_policy(secret_path: str) -> str:
    mount, key = _split_kv_path(secret_path)
    return f"""
path "{mount}/data/{key}" {{
  capabilities = ["read"]
}}
path "{mount}/metadata/{key}" {{
  capabilities = ["read", "list"]
}}
""".strip()


def _default_role_name() -> str:
    env_name = _env("IMMOAPP_ENV", "dev").strip().lower() or "dev"
    env_name = "".join(ch if (ch.isalnum() or ch in {"-", "_"}) else "-" for ch in env_name)
    env_name = env_name.replace("_", "-")
    return f"immoapp-server-{env_name}"


def _secret_source_path() -> Path:
    raw = _env("IMMOAPP_BOOTSTRAP_SECRETS_FILE", "").strip()
    if raw:
        return Path(raw)
    return Path("/run/immoapp-secrets/immoapp-dev-secrets.json")


def _random_secret(length_bytes: int = 32) -> str:
    return secrets.token_urlsafe(length_bytes)


def _default_value_for_key(key: str, seed: dict[str, str]) -> str | None:
    if key == "DJANGO_SECRET_KEY":
        return _random_secret(48)
    if key == "ALE_KEY_VERSION":
        return "v1"
    if key == "ALE_SEARCH_KEY_VERSION":
        return "v1"
    if key == "ALE_SEARCH_SECRET":
        return _random_secret(32)
    if key == "ALE_KDF_SALT":
        return _random_secret(24)
    if key == "POSTGRES_DB":
        return seed.get("POSTGRES_DB", "immoapp")
    if key == "POSTGRES_USER":
        return seed.get("POSTGRES_USER", "immoapp_app")
    if key == "POSTGRES_PASSWORD":
        return seed.get("POSTGRES_PASSWORD", "immoapp_app_password")
    if key == "POSTGRES_ADMIN_USER":
        return seed.get("POSTGRES_ADMIN_USER", "immoapp")
    if key == "POSTGRES_ADMIN_PASSWORD":
        return seed.get("POSTGRES_ADMIN_PASSWORD", "immoapp_admin_password")
    if key == "CELERY_BROKER_URL":
        return seed.get("CELERY_BROKER_URL")
    if key == "STORAGE_SECRET_KEY":
        return seed.get("STORAGE_SECRET_KEY") or seed.get("MINIO_ROOT_PASSWORD")
    if key == "RABBITMQ_USER":
        return seed.get("RABBITMQ_USER", "immoapp")
    if key == "RABBITMQ_PASSWORD":
        return seed.get("RABBITMQ_PASSWORD", "immoapp_rabbit_password")
    if key == "MINIO_ROOT_USER":
        return seed.get("MINIO_ROOT_USER", "immoapp")
    if key == "MINIO_ROOT_PASSWORD":
        return seed.get("MINIO_ROOT_PASSWORD", "immoapp123")
    if key == "STORAGE_BUCKET":
        return seed.get("STORAGE_BUCKET", "immoapp")
    if key == "JWT_SECRET_KEY":
        return _random_secret(32)
    if key == "IMMOAPP_IDEMPOTENCY_HMAC_KEY":
        return _random_secret(48)
    return None


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
            if not any(env_key.startswith(prefix) and data.get(env_key) for env_key in data):
                missing.append(key)
            continue
        if not data.get(key):
            missing.append(key)
    return missing


def _build_seed_payload() -> tuple[dict[str, str], Path]:
    source_file = _secret_source_path()
    source_data: dict[str, str] = {}
    if source_file.exists():
        parsed = json.loads(source_file.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            source_data = {str(k): str(v) for k, v in parsed.items() if v is not None}

    env_seed: dict[str, str] = {}
    for key in (
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_ADMIN_USER",
        "POSTGRES_ADMIN_PASSWORD",
        "RABBITMQ_USER",
        "RABBITMQ_PASSWORD",
        "CELERY_BROKER_URL",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "MINIO_KMS_SECRET_KEY",
        "STORAGE_BUCKET",
        "STORAGE_ACCESS_KEY",
        "STORAGE_SECRET_KEY",
    ):
        value = _env(key, "").strip()
        if value:
            env_seed[key] = value

    if "STORAGE_ACCESS_KEY" not in env_seed and env_seed.get("MINIO_ROOT_USER"):
        env_seed["STORAGE_ACCESS_KEY"] = env_seed["MINIO_ROOT_USER"]
    if "STORAGE_SECRET_KEY" not in env_seed and env_seed.get("MINIO_ROOT_PASSWORD"):
        env_seed["STORAGE_SECRET_KEY"] = env_seed["MINIO_ROOT_PASSWORD"]

    payload: dict[str, str] = dict(source_data)

    # Runtime topology belongs to the execution environment, not OpenBao. A
    # host-local seed file may contain localhost URLs while Docker services must
    # use service DNS names such as valkey. Keeping these values in OpenBao lets
    # secret loading overwrite the correct container environment at startup.
    # Purge stale values created by older releases so reseeding is self-healing.
    for topology_key in ("VALKEY_URL", "CHANNEL_LAYER_URL"):
        payload.pop(topology_key, None)

    for key, value in env_seed.items():
        payload.setdefault(key, value)

    if not _has_master_key(payload):
        payload["ALE_MASTER_KEY"] = _random_secret(48)

    required = _required_keys()
    missing = _validate_required(payload, required)
    for key in list(missing):
        if key.endswith("*"):
            continue
        default_value = _default_value_for_key(key, env_seed)
        if default_value:
            payload[key] = default_value
    missing = _validate_required(payload, required)
    if missing:
        raise SeedError(
            "OpenBao seed payload missing required keys: "
            + ", ".join(missing)
            + f". Source file: {source_file}"
        )

    return payload, source_file


def _safe_write_json(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    try:
        # App containers run as non-root; keep AppRole file readable.
        path.chmod(0o644)
    except Exception:
        pass


def _ensure_auth_mounts(
    addr: str, headers: dict[str, str], timeout: float, verify_ssl: bool
) -> None:
    data = _request_json(
        "GET",
        f"{addr}/v1/sys/auth",
        headers=headers,
        timeout=timeout,
        verify_ssl=verify_ssl,
    )
    existing_data = data.get("data")
    existing: JsonObject = existing_data if isinstance(existing_data, dict) else {}
    if "userpass/" not in existing:
        _request_json(
            "POST",
            f"{addr}/v1/sys/auth/userpass",
            headers=headers,
            payload={"type": "userpass"},
            timeout=timeout,
            verify_ssl=verify_ssl,
        )
    if "approle/" not in existing:
        _request_json(
            "POST",
            f"{addr}/v1/sys/auth/approle",
            headers=headers,
            payload={"type": "approle"},
            timeout=timeout,
            verify_ssl=verify_ssl,
        )


def _ensure_kv_v2_mount(
    addr: str,
    headers: dict[str, str],
    timeout: float,
    verify_ssl: bool,
    *,
    mount: str,
) -> None:
    mount_name = mount.strip().strip("/")
    if not mount_name:
        raise SeedError("Invalid KV mount name.")
    mount_key = f"{mount_name}/"

    data = _request_json(
        "GET",
        f"{addr}/v1/sys/mounts",
        headers=headers,
        timeout=timeout,
        verify_ssl=verify_ssl,
    )
    mounts = data.get("data") if isinstance(data.get("data"), dict) else {}
    existing = mounts.get(mount_key) if isinstance(mounts, dict) else None
    if existing is None:
        _request_json(
            "POST",
            f"{addr}/v1/sys/mounts/{urllib.parse.quote(mount_name, safe='')}",
            headers=headers,
            payload={"type": "kv", "options": {"version": "2"}},
            timeout=timeout,
            verify_ssl=verify_ssl,
        )
        return

    options = (existing or {}).get("options") if isinstance(existing, dict) else {}
    version = ""
    if isinstance(options, dict):
        version = str(options.get("version") or "").strip()
    if version != "2":
        _request_json(
            "POST",
            f"{addr}/v1/sys/mounts/{urllib.parse.quote(mount_name, safe='')}/tune",
            headers=headers,
            payload={"options": {"version": "2"}},
            timeout=timeout,
            verify_ssl=verify_ssl,
        )


def _ensure_approle(
    addr: str,
    headers: dict[str, str],
    timeout: float,
    verify_ssl: bool,
    *,
    role_name: str,
    policy_name: str,
    secret_path: str,
    secret_id_ttl: str,
    approle_file: Path,
) -> None:
    policy = _render_app_policy(secret_path)
    _request_json(
        "PUT",
        f"{addr}/v1/sys/policies/acl/{urllib.parse.quote(policy_name, safe='')}",
        headers=headers,
        payload={"policy": policy},
        timeout=timeout,
        verify_ssl=verify_ssl,
    )

    _request_json(
        "POST",
        f"{addr}/v1/auth/approle/role/{urllib.parse.quote(role_name, safe='')}",
        headers=headers,
        payload={
            "token_policies": [policy_name],
            "token_ttl": "1h",
            "token_max_ttl": "4h",
            "secret_id_ttl": secret_id_ttl,
            "bind_secret_id": True,
        },
        timeout=timeout,
        verify_ssl=verify_ssl,
    )

    role_resp = _request_json(
        "GET",
        f"{addr}/v1/auth/approle/role/{urllib.parse.quote(role_name, safe='')}/role-id",
        headers=headers,
        timeout=timeout,
        verify_ssl=verify_ssl,
    )
    role_data = role_resp.get("data")
    role_payload = role_data if isinstance(role_data, dict) else {}
    role_id = str(role_payload.get("role_id") or "").strip()
    if not role_id:
        raise SeedError(f"Failed to retrieve role_id for AppRole '{role_name}'.")

    sid_resp = _request_json(
        "POST",
        f"{addr}/v1/auth/approle/role/{urllib.parse.quote(role_name, safe='')}/secret-id",
        headers=headers,
        payload={},
        timeout=timeout,
        verify_ssl=verify_ssl,
    )
    secret_data = sid_resp.get("data")
    secret_payload = secret_data if isinstance(secret_data, dict) else {}
    secret_id = str(secret_payload.get("secret_id") or "").strip()
    if not secret_id:
        raise SeedError(f"Failed to generate secret_id for AppRole '{role_name}'.")

    _safe_write_json(
        approle_file,
        {
            "app_role_name": role_name,
            "app_role_id": role_id,
            "app_secret_id": secret_id,
        },
    )


def _write_and_verify_secret(
    addr: str,
    headers: dict[str, str],
    timeout: float,
    verify_ssl: bool,
    *,
    secret_path: str,
    payload: dict[str, str],
) -> None:
    write_url = f"{addr}/v1/{secret_path.lstrip('/')}"
    _request_json(
        "POST",
        write_url,
        headers=headers,
        payload={"data": normalize_json_object(payload)},
        timeout=timeout,
        verify_ssl=verify_ssl,
    )

    read_resp = _request_json(
        "GET",
        write_url,
        headers=headers,
        timeout=timeout,
        verify_ssl=verify_ssl,
    )
    read_payload = read_resp.get("data")
    loaded: JsonObject = {}
    if isinstance(read_payload, dict):
        nested_data = read_payload.get("data")
        if isinstance(nested_data, dict):
            loaded = nested_data
        else:
            loaded = read_payload

    missing = _validate_required({str(k): str(v) for k, v in loaded.items()}, _required_keys())
    if missing:
        raise SeedError(
            "OpenBao verification failed after write; missing required keys: " + ", ".join(missing)
        )


def main() -> None:
    addr = _env("BAO_ADDR", "http://openbao:8200").strip().rstrip("/")
    if not addr:
        raise SeedError("BAO_ADDR is empty.")

    verify_ssl = _truthy(_env("BAO_VERIFY_SSL", "0"))
    if addr.lower().startswith("http://"):
        verify_ssl = False
    timeout = float(_env("BAO_TIMEOUT", "8"))
    namespace = _env("BAO_NAMESPACE", "").strip()
    token = _resolve_admin_token()

    headers: dict[str, str] = {"X-Vault-Token": token}
    if namespace:
        headers["X-Vault-Namespace"] = namespace

    secret_path = _env("IMMOAPP_SECRETS_PATH", "secret/data/immoapp/dev").strip()
    if not secret_path:
        raise SeedError("IMMOAPP_SECRETS_PATH is empty.")

    role_name = _env("OPENBAO_APP_ROLE_NAME", "").strip() or _default_role_name()
    policy_name = _env("OPENBAO_APP_POLICY_NAME", "immoapp-app-secrets-read").strip()
    sid_ttl = _env("OPENBAO_APPROLE_SECRET_ID_TTL", "168h").strip() or "168h"
    approle_file = Path(_env("BAO_APPROLE_FILE", "/run/immoapp-secrets/openbao-approle.json"))
    if os.name != "nt" and len(str(approle_file)) > 2 and str(approle_file)[1:3] in {":\\", ":/"}:
        raise SeedError(
            f"BAO_APPROLE_FILE uses a Windows path inside container runtime: {approle_file}"
        )

    payload, source_file = _build_seed_payload()
    _ensure_auth_mounts(addr, headers, timeout, verify_ssl)
    mount_name, _ = _split_kv_path(secret_path)
    _ensure_kv_v2_mount(
        addr,
        headers,
        timeout,
        verify_ssl,
        mount=mount_name,
    )
    _ensure_approle(
        addr,
        headers,
        timeout,
        verify_ssl,
        role_name=role_name,
        policy_name=policy_name,
        secret_path=secret_path,
        secret_id_ttl=sid_ttl,
        approle_file=approle_file,
    )
    _write_and_verify_secret(
        addr,
        headers,
        timeout,
        verify_ssl,
        secret_path=secret_path,
        payload=payload,
    )
    _safe_write_json(source_file, payload)
    print(
        "openbao_seed_runtime: seeded path="
        f"{secret_path} keys={len(payload)} role={role_name} source={source_file}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - operational script
        print(f"openbao_seed_runtime: ERROR: {exc}", file=sys.stderr)
        raise
