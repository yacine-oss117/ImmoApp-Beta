from __future__ import annotations

import argparse
import getpass
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_env() -> Path:
    from core.env_files import resolve_env_file

    repo_root = Path(__file__).resolve().parents[1]
    base_dir = repo_root / "server"
    env_path = resolve_env_file(repo_root, base_dir)
    if env_path.exists():
        load_dotenv(env_path, override=False)
    return env_path


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


def _ssl_context(verify_ssl: bool) -> ssl.SSLContext | None:
    if verify_ssl:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _effective_verify_ssl(addr: str, requested: bool) -> bool:
    if addr.strip().lower().startswith("http://"):
        return False
    return requested


class BaoClient:
    def __init__(
        self,
        *,
        addr: str,
        namespace: str | None,
        token: str | None,
        timeout: float,
        verify_ssl: bool,
    ) -> None:
        self.addr = addr.rstrip("/")
        self.namespace = namespace
        self.token = token
        self.timeout = timeout
        self.verify_ssl = verify_ssl

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        allow_status: set[int] | None = None,
    ) -> dict[str, Any]:
        allowed = allow_status or {200, 204}
        url = f"{self.addr}/v1/{path.lstrip('/')}"
        headers: dict[str, str] = {}
        if self.namespace:
            headers["X-Vault-Namespace"] = self.namespace
        if self.token:
            headers["X-Vault-Token"] = self.token
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout, context=_ssl_context(self.verify_ssl)
            ) as response:
                status = int(response.status)
                body = response.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"OpenBao HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenBao connection failed: {exc}") from exc

        if status not in allowed:
            raise RuntimeError(
                f"OpenBao unexpected status {status} for {method} {path}: {body[:300]}"
            )
        if not body.strip():
            return {}
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return {"raw": body}
        if isinstance(parsed, dict):
            return parsed
        return {"raw": parsed}


def _split_kv_path(secret_path: str) -> tuple[str, str]:
    normalized = secret_path.strip().strip("/")
    if not normalized:
        raise RuntimeError("Secret path cannot be empty.")
    if "/data/" in normalized:
        mount, key = normalized.split("/data/", 1)
    else:
        parts = normalized.split("/", 1)
        mount = parts[0]
        key = parts[1] if len(parts) > 1 else ""
        if key == "data":
            key = ""
    key = key.strip("/")
    if not key:
        raise RuntimeError(
            f"Secret path '{secret_path}' does not include a secret key path (e.g. secret/data/immoapp)."
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


def _render_operator_policy(secret_path: str, app_role_name: str) -> str:
    mount, key = _split_kv_path(secret_path)
    role = app_role_name.strip().strip("/")
    return f"""
path "{mount}/data/{key}" {{
  capabilities = ["create", "update", "read", "delete"]
}}
path "{mount}/metadata/{key}" {{
  capabilities = ["read", "list"]
}}
path "auth/token/lookup-self" {{
  capabilities = ["read"]
}}
path "auth/token/renew-self" {{
  capabilities = ["update"]
}}
path "auth/approle/role/{role}" {{
  capabilities = ["create", "read", "update", "delete"]
}}
path "auth/approle/role/{role}/*" {{
  capabilities = ["create", "read", "update", "delete"]
}}
""".strip()


def _read_token_file(path_value: str) -> str:
    path = Path(path_value.strip())
    if not path.exists():
        raise RuntimeError(f"Token file not found: {path}")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError(f"Token file is empty: {path}")
    return token


def _resolve_admin_token(args: argparse.Namespace) -> str:
    inline_token = str(args.admin_token or "").strip()
    if inline_token:
        raise RuntimeError(
            "Inline --admin-token is forbidden by policy. Use --admin-token-file instead."
        )

    env_inline_token = os.environ.get("BAO_TOKEN", "").strip()
    if env_inline_token:
        raise RuntimeError(
            "BAO_TOKEN must stay empty for identity bootstrap. Use BAO_TOKEN_FILE instead."
        )

    token_file = str(args.admin_token_file or "").strip()
    if token_file:
        return _read_token_file(token_file)

    env_token_file = os.environ.get("BAO_TOKEN_FILE", "").strip()
    if env_token_file:
        return _read_token_file(env_token_file)

    raise RuntimeError(
        "Missing OpenBao admin token file. Provide --admin-token-file or set BAO_TOKEN_FILE."
    )


def _login_approle_for_token(
    *,
    addr: str,
    namespace: str | None,
    role_id: str,
    secret_id: str,
    timeout: float,
    verify_ssl: bool,
) -> str:
    client = BaoClient(
        addr=addr, namespace=namespace, token=None, timeout=timeout, verify_ssl=verify_ssl
    )
    payload = {"role_id": role_id, "secret_id": secret_id}
    response = client.request("POST", "auth/approle/login", payload)
    token = str((response.get("auth") or {}).get("client_token") or "").strip()
    if not token:
        raise RuntimeError("OpenBao AppRole login failed: missing client_token.")
    return token


def _ensure_auth_method(client: BaoClient, *, mount: str, method_type: str) -> str:
    normalized = mount.strip().strip("/")
    current = client.request("GET", "sys/auth")
    auth_map = current.get("data") if isinstance(current.get("data"), dict) else {}
    key = f"{normalized}/"
    if key in auth_map:
        existing_type = str((auth_map[key] or {}).get("type") or "")
        if existing_type != method_type:
            raise RuntimeError(
                f"Auth mount '{normalized}' already exists with type '{existing_type}', expected '{method_type}'."
            )
        return "exists"
    client.request("POST", f"sys/auth/{normalized}", {"type": method_type})
    return "created"


def _write_policy(client: BaoClient, *, policy_name: str, policy_hcl: str) -> None:
    payload = {"policy": policy_hcl}
    client.request("PUT", f"sys/policies/acl/{policy_name}", payload)


def _upsert_userpass_user(
    client: BaoClient,
    *,
    username: str,
    password: str,
    policies: list[str],
) -> None:
    quoted_user = urllib.parse.quote(username.strip(), safe="")
    payload = {
        "password": password,
        "policies": ",".join(sorted({item.strip() for item in policies if item.strip()})),
    }
    client.request("POST", f"auth/userpass/users/{quoted_user}", payload)


def _upsert_approle(
    client: BaoClient,
    *,
    role_name: str,
    policies: list[str],
    token_ttl: str,
    token_max_ttl: str,
    secret_id_ttl: str,
) -> None:
    payload = {
        "token_policies": sorted({item.strip() for item in policies if item.strip()}),
        "token_ttl": token_ttl,
        "token_max_ttl": token_max_ttl,
        "secret_id_ttl": secret_id_ttl,
        "bind_secret_id": True,
        "local_secret_ids": False,
    }
    client.request("POST", f"auth/approle/role/{role_name.strip()}", payload)


def _fetch_role_id(client: BaoClient, role_name: str) -> str:
    response = client.request("GET", f"auth/approle/role/{role_name.strip()}/role-id")
    role_id = str((response.get("data") or {}).get("role_id") or "").strip()
    if not role_id:
        raise RuntimeError(f"Failed to fetch role_id for AppRole '{role_name}'.")
    return role_id


def _generate_secret_id(client: BaoClient, role_name: str) -> str:
    response = client.request("POST", f"auth/approle/role/{role_name.strip()}/secret-id", {})
    secret_id = str((response.get("data") or {}).get("secret_id") or "").strip()
    if not secret_id:
        raise RuntimeError(f"Failed to generate secret_id for AppRole '{role_name}'.")
    return secret_id


def _mask(value: str, *, prefix: int = 4, suffix: int = 4) -> str:
    if len(value) <= prefix + suffix + 2:
        return "*" * len(value)
    return f"{value[:prefix]}...{value[-suffix:]}"


def _default_env_name() -> str:
    raw = (os.environ.get("IMMOAPP_ENV") or "").strip().lower()
    if raw:
        cleaned = "".join(ch if (ch.isalnum() or ch in {"-", "_"}) else "-" for ch in raw)
        return cleaned.replace("_", "-")
    debug = os.environ.get("DJANGO_DEBUG")
    if _truthy(debug):
        return "dev"
    return "prod"


def _default_app_role_name(env_name: str) -> str:
    return f"immoapp-server-{env_name}"


def _default_secrets_path(env_name: str) -> str:
    return f"secret/data/immoapp/{env_name}"


def _is_dev_like_env(env_name: str) -> bool:
    return env_name in {"dev", "development", "local", "test", "ci"}


def _is_nonexpiring_ttl(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {"0", "0s", "0m", "0h", "0d", "0w"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap OpenBao identities: operator userpass identity + app AppRole."
    )
    parser.add_argument("--addr", default=os.environ.get("BAO_ADDR", "http://127.0.0.1:8200"))
    parser.add_argument("--namespace", default=os.environ.get("BAO_NAMESPACE", ""))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("BAO_TIMEOUT", "8")))
    parser.add_argument(
        "--verify-ssl",
        dest="verify_ssl",
        action="store_true",
        default=_truthy(os.environ.get("BAO_VERIFY_SSL", "1")),
    )
    parser.add_argument("--insecure-skip-verify", dest="verify_ssl", action="store_false")
    parser.add_argument("--admin-token", default="")
    parser.add_argument("--admin-token-file", default="")
    parser.add_argument("--admin-role-id", default="")
    parser.add_argument("--admin-secret-id", default="")

    parser.add_argument("--operator-username", required=True)
    parser.add_argument("--operator-password", default="")
    parser.add_argument("--operator-policy-name", default="immoapp-operator")
    parser.add_argument("--app-policy-name", default="immoapp-app-secrets-read")
    parser.add_argument("--app-role-name", default="")
    parser.add_argument(
        "--secrets-path",
        default="",
    )
    parser.add_argument("--app-token-ttl", default="1h")
    parser.add_argument("--app-token-max-ttl", default="4h")
    parser.add_argument(
        "--app-secret-id-ttl",
        default=os.environ.get("OPENBAO_APPROLE_SECRET_ID_TTL", "168h"),
    )
    parser.add_argument("--out-json", default="")
    parser.add_argument("--show-secrets", action="store_true")
    return parser.parse_args()


def _harden_secret_file(path: Path) -> None:
    try:
        path.chmod(0o600)
    except Exception:
        pass
    if os.name != "nt":
        return
    identity = ""
    try:
        proc = subprocess.run(["whoami"], check=False, capture_output=True, text=True)
        identity = (proc.stdout or "").strip()
    except Exception:
        identity = ""
    if not identity:
        identity = os.environ.get("USERNAME", "").strip()
    if not identity:
        return
    path_str = str(path)
    cmds = [
        ["icacls", path_str, "/inheritance:r"],
        ["icacls", path_str, "/grant:r", f"{identity}:(R,W)"],
        ["icacls", path_str, "/grant:r", "SYSTEM:(F)"],
        ["icacls", path_str, "/grant:r", "Administrators:(F)"],
    ]
    for cmd in cmds:
        try:
            subprocess.run(cmd, check=False, capture_output=True, text=True)
        except Exception:
            pass


def main() -> None:
    env_path = _load_env()
    args = _parse_args()
    env_name = _default_env_name()
    app_role_name = (args.app_role_name or "").strip() or _default_app_role_name(env_name)
    secrets_path = (args.secrets_path or "").strip()
    if not secrets_path:
        secrets_path = (os.environ.get("IMMOAPP_SECRETS_PATH") or "").strip()
    if not secrets_path:
        secrets_path = _default_secrets_path(env_name)
    secret_id_ttl = str(args.app_secret_id_ttl or "").strip()
    if not secret_id_ttl:
        raise RuntimeError("AppRole SecretID TTL cannot be empty.")
    if _is_nonexpiring_ttl(secret_id_ttl):
        if _is_dev_like_env(env_name):
            print(
                "bootstrap_openbao_identity: warning: non-expiring AppRole SecretID TTL is enabled "
                "for dev-like environment.",
                file=sys.stderr,
            )
        else:
            raise RuntimeError(
                "Non-expiring AppRole SecretID TTL is forbidden in non-dev environments. "
                "Set OPENBAO_APPROLE_SECRET_ID_TTL to a finite value (for example 168h)."
            )
    namespace = args.namespace.strip() or None
    operator_password = str(args.operator_password or "").strip()
    if not operator_password:
        operator_password = os.environ.get("OPENBAO_OPERATOR_PASSWORD", "").strip()
    if not operator_password:
        operator_password = getpass.getpass("Operator password: ").strip()
    if not operator_password:
        raise RuntimeError("Operator password is required.")
    admin_token = _resolve_admin_token(args)
    verify_ssl = _effective_verify_ssl(args.addr, bool(args.verify_ssl))
    client = BaoClient(
        addr=args.addr,
        namespace=namespace,
        token=admin_token,
        timeout=args.timeout,
        verify_ssl=verify_ssl,
    )

    userpass_status = _ensure_auth_method(client, mount="userpass", method_type="userpass")
    approle_status = _ensure_auth_method(client, mount="approle", method_type="approle")

    app_policy_hcl = _render_app_policy(secrets_path)
    operator_policy_hcl = _render_operator_policy(secrets_path, app_role_name)
    _write_policy(client, policy_name=args.app_policy_name, policy_hcl=app_policy_hcl)
    _write_policy(client, policy_name=args.operator_policy_name, policy_hcl=operator_policy_hcl)

    _upsert_userpass_user(
        client,
        username=args.operator_username,
        password=operator_password,
        policies=[args.operator_policy_name],
    )

    _upsert_approle(
        client,
        role_name=app_role_name,
        policies=[args.app_policy_name],
        token_ttl=args.app_token_ttl,
        token_max_ttl=args.app_token_max_ttl,
        secret_id_ttl=secret_id_ttl,
    )
    role_id = _fetch_role_id(client, app_role_name)
    secret_id = _generate_secret_id(client, app_role_name)

    result = {
        "operator_username": args.operator_username,
        "operator_policy_name": args.operator_policy_name,
        "app_policy_name": args.app_policy_name,
        "app_role_name": app_role_name,
        "app_role_id": role_id,
        "app_secret_id": secret_id,
        "secrets_path": secrets_path,
        "userpass_mount": userpass_status,
        "approle_mount": approle_status,
        "env_name": env_name,
        "env_file": str(env_path),
    }

    if args.out_json:
        out_path = Path(args.out_json).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        _harden_secret_file(out_path)
        print(f"bootstrap_openbao_identity: wrote credentials to {out_path}")

    if args.show_secrets:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        safe = dict(result)
        safe["app_role_id"] = _mask(role_id)
        safe["app_secret_id"] = _mask(secret_id)
        print(json.dumps(safe, indent=2, sort_keys=True))
        print("bootstrap_openbao_identity: pass --show-secrets only in secure terminals.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover
        print(f"bootstrap_openbao_identity: ERROR: {exc}", file=sys.stderr)
        raise
