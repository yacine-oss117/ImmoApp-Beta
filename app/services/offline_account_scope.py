"""Account-scoped filesystem roots for durable offline mutation replay."""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from app.core_app.paths import get_app_data_dir
from app.services.api_client_auth import get_access_token, peek_access_token
from app.services.api_client_utils import decode_jwt_claims
from app.services.api_config import get_api_base_url

from .offline_store_utils import read_json, write_json_atomic

_OFFLINE_ROOT = "offline_sync"
_CURRENT_SCOPE_FILE = "current_account.json"
_LEGACY_QUARANTINE = "legacy_quarantine"
_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OfflineAccountScope:
    account_key: str
    api_base: str
    agency_id: int
    user_id: int
    account_dir: str
    role: str = ""
    is_owner: bool = False


@dataclass(frozen=True)
class AccountScopePayload:
    api_base: str
    agency_id: int
    user_id: int
    role: str
    is_owner: bool


def _offline_root() -> Path:
    root = get_app_data_dir() / _OFFLINE_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root


def _current_scope_path() -> Path:
    return _offline_root() / _CURRENT_SCOPE_FILE


def _parse_positive_int(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            parsed = int(text)
            return parsed if parsed > 0 else None
    return None


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _build_account_key(api_base: str, agency_id: int, user_id: int) -> str:
    return f"{api_base}|{agency_id}|{user_id}"


def _account_dir_name(account_key: str) -> str:
    digest = hashlib.sha256(account_key.encode("utf-8")).hexdigest()[:16]
    base, agency, user = account_key.split("|", 2)
    host = _SAFE_SEGMENT.sub("_", base.replace("https://", "").replace("http://", "")).strip("_")
    prefix = f"{host}_{agency}_{user}"[:48].strip("_") or "account"
    return f"{prefix}_{digest}"


def _scope_to_dict(scope: OfflineAccountScope) -> dict[str, object]:
    return {
        "account_key": scope.account_key,
        "api_base": scope.api_base,
        "agency_id": scope.agency_id,
        "user_id": scope.user_id,
        "account_dir": scope.account_dir,
        "role": scope.role,
        "is_owner": scope.is_owner,
    }


def _scope_from_dict(payload: object) -> OfflineAccountScope | None:
    if not isinstance(payload, dict):
        return None
    api_base = str(payload.get("api_base") or "").strip()
    agency_id = _parse_positive_int(payload.get("agency_id"))
    user_id = _parse_positive_int(payload.get("user_id"))
    account_key = str(payload.get("account_key") or "").strip()
    account_dir = str(payload.get("account_dir") or "").strip()
    role = str(payload.get("role") or "").strip()
    is_owner = _parse_bool(payload.get("is_owner"))
    if not api_base or agency_id is None or user_id is None:
        return None
    if not account_key:
        account_key = _build_account_key(api_base, agency_id, user_id)
    if not account_dir:
        account_dir = _account_dir_name(account_key)
    return OfflineAccountScope(
        account_key=account_key,
        api_base=api_base,
        agency_id=agency_id,
        user_id=user_id,
        account_dir=account_dir,
        role=role,
        is_owner=is_owner,
    )


def _persist_current_scope(scope: OfflineAccountScope) -> None:
    write_json_atomic(_current_scope_path(), _scope_to_dict(scope))


def clear_persisted_account_scope() -> None:
    try:
        _current_scope_path().unlink(missing_ok=True)
    except OSError:
        pass


def _read_persisted_scope() -> OfflineAccountScope | None:
    return _scope_from_dict(read_json(_current_scope_path(), {}))


def _scope_payload_from_claims(
    *,
    api_base: str,
    claims: Mapping[str, object],
) -> AccountScopePayload | None:
    agency_id = _parse_positive_int(claims.get("agency_id"))
    user_id = _parse_positive_int(claims.get("user_id") or claims.get("sub"))
    if not api_base or agency_id is None or user_id is None:
        return None
    return AccountScopePayload(
        api_base=api_base,
        agency_id=agency_id,
        user_id=user_id,
        role=str(claims.get("role") or "").strip(),
        is_owner=_parse_bool(claims.get("is_owner")),
    )


def persist_account_scope(payload: AccountScopePayload) -> OfflineAccountScope:
    account_key = _build_account_key(payload.api_base, payload.agency_id, payload.user_id)
    scope = OfflineAccountScope(
        account_key=account_key,
        api_base=payload.api_base,
        agency_id=payload.agency_id,
        user_id=payload.user_id,
        account_dir=_account_dir_name(account_key),
        role=payload.role,
        is_owner=payload.is_owner,
    )
    _persist_current_scope(scope)
    return scope


def sync_account_scope_from_token(token: str | None) -> OfflineAccountScope | None:
    api_base = str(get_api_base_url() or "").strip()
    if not api_base or not token:
        return None
    claims = decode_jwt_claims(token)
    if not isinstance(claims, dict):
        return None
    payload = _scope_payload_from_claims(api_base=api_base, claims=claims)
    if payload is None:
        return None
    return persist_account_scope(payload)


def get_active_account_scope(*, allow_network: bool = False) -> OfflineAccountScope | None:
    api_base = str(get_api_base_url() or "").strip()
    token = peek_access_token()
    if token is None and allow_network:
        try:
            token = get_access_token()
        except Exception:
            logger.debug("Skipping network-backed account scope resolution", exc_info=True)
            token = None
    claims = decode_jwt_claims(token) if token else None
    if api_base and isinstance(claims, dict):
        payload = _scope_payload_from_claims(api_base=api_base, claims=claims)
        if payload is not None:
            return persist_account_scope(payload)
    persisted_scope = _read_persisted_scope()
    if persisted_scope is None:
        return None
    if api_base and persisted_scope.api_base != api_base:
        return None
    return persisted_scope


def require_active_account_scope() -> OfflineAccountScope:
    scope = get_active_account_scope()
    if scope is None:
        raise RuntimeError("Authenticated account scope is unavailable for offline sync.")
    return scope


def get_account_root(scope: OfflineAccountScope | None = None) -> Path:
    resolved = scope if scope is not None else require_active_account_scope()
    root = _offline_root() / resolved.account_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def legacy_quarantine_root() -> Path:
    path = _offline_root() / _LEGACY_QUARANTINE
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_compatibility_scope() -> OfflineAccountScope:
    scope = get_active_account_scope()
    if scope is not None:
        return scope
    api_base = str(get_api_base_url() or "local").strip() or "local"
    account_key = _build_account_key(api_base, 0, 0)
    return OfflineAccountScope(
        account_key=account_key,
        api_base=api_base,
        agency_id=0,
        user_id=0,
        account_dir=_account_dir_name(account_key),
    )


def quarantine_legacy_api_queue_files() -> list[Path]:
    root = get_app_data_dir() / "api_write_queue"
    moved: list[Path] = []
    if not root.exists():
        return moved
    quarantine_root = legacy_quarantine_root()
    for name in ("pending_mutations.json", "failed_mutations.json"):
        path = root / name
        if not path.exists():
            continue
        target = quarantine_root / f"{path.stem}.{path.suffix.lstrip('.') or 'json'}"
        try:
            index = 0
            candidate = target
            while candidate.exists():
                index += 1
                candidate = (
                    quarantine_root / f"{path.stem}.{index}.{path.suffix.lstrip('.') or 'json'}"
                )
            shutil.move(str(path), str(candidate))
            moved.append(candidate)
        except OSError:
            continue
    return moved


__all__ = [
    "AccountScopePayload",
    "OfflineAccountScope",
    "clear_persisted_account_scope",
    "get_compatibility_scope",
    "get_account_root",
    "get_active_account_scope",
    "quarantine_legacy_api_queue_files",
    "legacy_quarantine_root",
    "persist_account_scope",
    "require_active_account_scope",
    "sync_account_scope_from_token",
]
