"""ALE search-key helpers for Postgres UoW."""

from __future__ import annotations

import hmac
import os
import re
import threading
import time
from functools import lru_cache
from hashlib import sha256

import psycopg

from .uow_internal_env import _load_env

_KEY_VERSION_RE = re.compile(r"^v\d+$")
_SEARCH_KEY_VERSION_CACHE_LOCK = threading.Lock()
_SEARCH_KEY_VERSION_CACHE: tuple[float, tuple[str | None, str | None]] | None = None
RowMapping = dict[str, object]
PgConn = psycopg.Connection[RowMapping]


def _meta_key_version_cache_ttl_seconds() -> float:
    raw = os.environ.get("IMMOAPP_ALE_SEARCH_KEY_META_CACHE_TTL_SECONDS", "30").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 30.0
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return 0.0
    return max(0.0, min(value, 300.0))


def _normalize_search_key_version(raw: str | None, *, default: str) -> str:
    value = (raw or "").strip().lower()
    if not value:
        return default
    if not _KEY_VERSION_RE.match(value):
        return default
    return value


def _read_meta_key_versions(conn: PgConn) -> tuple[str | None, str | None]:
    """Read (current, previous) search-key versions from meta if available."""
    try:
        row = conn.execute("SELECT to_regclass('public.meta') AS meta_reg").fetchone()
        if not row or not row.get("meta_reg"):
            return None, None
        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key IN (%s, %s)",
            ("ale_search_key_version", "ale_search_key_prev_version"),
        ).fetchall()
        values = {
            str(r["key"]): str(r["value"])
            for r in rows
            if r.get("key") and r.get("value") is not None
        }
        return values.get("ale_search_key_version"), values.get("ale_search_key_prev_version")
    except Exception:
        return None, None


def _resolve_meta_key_versions_cached(conn: PgConn) -> tuple[str | None, str | None]:
    global _SEARCH_KEY_VERSION_CACHE
    ttl = _meta_key_version_cache_ttl_seconds()
    if ttl <= 0.0:
        return _read_meta_key_versions(conn)
    now = time.monotonic()
    with _SEARCH_KEY_VERSION_CACHE_LOCK:
        cached = _SEARCH_KEY_VERSION_CACHE
        if cached is not None and cached[0] > now:
            return cached[1]
    resolved = _read_meta_key_versions(conn)
    with _SEARCH_KEY_VERSION_CACHE_LOCK:
        _SEARCH_KEY_VERSION_CACHE = (time.monotonic() + ttl, resolved)
    return resolved


def _resolve_search_key_versions(conn: PgConn) -> tuple[str, str | None]:
    env_current = _normalize_search_key_version(
        os.environ.get("ALE_SEARCH_KEY_VERSION"),
        default="v1",
    )
    env_prev = _normalize_search_key_version(
        os.environ.get("ALE_SEARCH_KEY_PREVIOUS_VERSION"),
        default="",
    )
    meta_current_raw, meta_prev_raw = _resolve_meta_key_versions_cached(conn)
    current = _normalize_search_key_version(meta_current_raw, default=env_current)
    prev = _normalize_search_key_version(meta_prev_raw, default=env_prev)
    if not prev or prev == current:
        return current, None
    return current, prev


@lru_cache(maxsize=1024)
def _cached_ale_search_secret(agency_id: int | None, version: str) -> str:
    _load_env()
    secret = os.environ.get("ALE_SEARCH_SECRET_MASTER") or os.environ.get("ALE_SEARCH_SECRET")
    if not secret:
        raise RuntimeError(
            "ALE_SEARCH_SECRET_MASTER (or ALE_SEARCH_SECRET) must be set (fail-secure policy)."
        )
    if agency_id is None:
        tenant_scope = "global"
    else:
        tenant_scope = f"agency:{agency_id}"
    if version == "v1":
        message = tenant_scope
    else:
        message = f"{tenant_scope}:search:{version}"
    derived = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        sha256,
    ).hexdigest()
    return derived


def _resolve_ale_search_secret(agency_id: int | None, *, version: str) -> str:
    return _cached_ale_search_secret(agency_id, version)


def _resolve_ale_trigram_limit() -> str:
    _load_env()
    raw = (os.environ.get("ALE_TRIGRAM_LIMIT") or "").strip()
    if not raw:
        return "128"
    try:
        value = int(raw)
    except ValueError:
        return "128"
    if value < 16:
        value = 16
    if value > 512:
        value = 512
    return str(value)


__all__ = [
    "_resolve_ale_search_secret",
    "_resolve_ale_trigram_limit",
    "_resolve_search_key_versions",
]
