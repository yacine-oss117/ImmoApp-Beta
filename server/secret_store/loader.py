from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from core.env_files import resolve_env_file

from .openbao import OpenBaoError, fetch_secret_data
from .required_keys import DEFAULT_OPENBAO_REQUIRED_KEYS

logger = logging.getLogger(__name__)

_DEFAULT_ALLOWLIST = ("ALE_", "DJANGO_", "IMMOAPP_")
_LAST_STATUS: dict[str, object] = {
    "backend": "openbao",
    "enabled": False,
    "loaded": 0,
    "required": False,
    "strict_openbao": True,
    "production_mode": False,
    "required_keys": [],
    "error": None,
}
_ENV_LOADED = False


def _load_env_once() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    repo_root = Path(__file__).resolve().parents[2]
    base_dir = repo_root / "server"
    env_path = resolve_env_file(repo_root, base_dir)
    if env_path.exists():
        load_dotenv(env_path, override=False)
    _ENV_LOADED = True


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_production_mode() -> bool:
    env_mode = os.environ.get("IMMOAPP_ENV", "").strip().lower()
    if env_mode in {"prod", "production"}:
        return True
    if env_mode in {"dev", "development", "local", "test", "ci"}:
        return False
    debug_value = os.environ.get("DJANGO_DEBUG")
    if debug_value is not None:
        return not _is_truthy(debug_value)
    # Fail secure: ambiguous environment is treated as production.
    return True


def _parse_allowlist(raw: str | None) -> list[str]:
    if not raw:
        return list(_DEFAULT_ALLOWLIST)
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


def _parse_required_keys(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _strict_openbao_only() -> bool:
    # Fail-secure by default: OpenBao is mandatory unless break-glass is explicit.
    return not _is_truthy(os.environ.get("IMMOAPP_ALLOW_ENV_SECRETS"))


def _validate_openbao_auth_policy(*, production_mode: bool) -> None:
    strict_runtime = _strict_openbao_only()
    enforce_plaintext_ban = production_mode or strict_runtime
    if not enforce_plaintext_ban:
        return
    if _is_truthy(os.environ.get("IMMOAPP_ALLOW_PLAINTEXT_BAO_TOKEN")):
        return

    plain_token = os.environ.get("BAO_TOKEN", "").strip()
    token_file = os.environ.get("BAO_TOKEN_FILE", "").strip()
    approle_file = os.environ.get("BAO_APPROLE_FILE", "").strip()
    has_approle = bool(
        os.environ.get("BAO_ROLE_ID", "").strip() and os.environ.get("BAO_SECRET_ID", "").strip()
    )

    if plain_token:
        raise RuntimeError(
            "Plain BAO_TOKEN in runtime env is not allowed when OpenBao-only policy is active. "
            "Use BAO_TOKEN_FILE or AppRole credentials."
        )
    if not token_file and not has_approle and not approle_file:
        raise RuntimeError(
            "OpenBao auth is not configured for production. "
            "Set BAO_TOKEN_FILE, BAO_APPROLE_FILE, or BAO_ROLE_ID/BAO_SECRET_ID."
        )


def _has_any_master_key() -> bool:
    if os.environ.get("ALE_MASTER_KEYS"):
        return True
    if os.environ.get("ALE_MASTER_KEY"):
        return True
    for env_key, env_val in os.environ.items():
        if env_key.startswith("ALE_MASTER_KEY_V") and env_val:
            return True
    return False


def _require_keys(required_keys: list[str]) -> None:
    missing: list[str] = []
    for key in required_keys:
        if key == "ALE_MASTER_KEY":
            if not _has_any_master_key():
                missing.append("ALE_MASTER_KEY*")
            continue
        if key.endswith("*"):
            prefix = key[:-1]
            if not any(
                env_key.startswith(prefix) and os.environ.get(env_key) for env_key in os.environ
            ):
                missing.append(key)
            continue
        if not os.environ.get(key):
            missing.append(key)
    if missing:
        raise RuntimeError(f"Missing required secrets: {', '.join(missing)}")


def _apply_secrets(
    secrets: dict[str, Any],
    *,
    overwrite: bool,
    allowlist: list[str],
) -> dict[str, str]:
    applied: dict[str, str] = {}
    for key, value in secrets.items():
        if not isinstance(key, str):
            continue
        if not _allowed(key, allowlist):
            continue
        if not overwrite and os.environ.get(key):
            continue
        os.environ[key] = str(value)
        applied[key] = str(value)
    return applied


def load_secrets() -> dict[str, str]:
    _load_env_once()
    backend = os.environ.get("IMMOAPP_SECRETS_BACKEND", "openbao").strip().lower()
    strict_openbao = _strict_openbao_only()
    production_mode = _is_production_mode()
    required = (
        _is_truthy(os.environ.get("IMMOAPP_SECRETS_REQUIRED")) or production_mode or strict_openbao
    )
    required_keys = _parse_required_keys(os.environ.get("IMMOAPP_SECRETS_REQUIRED_KEYS"))
    if backend in {"", "env", "none"}:
        if required:
            raise RuntimeError(
                "OpenBao-only policy active. Set IMMOAPP_SECRETS_BACKEND=openbao "
                "or explicitly enable break-glass with IMMOAPP_ALLOW_ENV_SECRETS=1."
            )
        _LAST_STATUS.update(
            {
                "backend": "env",
                "enabled": False,
                "loaded": 0,
                "required": required,
                "strict_openbao": strict_openbao,
                "production_mode": production_mode,
                "required_keys": required_keys,
                "error": None,
            }
        )
        logger.info("Secrets backend: env (disabled). OpenBao inactive.")
        return {}

    allowlist = _parse_allowlist(os.environ.get("IMMOAPP_SECRETS_ALLOWLIST"))
    overwrite = os.environ.get("IMMOAPP_SECRETS_OVERWRITE", "1") == "1"

    if backend != "openbao":
        if required:
            raise RuntimeError(f"Unsupported secrets backend: {backend}")
        logger.warning("Unsupported secrets backend: %s", backend)
        _LAST_STATUS.update(
            {
                "backend": backend,
                "enabled": False,
                "loaded": 0,
                "required": required,
                "strict_openbao": strict_openbao,
                "production_mode": production_mode,
                "required_keys": required_keys,
                "error": f"Unsupported backend: {backend}",
            }
        )
        return {}

    _validate_openbao_auth_policy(production_mode=production_mode)

    path = os.environ.get("IMMOAPP_SECRETS_PATH", "secret/data/immoapp")
    try:
        secrets = fetch_secret_data(path)
    except OpenBaoError as exc:
        _LAST_STATUS.update(
            {
                "backend": backend,
                "enabled": True,
                "loaded": 0,
                "required": required,
                "strict_openbao": strict_openbao,
                "production_mode": production_mode,
                "required_keys": required_keys,
                "error": str(exc),
            }
        )
        if required:
            raise
        logger.warning("OpenBao secrets load failed: %s", exc)
        return {}

    applied = _apply_secrets(secrets, overwrite=overwrite, allowlist=allowlist)
    logger.info("Loaded %s secrets from OpenBao (%s)", len(applied), path)

    if required:
        if not required_keys:
            required_keys = list(DEFAULT_OPENBAO_REQUIRED_KEYS)
        _require_keys(required_keys)
        if strict_openbao:
            # Required keys must come from OpenBao payload, not inherited env.
            missing_from_openbao: list[str] = []
            applied_keys = set(applied.keys())
            for key in required_keys:
                if key == "ALE_MASTER_KEY":
                    if "ALE_MASTER_KEY" in applied_keys:
                        continue
                    if any(k.startswith("ALE_MASTER_KEY_V") for k in applied_keys):
                        continue
                    missing_from_openbao.append("ALE_MASTER_KEY*")
                    continue
                if key.endswith("*"):
                    prefix = key[:-1]
                    if not any(k.startswith(prefix) for k in applied_keys):
                        missing_from_openbao.append(key)
                    continue
                if key not in applied_keys:
                    missing_from_openbao.append(key)
            if missing_from_openbao:
                raise RuntimeError(
                    "OpenBao-only policy requires required keys to be loaded from OpenBao: "
                    + ", ".join(missing_from_openbao)
                )
    _LAST_STATUS.update(
        {
            "backend": backend,
            "enabled": True,
            "loaded": len(applied),
            "required": required,
            "strict_openbao": strict_openbao,
            "production_mode": production_mode,
            "required_keys": required_keys,
            "error": None,
        }
    )
    logger.info(
        "Secrets backend: %s (enabled). Required=%s, loaded=%s.",
        backend,
        required,
        len(applied),
    )
    logger.info("OpenBao secrets active.")
    return applied


def get_secrets_status() -> dict[str, object]:
    return dict(_LAST_STATUS)
