"""
Custom throttles that expose rate-limit headers.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, cast

from django.core.cache import caches
from rest_framework.throttling import (
    AnonRateThrottle,
    ScopedRateThrottle,
    SimpleRateThrottle,
    UserRateThrottle,
)

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView

logger = logging.getLogger(__name__)

_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now_ms - window_ms)
local count = redis.call('ZCARD', key)
local allowed = 0
if count < limit then
    redis.call('ZADD', key, now_ms, member)
    redis.call('PEXPIRE', key, window_ms)
    count = count + 1
    allowed = 1
end
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local oldest_ms = 0
if oldest[2] then
    oldest_ms = tonumber(oldest[2])
end
return {allowed, count, oldest_ms}
"""

_SLIDING_WINDOW_PAIR_SCRIPT = """
local function eval_window(key, now_ms, window_ms, limit, member)
    if not key or key == '' or limit <= 0 then
        return 1, 0, now_ms
    end
    redis.call('ZREMRANGEBYSCORE', key, 0, now_ms - window_ms)
    local count = redis.call('ZCARD', key)
    local allowed = 0
    if count < limit then
        redis.call('ZADD', key, now_ms, member)
        redis.call('PEXPIRE', key, window_ms)
        count = count + 1
        allowed = 1
    end
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local oldest_ms = now_ms
    if oldest[2] then
        oldest_ms = tonumber(oldest[2])
    end
    return allowed, count, oldest_ms
end

local now_ms = tonumber(ARGV[1])
local allowed1, count1, oldest1 = eval_window(
    KEYS[1],
    now_ms,
    tonumber(ARGV[2]),
    tonumber(ARGV[3]),
    ARGV[4]
)
local allowed2, count2, oldest2 = eval_window(
    KEYS[2],
    now_ms,
    tonumber(ARGV[5]),
    tonumber(ARGV[6]),
    ARGV[7]
)
return {allowed1, count1, oldest1, allowed2, count2, oldest2}
"""


def parse_rate_limit_window(rate: str) -> tuple[int, int]:
    value, period = rate.split("/", 1)
    num_requests = max(1, int(value))
    period_token = period.strip().lower()
    duration = {
        "s": 1,
        "sec": 1,
        "second": 1,
        "m": 60,
        "min": 60,
        "minute": 60,
        "h": 60 * 60,
        "hour": 60 * 60,
        "d": 60 * 60 * 24,
        "day": 60 * 60 * 24,
    }.get(period_token[:1], 60)
    if period_token.startswith("sec"):
        duration = 1
    elif period_token.startswith("min"):
        duration = 60
    elif period_token.startswith("hour"):
        duration = 60 * 60
    elif period_token.startswith("day"):
        duration = 60 * 60 * 24
    return num_requests, duration


def build_throttle_storage_key(scope: str, ident: str) -> str:
    return f"throttle:{str(scope or 'default')}:{str(ident or 'unknown')}"


def _resolve_user_ident(request: Request) -> str | None:
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        user_id = getattr(user, "pk", None) or getattr(user, "id", None)
        if user_id is not None:
            return f"user:{int(user_id)}"
    remote_addr = str(request.META.get("REMOTE_ADDR", "") or "").strip()
    if remote_addr:
        return f"ip:{remote_addr}"
    return None


def _resolve_agency_ident(request: Request) -> str | None:
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        agency_id = getattr(user, "agency_id", None)
        if agency_id is None:
            agency = getattr(user, "agency", None)
            if agency is not None:
                agency_id = getattr(agency, "id", None)
        if agency_id is not None:
            return f"agency:{int(agency_id)}"
    return _resolve_user_ident(request)


def _default_cache_client() -> Any | None:
    try:
        cache = caches["default"]
        client = getattr(cache, "client", None)
        if client is None or not hasattr(client, "get_client"):
            return None
        return client.get_client(write=True)
    except Exception:
        return None


def _scope_limits(scope: str) -> tuple[int, int]:
    from rest_framework.settings import api_settings

    rate = str(api_settings.DEFAULT_THROTTLE_RATES.get(scope) or "").strip()
    if not rate:
        return 0, 0
    return parse_rate_limit_window(rate)


def _store_rate_limit_headers(request: Request, *, limit: int, remaining: int, reset: int) -> None:
    entries = getattr(request, "_rate_limit_headers", [])
    entries.append(
        {
            "limit": limit,
            "remaining": max(remaining, 0),
            "reset": reset,
        }
    )
    request._rate_limit_headers = entries


class _HeaderThrottleMixin:
    """Mixin to capture throttle state for response headers."""

    def allow_request(self, request: Request, view: APIView) -> bool:
        super_obj = cast(Any, super())
        allowed = super_obj.allow_request(request, view)
        allowed_bool = cast(bool, allowed)
        limit = getattr(self, "num_requests", 0) or 0
        history = getattr(self, "history", []) or []
        remaining = limit - len(history)
        now = getattr(self, "now", 0)
        duration = getattr(self, "duration", 0)
        reset = int(now + duration) if duration else 0
        if limit:
            _store_rate_limit_headers(request, limit=limit, remaining=remaining, reset=reset)
        return allowed_bool


class _SlidingWindowMixin:
    """Valkey-backed sliding window throttle with fail-open semantics."""

    _throttle_retry_after: float | None = None

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        raise NotImplementedError

    def _get_storage_key(self, request: Request, view: APIView) -> str | None:
        cache_key = self.get_cache_key(request, view)
        if cache_key is None:
            return None
        return str(cache_key)

    def _sliding_allow_request(
        self,
        *,
        key: str,
        num_requests: int,
        duration: int,
    ) -> tuple[bool, int, float]:
        client = _default_cache_client()
        if client is None:
            raise RuntimeError("default cache client is unavailable")
        now_ms = int(time.time() * 1000.0)
        window_ms = max(1000, int(duration) * 1000)
        member = f"{now_ms}:{uuid.uuid4().hex}"
        result = client.eval(
            _SLIDING_WINDOW_SCRIPT,
            1,
            key,
            now_ms,
            window_ms,
            max(1, int(num_requests)),
            member,
        )
        allowed = (
            bool(int(result[0])) if isinstance(result, (list, tuple)) and len(result) >= 1 else True
        )
        count_after = (
            int(result[1]) if isinstance(result, (list, tuple)) and len(result) >= 2 else 0
        )
        oldest_ms = (
            int(float(result[2]))
            if isinstance(result, (list, tuple)) and len(result) >= 3
            else now_ms
        )
        reset_after = max(0.0, ((oldest_ms + window_ms) - now_ms) / 1000.0)
        return allowed, count_after, reset_after

    def _paired_allow_request(self, request: Request) -> tuple[bool, int, float] | None:
        user = getattr(request, "user", None)
        if not (user and getattr(user, "is_authenticated", False)):
            return None
        cached = getattr(request, "_paired_sliding_window", None)
        if isinstance(cached, dict):
            scope_name = str(getattr(self, "scope", "") or "")
            result = cached.get(scope_name)
            if isinstance(result, tuple) and len(result) == 3:
                return result
        agency_ident = _resolve_agency_ident(request)
        user_ident = _resolve_user_ident(request)
        if agency_ident is None or user_ident is None:
            return None
        agency_limit, agency_duration = _scope_limits("agency")
        user_limit, user_duration = _scope_limits("user")
        if agency_limit <= 0 or agency_duration <= 0 or user_limit <= 0 or user_duration <= 0:
            return None
        client = _default_cache_client()
        if client is None:
            raise RuntimeError("default cache client is unavailable")
        now_ms = int(time.time() * 1000.0)
        base_member = uuid.uuid4().hex
        try:
            result = client.eval(
                _SLIDING_WINDOW_PAIR_SCRIPT,
                2,
                build_throttle_storage_key("agency", agency_ident),
                build_throttle_storage_key("user", user_ident),
                now_ms,
                max(1000, agency_duration * 1000),
                agency_limit,
                f"{now_ms}:{base_member}:agency",
                max(1000, user_duration * 1000),
                user_limit,
                f"{now_ms}:{base_member}:user",
            )
        except TypeError:
            return None
        parsed = {
            "agency": self._parse_pair_result(
                result=result,
                offset=0,
                now_ms=now_ms,
                duration=agency_duration,
            ),
            "user": self._parse_pair_result(
                result=result,
                offset=3,
                now_ms=now_ms,
                duration=user_duration,
            ),
        }
        request._paired_sliding_window = parsed
        scope_name = str(getattr(self, "scope", "") or "")
        scoped = parsed.get(scope_name)
        if isinstance(scoped, tuple) and len(scoped) == 3:
            return scoped
        return None

    def _parse_pair_result(
        self,
        *,
        result: Any,
        offset: int,
        now_ms: int,
        duration: int,
    ) -> tuple[bool, int, float]:
        allowed = (
            bool(int(result[offset]))
            if isinstance(result, (list, tuple)) and len(result) >= offset + 1
            else True
        )
        count_after = (
            int(result[offset + 1])
            if isinstance(result, (list, tuple)) and len(result) >= offset + 2
            else 0
        )
        oldest_ms = (
            int(float(result[offset + 2]))
            if isinstance(result, (list, tuple)) and len(result) >= offset + 3
            else now_ms
        )
        reset_after = max(0.0, ((oldest_ms + (duration * 1000)) - now_ms) / 1000.0)
        return allowed, count_after, reset_after

    def allow_request(self, request: Request, view: APIView) -> bool:
        key = self._get_storage_key(request, view)
        if key is None:
            return True
        num_requests = int(getattr(self, "num_requests", 0) or 0)
        duration = int(getattr(self, "duration", 0) or 0)
        if num_requests <= 0 or duration <= 0:
            return True
        try:
            paired = self._paired_allow_request(request)
            if paired is not None:
                allowed, count_after, reset_after = paired
            else:
                allowed, count_after, reset_after = self._sliding_allow_request(
                    key=key,
                    num_requests=num_requests,
                    duration=duration,
                )
        except Exception:
            logger.warning("Sliding-window throttle unavailable; failing open", exc_info=True)
            self._throttle_retry_after = None
            return True
        self.now = time.time()
        self.duration = reset_after
        self.history = range(min(max(count_after, 0), num_requests))
        self._throttle_retry_after = reset_after if not allowed else None
        return bool(allowed)

    def wait(self) -> float | None:
        retry_after = self._throttle_retry_after
        if retry_after is None:
            return None
        return max(0.0, float(retry_after))


class HeaderAnonRateThrottle(_HeaderThrottleMixin, AnonRateThrottle):
    """Anon throttle with rate-limit headers."""


class HeaderUserRateThrottle(
    _HeaderThrottleMixin,
    _SlidingWindowMixin,
    UserRateThrottle,
):
    """User throttle with rate-limit headers."""

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        ident = _resolve_user_ident(request)
        if ident is None:
            return None
        return build_throttle_storage_key(self.scope, ident)


class HeaderAgencyRateThrottle(
    _HeaderThrottleMixin,
    _SlidingWindowMixin,
    SimpleRateThrottle,
):
    """Agency throttle with user fallback for agency-less users."""

    scope = "agency"

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        ident = _resolve_agency_ident(request)
        if ident is None:
            return None
        return build_throttle_storage_key(self.scope, ident)


class HeaderScopedRateThrottle(
    _HeaderThrottleMixin,
    _SlidingWindowMixin,
    ScopedRateThrottle,
):
    """Scoped throttle with rate-limit headers."""

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        scope = getattr(view, "throttle_scope", None)
        if not isinstance(scope, str) or not scope:
            return None
        ident = _resolve_user_ident(request)
        if ident is None:
            return None
        return str(
            self.cache_format
            % {
                "scope": scope,
                "ident": ident,
            }
        )


__all__ = [
    "HeaderAgencyRateThrottle",
    "HeaderAnonRateThrottle",
    "HeaderScopedRateThrottle",
    "HeaderUserRateThrottle",
    "_HeaderThrottleMixin",
    "_SlidingWindowMixin",
    "_resolve_agency_ident",
    "build_throttle_storage_key",
    "parse_rate_limit_window",
]
