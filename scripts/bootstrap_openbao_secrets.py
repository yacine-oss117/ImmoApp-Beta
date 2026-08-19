from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_env() -> None:
    from core.env_files import resolve_env_file

    repo_root = Path(__file__).resolve().parents[1]
    base_dir = repo_root / "server"
    env_path = resolve_env_file(repo_root, base_dir)
    if env_path.exists():
        # Bootstrap must read the file as the source of truth.
        load_dotenv(env_path, override=True)


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


def _required_keys() -> list[str]:
    raw = os.environ.get("IMMOAPP_SECRETS_REQUIRED_KEYS", "").strip()
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    # By default sync all allowlisted keys present in env.
    # Set IMMOAPP_SECRETS_REQUIRED_KEYS to enforce a strict bootstrap set.
    return []


def _parse_allowlist(raw: str | None) -> list[str]:
    if not raw:
        return ["ALE_", "DJANGO_", "IMMOAPP_"]
    return [item.strip() for item in raw.split(",") if item.strip()]


def _allowed(key: str, allowlist: list[str]) -> bool:
    for rule in allowlist:
        if rule.endswith("*"):
            if key.startswith(rule[:-1]):
                return True
        elif rule.endswith("_"):
            if key.startswith(rule):
                return True
        elif key == rule:
            return True
    return False


def _collect_payload() -> dict[str, str]:
    keys = _required_keys()
    payload: dict[str, str] = {}
    missing: list[str] = []
    allowlist = _parse_allowlist(os.environ.get("IMMOAPP_SECRETS_ALLOWLIST"))

    for key in keys:
        if key == "ALE_MASTER_KEY":
            direct = os.environ.get("ALE_MASTER_KEY")
            if direct:
                payload["ALE_MASTER_KEY"] = direct
                continue
            versioned = {
                env_key: env_val
                for env_key, env_val in os.environ.items()
                if env_key.startswith("ALE_MASTER_KEY_V") and bool(env_val)
            }
            if versioned:
                payload.update(versioned)
                continue
            missing.append("ALE_MASTER_KEY*")
            continue

        if key.endswith("*"):
            prefix = key[:-1]
            matched = {
                env_key: env_val
                for env_key, env_val in os.environ.items()
                if env_key.startswith(prefix) and bool(env_val)
            }
            if matched:
                payload.update(matched)
            else:
                missing.append(key)
            continue

        value = os.environ.get(key)
        if value:
            payload[key] = value
        else:
            missing.append(key)

    if missing:
        raise RuntimeError(
            "Missing required source env vars for OpenBao bootstrap: " + ", ".join(missing)
        )

    # Also sync any configured runtime env keys (for OpenBao-only runtime).
    # This lets operators progressively remove plaintext values from env.local
    # while keeping startup deterministic.
    for env_key, env_val in os.environ.items():
        if not isinstance(env_key, str):
            continue
        if not _allowed(env_key, allowlist):
            continue
        if not env_val:
            continue
        payload.setdefault(env_key, str(env_val))
    return payload


def _ssl_context() -> ssl.SSLContext | None:
    if _truthy(os.environ.get("BAO_VERIFY_SSL", "1")):
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _resolve_token(headers: dict[str, str]) -> str:
    token_file = os.environ.get("BAO_TOKEN_FILE")
    if token_file:
        token_path = Path(token_file.strip())
        if token_path.exists():
            token = token_path.read_text(encoding="utf-8").strip()
            if token:
                return token
            raise RuntimeError(f"BAO_TOKEN_FILE is empty: {token_path}")
        raise RuntimeError(f"BAO_TOKEN_FILE does not exist: {token_path}")

    token = os.environ.get("BAO_TOKEN")
    if token:
        return token

    role_id = os.environ.get("BAO_ROLE_ID")
    secret_id = os.environ.get("BAO_SECRET_ID")
    if not (role_id and secret_id):
        approle_file = (os.environ.get("BAO_APPROLE_FILE") or "").strip()
        if approle_file:
            path = Path(approle_file)
            if not path.exists():
                raise RuntimeError(f"BAO_APPROLE_FILE does not exist: {path}")
            try:
                parsed = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise RuntimeError(f"Failed to parse BAO_APPROLE_FILE at {path}: {exc}") from exc
            role_id = role_id or parsed.get("app_role_id") or parsed.get("role_id")
            secret_id = secret_id or parsed.get("app_secret_id") or parsed.get("secret_id")

    if not role_id or not secret_id:
        raise RuntimeError(
            "Set BAO_TOKEN, BAO_APPROLE_FILE, or BAO_ROLE_ID/BAO_SECRET_ID before bootstrap."
        )

    addr = os.environ.get("BAO_ADDR", "http://127.0.0.1:8200").rstrip("/")
    body = json.dumps({"role_id": role_id, "secret_id": secret_id}).encode("utf-8")
    req = urllib.request.Request(
        f"{addr}/v1/auth/approle/login",
        data=body,
        method="POST",
        headers={**headers, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10, context=_ssl_context()) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    client_token = (parsed.get("auth") or {}).get("client_token")
    if not client_token:
        raise RuntimeError("OpenBao AppRole login failed (missing client_token).")
    return str(client_token)


def _write_secret(path: str, payload: dict[str, str]) -> None:
    addr = os.environ.get("BAO_ADDR", "http://127.0.0.1:8200").rstrip("/")
    namespace = os.environ.get("BAO_NAMESPACE")
    headers: dict[str, str] = {}
    if namespace:
        headers["X-Vault-Namespace"] = namespace
    token = _resolve_token(headers)
    headers["X-Vault-Token"] = token
    headers["Content-Type"] = "application/json"

    body = json.dumps({"data": payload}).encode("utf-8")
    req = urllib.request.Request(
        f"{addr}/v1/{path.lstrip('/')}",
        data=body,
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=10, context=_ssl_context()):
            pass
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenBao write failed: HTTP {exc.code} {detail}") from exc


def main() -> None:
    _load_env()
    path = os.environ.get("IMMOAPP_SECRETS_PATH", "secret/data/immoapp")
    payload = _collect_payload()
    _write_secret(path, payload)
    print(f"bootstrap_openbao_secrets: wrote {len(payload)} keys to {path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - operational utility
        print(f"bootstrap_openbao_secrets: ERROR: {exc}", file=sys.stderr)
        raise
