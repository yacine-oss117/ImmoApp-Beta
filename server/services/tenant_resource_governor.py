"""Fast shared tenant-budget admission control for expensive work."""

from __future__ import annotations

import logging
import math
import os
import time
from typing import Any

from django.core.cache import caches

from server.immoapp_server.business_metrics_governance import record_tenant_budget_event

logger = logging.getLogger(__name__)

_TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local refill_per_minute = tonumber(ARGV[2])
local burst = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local current = redis.call('HMGET', key, 'tokens', 'updated_ms')
local tokens = tonumber(current[1])
local updated_ms = tonumber(current[2])
if not tokens then
    tokens = burst
    updated_ms = now_ms
end
if now_ms > updated_ms and refill_per_minute > 0 then
    local refill_per_ms = refill_per_minute / 60000.0
    tokens = math.min(burst, tokens + ((now_ms - updated_ms) * refill_per_ms))
    updated_ms = now_ms
end
local allowed = 0
local retry_ms = 0
if tokens >= cost then
    tokens = tokens - cost
    allowed = 1
elseif refill_per_minute > 0 then
    local missing = cost - tokens
    retry_ms = math.ceil((missing / (refill_per_minute / 60000.0)))
end
redis.call('HMSET', key, 'tokens', tokens, 'updated_ms', updated_ms)
redis.call('PEXPIRE', key, 3600000)
return {allowed, tokens, retry_ms}
"""


def _env_int(name: str, default: int, *, min_v: int, max_v: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_v, min(max_v, value))


def _default_cache_client() -> Any | None:
    try:
        cache = caches["default"]
        client = getattr(cache, "client", None)
        if client is None or not hasattr(client, "get_client"):
            return None
        return client.get_client(write=True)
    except Exception:
        return None


def governor_backend_available() -> bool:
    return _default_cache_client() is not None


def _budget_key(budget_name: str, agency_id: int) -> str:
    return f"tenant_budget:{str(budget_name or 'default')}:{int(agency_id)}"


def _refill_per_minute() -> int:
    return _env_int("IMMOAPP_TENANT_BG_TOKEN_REFILL_PER_MINUTE", 6, min_v=1, max_v=600)


def _burst() -> int:
    return _env_int("IMMOAPP_TENANT_BG_TOKEN_BURST", 3, min_v=1, max_v=128)


def allow_expensive_work(*, budget_name: str, agency_id: int, cost: int = 1) -> tuple[bool, int]:
    client = _default_cache_client()
    if client is None:
        record_tenant_budget_event(budget_name, "fail_open", int(agency_id))
        return True, 0
    now_ms = int(time.time() * 1000.0)
    try:
        result = client.eval(
            _TOKEN_BUCKET_SCRIPT,
            1,
            _budget_key(budget_name, int(agency_id)),
            now_ms,
            _refill_per_minute(),
            _burst(),
            max(1, int(cost)),
        )
        allowed = bool(int(result[0])) if isinstance(result, (list, tuple)) and result else True
        retry_after = (
            max(1, int(math.ceil(float(result[2]) / 1000.0)))
            if isinstance(result, (list, tuple)) and len(result) >= 3 and int(result[2] or 0) > 0
            else 0
        )
        record_tenant_budget_event(
            budget_name,
            "allowed" if allowed else "backpressured",
            int(agency_id),
        )
        return allowed, retry_after
    except Exception:
        logger.warning("Tenant resource governor unavailable; failing open", exc_info=True)
        record_tenant_budget_event(budget_name, "fail_open", int(agency_id))
        return True, 0


def note_work_completed(*, budget_name: str, agency_id: int, cost: int = 1) -> None:
    _ = cost
    record_tenant_budget_event(budget_name, "completed", int(agency_id))


def budget_state_snapshot(
    *,
    agency_ids: list[int] | tuple[int, ...],
    budget_names: list[str] | tuple[str, ...],
) -> dict[str, object]:
    client = _default_cache_client()
    payload: dict[str, object] = {
        "available": client is not None,
        "budgets": {},
    }
    if client is None:
        return payload

    budgets: dict[str, object] = {}
    for budget_name in budget_names:
        by_agency: dict[str, object] = {}
        for agency_id in agency_ids:
            if int(agency_id) <= 0:
                continue
            try:
                raw = client.hgetall(_budget_key(str(budget_name), int(agency_id))) or {}
                tokens_raw = raw.get(b"tokens") if isinstance(raw, dict) else None
                updated_raw = raw.get(b"updated_ms") if isinstance(raw, dict) else None
                tokens = (
                    float(tokens_raw.decode("utf-8")) if isinstance(tokens_raw, bytes) else None
                )
                updated_ms = (
                    int(updated_raw.decode("utf-8")) if isinstance(updated_raw, bytes) else None
                )
            except Exception:
                tokens = None
                updated_ms = None
            by_agency[str(int(agency_id))] = {
                "tokens": tokens,
                "updated_ms": updated_ms,
            }
        budgets[str(budget_name)] = by_agency
    payload["budgets"] = budgets
    return payload


__all__ = [
    "allow_expensive_work",
    "budget_state_snapshot",
    "governor_backend_available",
    "note_work_completed",
]
