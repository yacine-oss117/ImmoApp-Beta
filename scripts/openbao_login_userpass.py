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


def _load_env() -> None:
    from core.env_files import resolve_env_file

    repo_root = Path(__file__).resolve().parents[1]
    base_dir = repo_root / "server"
    env_path = resolve_env_file(repo_root, base_dir)
    if env_path.exists():
        load_dotenv(env_path, override=False)


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
    *,
    method: str,
    addr: str,
    path: str,
    payload: dict[str, Any] | None,
    timeout: float,
    verify_ssl: bool,
    namespace: str | None,
) -> dict[str, Any]:
    url = f"{addr.rstrip('/')}/v1/{path.lstrip('/')}"
    headers: dict[str, str] = {}
    if namespace:
        headers["X-Vault-Namespace"] = namespace
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context(verify_ssl)) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenBao HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenBao connection failed: {exc}") from exc

    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("OpenBao returned unexpected JSON shape.")
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Login to OpenBao with userpass and optionally write token to a file."
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", default="")
    parser.add_argument("--token-out", default="")
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
    parser.add_argument("--show-token", action="store_true")
    return parser.parse_args()


def _effective_verify_ssl(addr: str, requested: bool) -> bool:
    if addr.strip().lower().startswith("http://"):
        return False
    return requested


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
    _load_env()
    args = _parse_args()
    username = args.username.strip()
    if not username:
        raise RuntimeError("Username is required.")

    password = args.password or os.environ.get("BAO_USERPASS_PASSWORD", "")
    if not password:
        password = getpass.getpass("OpenBao password: ")
    if not password:
        raise RuntimeError("Password is required.")
    verify_ssl = _effective_verify_ssl(args.addr, bool(args.verify_ssl))
    if bool(args.verify_ssl) and not verify_ssl:
        print(
            "openbao_login_userpass: warning: BAO_VERIFY_SSL was requested, but address is http://. "
            "SSL verification is disabled.",
            file=sys.stderr,
        )

    quoted_user = urllib.parse.quote(username, safe="")
    response = _request_json(
        method="POST",
        addr=args.addr,
        path=f"auth/userpass/login/{quoted_user}",
        payload={"password": password},
        timeout=args.timeout,
        verify_ssl=verify_ssl,
        namespace=args.namespace.strip() or None,
    )
    token = str((response.get("auth") or {}).get("client_token") or "").strip()
    if not token:
        raise RuntimeError("OpenBao login succeeded but did not return client_token.")

    if args.token_out:
        token_path = Path(args.token_out).expanduser()
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(token + "\n", encoding="utf-8")
        _harden_secret_file(token_path)
        print(f"openbao_login_userpass: wrote token file {token_path}")

    if args.show_token:
        print(token)
    else:
        print("openbao_login_userpass: token acquired.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover
        print(f"openbao_login_userpass: ERROR: {exc}", file=sys.stderr)
        raise
