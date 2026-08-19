"""Tenant resource-usage diagnostics and metrics helpers."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Mapping
from typing import Any

from django.core.cache import caches

from core.runtime.hub_runtime_profile import resolve_hub_runtime_profile
from server.api.throttling import build_throttle_storage_key, parse_rate_limit_window
from server.immoapp_server import settings_api
from server.immoapp_server.business_metrics_governance import record_tenant_usage_gauge
from server.pg.uow import get_uow

logger = logging.getLogger(__name__)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, (str, bytes, bytearray)):
        text = value.strip() if isinstance(value, str) else value
        if not text:
            return None
        return int(value)
    return None


def _row_value(row: object, key: str) -> object | None:
    if isinstance(row, Mapping):
        return row.get(key)
    return getattr(row, key, None)


def _throttle_rates() -> Mapping[str, object]:
    rest_framework = settings_api.REST_FRAMEWORK
    if not isinstance(rest_framework, Mapping):
        return {}
    rates = rest_framework.get("DEFAULT_THROTTLE_RATES", {})
    if not isinstance(rates, Mapping):
        return {}
    return rates


def _global_slot_budget() -> int:
    raw = (os.environ.get("IMMOAPP_MATCH_ALL_GLOBAL_SLOT_BUDGET") or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return max(1, resolve_hub_runtime_profile().effective_limits().max_background_jobs)


def _agency_rate_limit() -> int:
    rates = _throttle_rates()
    rate = str(rates.get("agency", os.environ.get("AGENCY_THROTTLE", "30000/hour")))
    limit, _duration = parse_rate_limit_window(rate)
    return max(1, int(limit))


def _default_cache_client() -> Any | None:
    try:
        cache = caches["default"]
        client = getattr(cache, "client", None)
        if client is None or not hasattr(client, "get_client"):
            return None
        return client.get_client(write=True)
    except Exception:
        return None


def _in_flight_ratio(agency_id: int) -> float:
    try:
        with get_uow().session() as session:
            row = session.execute(
                """
                SELECT COALESCE(SUM(in_flight), 0) AS total
                FROM tenant_work_lease
                WHERE agency_id = %s
                """,
                (int(agency_id),),
            ).fetchone()
    except Exception:
        logger.warning("Failed to compute tenant in-flight ratio", exc_info=True)
        return 0.0
    total = _optional_int(_row_value(row, "total")) or 0
    return min(1.0, max(0.0, float(total) / float(_global_slot_budget())))


def _api_rate_ratio(agency_id: int) -> float:
    client = _default_cache_client()
    if client is None:
        return 0.0
    rate = str(_throttle_rates().get("agency", os.environ.get("AGENCY_THROTTLE", "30000/hour")))
    _limit, duration_seconds = parse_rate_limit_window(rate)
    key = build_throttle_storage_key("agency", f"agency:{int(agency_id)}")
    now_ms = int(time.time() * 1000.0)
    try:
        client.zremrangebyscore(key, 0, now_ms - (duration_seconds * 1000))
        count = int(client.zcard(key))
    except Exception:
        logger.warning("Failed to compute tenant API rate ratio", exc_info=True)
        return 0.0
    return min(1.0, max(0.0, float(count) / float(_agency_rate_limit())))


def compute_tenant_usage(agency_id: int) -> dict[str, float]:
    in_flight_ratio = _in_flight_ratio(int(agency_id))
    api_rate_ratio = _api_rate_ratio(int(agency_id))
    composite_ratio = max(in_flight_ratio, api_rate_ratio)
    record_tenant_usage_gauge(
        int(agency_id),
        composite_ratio=composite_ratio,
        in_flight_ratio=in_flight_ratio,
        api_rate_ratio=api_rate_ratio,
    )
    return {
        "in_flight_ratio": in_flight_ratio,
        "api_rate_ratio": api_rate_ratio,
        "composite_ratio": composite_ratio,
    }


def compute_all_tenant_usage() -> list[dict[str, object]]:
    agency_ids: set[int] = set()
    try:
        with get_uow().session() as session:
            rows = session.execute("""
                SELECT DISTINCT agency_id
                FROM tenant_work_lease
                WHERE agency_id IS NOT NULL
                """).fetchall()
        for row in rows:
            agency_id = _optional_int(_row_value(row, "agency_id"))
            if agency_id is not None:
                agency_ids.add(agency_id)
    except Exception:
        logger.warning("Failed to enumerate tenant usage agencies from leases", exc_info=True)

    client = _default_cache_client()
    if client is not None:
        try:
            for raw_key in client.scan_iter(match="throttle:agency:agency:*"):
                key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
                agency_token = key.rsplit(":", 1)[-1]
                try:
                    agency_ids.add(int(agency_token))
                except ValueError:
                    continue
        except Exception:
            logger.warning(
                "Failed to enumerate tenant usage agencies from throttles", exc_info=True
            )

    results: list[dict[str, object]] = []
    for agency_id in sorted(agency_ids):
        ratios = compute_tenant_usage(int(agency_id))
        results.append({"agency_id": int(agency_id), **ratios})
    return results


__all__ = ["compute_all_tenant_usage", "compute_tenant_usage"]
