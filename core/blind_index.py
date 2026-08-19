"""
Deterministic blind-index helpers (non-trigram).
"""

from __future__ import annotations

import hmac
import os
import re
from hashlib import sha256

from core.utils.common import norm_text

_VERSION_RE = re.compile(r"^v\d+$")


def _master_search_secret() -> str:
    secret = os.environ.get("ALE_SEARCH_SECRET_MASTER") or os.environ.get("ALE_SEARCH_SECRET")
    if secret:
        return secret
    raise RuntimeError(
        "ALE_SEARCH_SECRET_MASTER (or ALE_SEARCH_SECRET) must be set (fail-secure policy)."
    )


def _normalize_key_version(raw: str | None, *, default: str) -> str:
    value = (raw or "").strip().lower()
    if not value:
        return default
    if not _VERSION_RE.match(value):
        return default
    return value


def get_search_key_version() -> str:
    return _normalize_key_version(os.environ.get("ALE_SEARCH_KEY_VERSION"), default="v1")


def get_previous_search_key_version() -> str | None:
    prev = _normalize_key_version(
        os.environ.get("ALE_SEARCH_KEY_PREVIOUS_VERSION"),
        default="",
    )
    if not prev:
        return None
    current = get_search_key_version()
    return None if prev == current else prev


def _derive_tenant_secret(master_secret: str, agency_id: int | None, *, version: str) -> str:
    if agency_id is None:
        tenant_scope = "global"
    else:
        tenant_scope = f"agency:{agency_id}"
    # Backward-compatibility for existing v1 hashes.
    if version == "v1":
        message = tenant_scope
    else:
        message = f"{tenant_scope}:search:{version}"
    digest = hmac.new(
        master_secret.encode("utf-8"),
        message.encode("utf-8"),
        sha256,
    ).hexdigest()
    return digest


def _resolve_agency_id(agency_id: int | None) -> int | None:
    try:
        from server.pg.tenant_context import resolve_agency_id as resolve_tenant_agency_id

        current = resolve_tenant_agency_id(explicit=agency_id)
        if current is not None:
            return current
    except Exception:
        return None
    return None


def get_search_secret(*, agency_id: int | None = None, version: str | None = None) -> str:
    """
    Return the blind-index secret.

    - Derive by tenant + key version.
    - Version defaults to `ALE_SEARCH_KEY_VERSION` (default `v1`).
    """
    master = _master_search_secret()
    key_version = _normalize_key_version(version, default=get_search_key_version())
    return _derive_tenant_secret(master, _resolve_agency_id(agency_id), version=key_version)


def get_search_secret_set(*, agency_id: int | None = None) -> list[str]:
    """
    Return search secrets in priority order: current first, optional previous second.

    This is used for zero-downtime rotation windows where both old and new
    search keys must match existing rows.
    """
    current = get_search_key_version()
    versions = [current]
    previous = get_previous_search_key_version()
    if previous:
        versions.append(previous)
    secrets: list[str] = []
    for ver in versions:
        secret = get_search_secret(agency_id=agency_id, version=ver)
        if secret not in secrets:
            secrets.append(secret)
    return secrets


def blind_index(text: str) -> str:
    normalized = norm_text(text)
    digest = hmac.new(get_search_secret().encode("utf-8"), normalized.encode("utf-8"), sha256)
    return digest.hexdigest()[:32]


def blind_index_for_agency(text: str, *, agency_id: int) -> str:
    normalized = norm_text(text)
    digest = hmac.new(
        get_search_secret(agency_id=int(agency_id)).encode("utf-8"),
        normalized.encode("utf-8"),
        sha256,
    )
    return digest.hexdigest()[:32]


def blind_index_for_write(text: str, *, agency_id: int | None = None) -> str:
    agency_id = _resolve_agency_id(agency_id)
    if agency_id is None:
        raise RuntimeError("Missing tenant context: agency_id is required for write blind index")
    return blind_index_for_agency(text, agency_id=agency_id)


__all__ = [
    "blind_index",
    "blind_index_for_agency",
    "blind_index_for_write",
    "get_search_key_version",
    "get_previous_search_key_version",
    "get_search_secret",
    "get_search_secret_set",
]
