"""Idempotent SigNoz alert/channel provisioning via API.

This script is designed for local/full-stack docker usage and CI-friendly
automation. It supports:
- bootstrap first admin user when setup is incomplete (`/api/v1/register`)
- bearer login (`/api/v2/sessions/email_password`)
- optional PAT creation (`/api/v1/pats`)
- idempotent upsert of channels (`/api/v1/channels`)
- idempotent upsert of rules (`/api/v1/rules`)
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from repo_layout import SIGNOZ_ALERTS_CONFIG


class ProvisionError(RuntimeError):
    """Raised when provisioning cannot continue safely."""


_ENV_PLACEHOLDER_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _parse_json_maybe(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return {}
    if raw.startswith("{") or raw.startswith("["):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
    return {"raw": raw}


def _http_json(
    *,
    base_url: str,
    method: str,
    path: str,
    timeout: float,
    headers: dict[str, str] | None = None,
    payload: Any | None = None,
    expected: tuple[int, ...] = (200,),
) -> Any:
    url = f"{base_url.rstrip('/')}{path}"
    body: bytes | None = None
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    request = Request(url=url, data=body, headers=req_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            raw_body = response.read().decode("utf-8", errors="replace")
            if status not in expected:
                raise ProvisionError(f"Unexpected status {status} for {method} {path}: {raw_body}")
            if not raw_body:
                return {}
            return _parse_json_maybe(raw_body)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        detail = _parse_json_maybe(raw)
        raise ProvisionError(
            f"{method} {path} failed with {exc.code}: {json.dumps(detail)}"
        ) from exc
    except URLError as exc:
        raise ProvisionError(f"{method} {path} failed: {exc}") from exc


@dataclass(frozen=True)
class AuthContext:
    headers: dict[str, str]
    mode: str


def _get_version(base_url: str, timeout: float) -> dict[str, Any]:
    data = _http_json(
        base_url=base_url,
        method="GET",
        path="/api/v1/version",
        timeout=timeout,
        expected=(200,),
    )
    if not isinstance(data, dict):
        raise ProvisionError(f"Unexpected /api/v1/version response: {data}")
    return data


def _bootstrap_register(
    *,
    base_url: str,
    timeout: float,
    email: str,
    password: str,
) -> str | None:
    result = _http_json(
        base_url=base_url,
        method="POST",
        path="/api/v1/register",
        timeout=timeout,
        payload={"email": email, "password": password},
        expected=(200, 201),
    )
    if not isinstance(result, dict):
        return None
    data = result.get("data", {})
    if isinstance(data, dict):
        org_id = data.get("orgId")
        if isinstance(org_id, str) and org_id:
            return org_id
    return None


def _login_bearer(
    *,
    base_url: str,
    timeout: float,
    email: str,
    password: str,
    org_id: str,
) -> AuthContext:
    payload = {"email": email, "password": password, "orgID": org_id}
    result = _http_json(
        base_url=base_url,
        method="POST",
        path="/api/v2/sessions/email_password",
        timeout=timeout,
        payload=payload,
        expected=(200,),
    )
    token = result.get("data", {}).get("accessToken", "") if isinstance(result, dict) else ""
    if not isinstance(token, str) or not token:
        raise ProvisionError("SigNoz login succeeded but no access token was returned")
    return AuthContext(
        headers={"Authorization": f"Bearer {token}"},
        mode="bearer",
    )


def _auth_from_env(
    *,
    base_url: str,
    timeout: float,
    org_id_hint: str | None,
) -> tuple[AuthContext, str | None]:
    api_key = os.environ.get("SIGNOZ_API_KEY", "").strip()
    if api_key:
        return AuthContext(headers={"SIGNOZ-API-KEY": api_key}, mode="api_key"), None

    email = os.environ.get("SIGNOZ_EMAIL", "").strip()
    password = os.environ.get("SIGNOZ_PASSWORD", "").strip()
    org_id = os.environ.get("SIGNOZ_ORG_ID", "").strip() or (org_id_hint or "")
    if not email or not password or not org_id:
        raise ProvisionError(
            "Authentication missing. Set SIGNOZ_API_KEY, or "
            "SIGNOZ_EMAIL + SIGNOZ_PASSWORD + SIGNOZ_ORG_ID."
        )
    return (
        _login_bearer(
            base_url=base_url,
            timeout=timeout,
            email=email,
            password=password,
            org_id=org_id,
        ),
        org_id,
    )


def _ensure_pat(
    *,
    base_url: str,
    timeout: float,
    auth: AuthContext,
    pat_name: str,
    pat_role: str,
    write_key_file: Path | None,
) -> None:
    if auth.mode != "bearer":
        return
    pats_payload = _http_json(
        base_url=base_url,
        method="GET",
        path="/api/v1/pats",
        timeout=timeout,
        headers=auth.headers,
        expected=(200,),
    )
    existing = pats_payload.get("data", []) if isinstance(pats_payload, dict) else []
    if isinstance(existing, list) and any(
        isinstance(item, dict) and item.get("name") == pat_name for item in existing
    ):
        print(f"[INFO] PAT '{pat_name}' already exists; leaving it unchanged.")
        return

    created = _http_json(
        base_url=base_url,
        method="POST",
        path="/api/v1/pats",
        timeout=timeout,
        headers=auth.headers,
        payload={"name": pat_name, "role": pat_role},
        expected=(201,),
    )
    api_key = created.get("data", {}).get("apiKey", "") if isinstance(created, dict) else ""
    if isinstance(api_key, str) and api_key:
        if write_key_file:
            write_key_file.parent.mkdir(parents=True, exist_ok=True)
            write_key_file.write_text(api_key, encoding="utf-8")
            print(f"[INFO] Wrote SigNoz PAT to {write_key_file}")
        else:
            print(
                "[INFO] Created SigNoz PAT. Set this env var for API-key mode:\n"
                f"SIGNOZ_API_KEY={api_key}"
            )


def _channel_map(
    *,
    base_url: str,
    timeout: float,
    headers: dict[str, str],
) -> dict[str, dict[str, Any]]:
    payload = _http_json(
        base_url=base_url,
        method="GET",
        path="/api/v1/channels",
        timeout=timeout,
        headers=headers,
        expected=(200,),
    )
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    result: dict[str, dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("name")
            if isinstance(name, str) and name:
                result[name] = row
    return result


def _rule_map(
    *,
    base_url: str,
    timeout: float,
    headers: dict[str, str],
) -> dict[str, dict[str, Any]]:
    payload = _http_json(
        base_url=base_url,
        method="GET",
        path="/api/v1/rules",
        timeout=timeout,
        headers=headers,
        expected=(200,),
    )
    rows = payload.get("data", {}).get("rules", []) if isinstance(payload, dict) else []
    result: dict[str, dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("alert")
            if isinstance(name, str) and name:
                result[name] = row
    return result


def _upsert_channels(
    *,
    base_url: str,
    timeout: float,
    headers: dict[str, str],
    channels: list[dict[str, Any]],
    dry_run: bool,
) -> tuple[int, int]:
    channels = _apply_channel_runtime_defaults(channels)
    existing = _channel_map(base_url=base_url, timeout=timeout, headers=headers)
    created = 0
    updated = 0
    for channel in channels:
        name = channel.get("name")
        if not isinstance(name, str) or not name:
            raise ProvisionError("Channel payload missing non-empty 'name'")
        if name in existing:
            channel_id = existing[name].get("id")
            if not isinstance(channel_id, str) or not channel_id:
                raise ProvisionError(f"Existing channel '{name}' has no id")
            if dry_run:
                print(f"[DRY-RUN] update channel: {name} ({channel_id})")
            else:
                _http_json(
                    base_url=base_url,
                    method="PUT",
                    path=f"/api/v1/channels/{channel_id}",
                    timeout=timeout,
                    headers=headers,
                    payload=channel,
                    expected=(200, 204),
                )
            updated += 1
        else:
            if dry_run:
                print(f"[DRY-RUN] create channel: {name}")
            else:
                _http_json(
                    base_url=base_url,
                    method="POST",
                    path="/api/v1/channels",
                    timeout=timeout,
                    headers=headers,
                    payload=channel,
                    expected=(200, 201),
                )
            created += 1
    return created, updated


def _apply_channel_runtime_defaults(
    channels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    smtp_from = os.environ.get("SIGNOZ_EMAILING_FROM", "").strip()
    smtp_address = os.environ.get("SIGNOZ_EMAILING_ADDRESS", "").strip()
    smtp_username = os.environ.get("SIGNOZ_EMAILING_AUTH_USERNAME", "").strip()
    smtp_password = os.environ.get("SIGNOZ_EMAILING_AUTH_PASSWORD", "").strip()
    smtp_hello = os.environ.get("SIGNOZ_SMTP_HELLO", "").strip()

    patched: list[dict[str, Any]] = []
    for channel in channels:
        working = dict(channel)
        email_configs = working.get("email_configs")
        if isinstance(email_configs, list):
            normalized_configs: list[dict[str, Any]] = []
            for cfg in email_configs:
                if not isinstance(cfg, dict):
                    continue
                c = dict(cfg)
                if smtp_from and not c.get("from"):
                    c["from"] = smtp_from
                if smtp_address and not c.get("smarthost"):
                    c["smarthost"] = smtp_address
                if smtp_username and not c.get("auth_username"):
                    c["auth_username"] = smtp_username
                if smtp_password and not c.get("auth_password"):
                    c["auth_password"] = smtp_password
                if smtp_hello and not c.get("hello"):
                    c["hello"] = smtp_hello
                if "require_tls" not in c and smtp_address.endswith(":587"):
                    c["require_tls"] = True
                normalized_configs.append(c)
            working["email_configs"] = normalized_configs

            if smtp_username and not smtp_password:
                print(
                    "[WARN] SIGNOZ_EMAILING_AUTH_PASSWORD is empty. "
                    "Email alerts may fail to send until SMTP auth password is set."
                )

        patched.append(working)
    return patched


def _upsert_rules(
    *,
    base_url: str,
    timeout: float,
    headers: dict[str, str],
    rules: list[dict[str, Any]],
    dry_run: bool,
) -> tuple[int, int]:
    existing = _rule_map(base_url=base_url, timeout=timeout, headers=headers)
    created = 0
    updated = 0
    for rule in rules:
        alert_name = rule.get("alert")
        if not isinstance(alert_name, str) or not alert_name:
            raise ProvisionError("Rule payload missing non-empty 'alert'")
        if alert_name in existing:
            rule_id = existing[alert_name].get("id")
            if not isinstance(rule_id, str) or not rule_id:
                raise ProvisionError(f"Existing rule '{alert_name}' has no id")
            if dry_run:
                print(f"[DRY-RUN] update rule: {alert_name} ({rule_id})")
            else:
                _http_json(
                    base_url=base_url,
                    method="PUT",
                    path=f"/api/v1/rules/{rule_id}",
                    timeout=timeout,
                    headers=headers,
                    payload=rule,
                    expected=(200,),
                )
            updated += 1
        else:
            if dry_run:
                print(f"[DRY-RUN] create rule: {alert_name}")
            else:
                _http_json(
                    base_url=base_url,
                    method="POST",
                    path="/api/v1/rules",
                    timeout=timeout,
                    headers=headers,
                    payload=rule,
                    expected=(200,),
                )
            created += 1
    return created, updated


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ProvisionError(f"Config file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProvisionError(f"Invalid JSON config in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProvisionError(f"Config root must be an object: {path}")
    return payload


def _resolve_env_placeholders(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _resolve_env_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_placeholders(v) for v in value]
    if isinstance(value, str):
        placeholders = _ENV_PLACEHOLDER_RE.findall(value)
        resolved = value
        for name in placeholders:
            env_val = os.environ.get(name, "").strip()
            if not env_val:
                raise ProvisionError(
                    f"Missing required environment variable for provisioning config: {name}"
                )
            resolved = resolved.replace(f"${{{name}}}", env_val)
        return resolved
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SIGNOZ_URL", "http://127.0.0.1:3301"),
        help="SigNoz base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--config",
        default=str(SIGNOZ_ALERTS_CONFIG),
        help="Path to JSON provisioning config (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("SIGNOZ_HTTP_TIMEOUT", "15")),
        help="HTTP timeout seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without mutating SigNoz",
    )
    parser.add_argument(
        "--ensure-pat",
        action="store_true",
        help="When using bearer auth, ensure a PAT exists for automation",
    )
    parser.add_argument(
        "--pat-name",
        default=os.environ.get("SIGNOZ_PAT_NAME", "immoapp-automation"),
        help="PAT name for --ensure-pat (default: %(default)s)",
    )
    parser.add_argument(
        "--pat-role",
        default=os.environ.get("SIGNOZ_PAT_ROLE", "ADMIN"),
        help="PAT role for --ensure-pat (default: %(default)s)",
    )
    parser.add_argument(
        "--write-api-key-file",
        default=os.environ.get("SIGNOZ_WRITE_API_KEY_FILE", ""),
        help="Optional file path to store newly created PAT key",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    base_url = args.base_url.rstrip("/")
    timeout = args.timeout
    config_path = Path(args.config)
    write_key_file = Path(args.write_api_key_file) if args.write_api_key_file else None

    version = _get_version(base_url, timeout)
    setup_completed = bool(version.get("setupCompleted"))
    bootstrap_org_id: str | None = None
    if not setup_completed:
        bootstrap_email = (
            os.environ.get("SIGNOZ_BOOTSTRAP_EMAIL") or os.environ.get("SIGNOZ_EMAIL") or ""
        ).strip()
        bootstrap_password = (
            os.environ.get("SIGNOZ_BOOTSTRAP_PASSWORD") or os.environ.get("SIGNOZ_PASSWORD") or ""
        ).strip()
        if not bootstrap_email or not bootstrap_password:
            raise ProvisionError(
                "SigNoz setup is incomplete. Set SIGNOZ_BOOTSTRAP_EMAIL and "
                "SIGNOZ_BOOTSTRAP_PASSWORD (or SIGNOZ_EMAIL/SIGNOZ_PASSWORD)."
            )
        print("[INFO] SigNoz setup incomplete. Bootstrapping first admin user...")
        bootstrap_org_id = _bootstrap_register(
            base_url=base_url,
            timeout=timeout,
            email=bootstrap_email,
            password=bootstrap_password,
        )
        version = _get_version(base_url, timeout)
        if not bool(version.get("setupCompleted")):
            raise ProvisionError("SigNoz setup is still incomplete after bootstrap")

    auth, _ = _auth_from_env(
        base_url=base_url,
        timeout=timeout,
        org_id_hint=bootstrap_org_id,
    )
    print(f"[INFO] Authenticated using {auth.mode} mode")

    if args.ensure_pat:
        _ensure_pat(
            base_url=base_url,
            timeout=timeout,
            auth=auth,
            pat_name=args.pat_name,
            pat_role=args.pat_role,
            write_key_file=write_key_file,
        )

    cfg = _resolve_env_placeholders(_load_config(config_path))
    channels_raw = cfg.get("channels", [])
    rules_raw = cfg.get("rules", [])
    if not isinstance(channels_raw, list) or not isinstance(rules_raw, list):
        raise ProvisionError("'channels' and 'rules' must be arrays in config")
    channels = [item for item in channels_raw if isinstance(item, dict)]
    rules = [item for item in rules_raw if isinstance(item, dict)]

    created_ch, updated_ch = _upsert_channels(
        base_url=base_url,
        timeout=timeout,
        headers=auth.headers,
        channels=channels,
        dry_run=args.dry_run,
    )
    created_rules, updated_rules = _upsert_rules(
        base_url=base_url,
        timeout=timeout,
        headers=auth.headers,
        rules=rules,
        dry_run=args.dry_run,
    )
    print(
        "[OK] SigNoz provisioning complete. "
        f"channels(created={created_ch}, updated={updated_ch}) "
        f"rules(created={created_rules}, updated={updated_rules})"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProvisionError as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1) from exc
