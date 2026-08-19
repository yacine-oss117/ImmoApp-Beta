"""Shared L1/L2 cache helpers for hot read endpoints."""

from __future__ import annotations

import copy
import hashlib
import heapq
import json
import logging
import os
import socket
import threading
import time
import uuid
from collections import OrderedDict, defaultdict
from typing import Any, Callable, TypedDict, cast

from django.conf import settings
from django.core.cache import cache, caches

from core.runtime.hub_runtime_profile import detect_machine_capacity
from server.immoapp_server.business_metrics_match import (
    record_cache_event,
    record_cache_fill_latency,
    record_cache_payload_bytes,
    record_cache_pressure,
)
from server.pg.observability import record_cache_hit, record_cache_miss
from server.services.cache_control import CacheNamespace, namespace_key
from server.services.cache_policies import CachePolicy

logger = logging.getLogger(__name__)

_SINGLE_FLIGHT_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""
_SINGLE_FLIGHT_RENEW_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""


class CacheEntryEnvelope(TypedDict):
    version: int
    expires_at_epoch_ms: int
    payload: object
    payload_bytes: int
    tenant_key: str
    policy_name: str


def _stable_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _memory_budget_bytes() -> int:
    raw = (os.environ.get("IMMOAPP_CACHE_L1_MAX_BYTES") or "").strip()
    if raw:
        try:
            return max(64 * 1024 * 1024, min(int(raw), 256 * 1024 * 1024))
        except ValueError:
            pass
    capacity = detect_machine_capacity()
    detected_total = capacity.effective_memory_bytes or capacity.total_ram_bytes
    if detected_total <= 0:
        return 64 * 1024 * 1024
    return min(256 * 1024 * 1024, max(64 * 1024 * 1024, int(detected_total * 0.05)))


def _high_watermark_ratio() -> float:
    raw = (os.environ.get("IMMOAPP_CACHE_L1_PRESSURE_HIGH_RATIO") or "0.80").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 0.8
    return max(0.2, min(value, 0.98))


def _low_watermark_ratio() -> float:
    raw = (os.environ.get("IMMOAPP_CACHE_L1_PRESSURE_LOW_RATIO") or "0.60").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 0.6
    return max(0.1, min(value, _high_watermark_ratio()))


def _single_flight_lock_seconds() -> int:
    raw = (os.environ.get("IMMOAPP_CACHE_SINGLE_FLIGHT_LOCK_SECONDS") or "5").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 5
    return max(1, min(value, 30))


def _single_flight_wait_seconds(policy: CachePolicy) -> float:
    ttl_seconds = max(1, int(policy["ttl_seconds"]))
    raw = (os.environ.get("IMMOAPP_CACHE_SINGLE_FLIGHT_WAIT_SECONDS") or "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            value = min(float(ttl_seconds), 15.0)
    else:
        value = min(float(ttl_seconds), 15.0)
    return max(0.5, min(value, 120.0))


def _payload_bytes(payload: object) -> int:
    return len(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    )


def _jittered_ttl_seconds(ttl_seconds: int, *, key: str, max_ratio: float = 0.20) -> int:
    ttl_seconds = max(1, int(ttl_seconds))
    if ttl_seconds <= 5:
        return ttl_seconds
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    scale = int(digest[0]) / 255.0
    jittered = ttl_seconds + int(round(ttl_seconds * max(0.0, min(max_ratio, 1.0)) * scale))
    return max(1, jittered)


def _l1_seed_ttl_seconds(policy: CachePolicy, *, key: str) -> int:
    ttl_seconds = max(1, int(policy["ttl_seconds"]))
    seeded = max(1, min(ttl_seconds, max(5, ttl_seconds // 2 or 1)))
    return _jittered_ttl_seconds(seeded, key=f"{key}:l1")


def _clone_response_payload(payload: object) -> object:
    if isinstance(payload, (dict, list, tuple, set)):
        return copy.deepcopy(payload)
    return copy.copy(payload)


def _default_cache_client() -> object | None:
    try:
        backend = caches["default"]
        client = getattr(backend, "client", None)
        if client is None or not hasattr(client, "get_client"):
            return None
        return cast(object, client.get_client(write=True))
    except Exception:
        return None


def _single_flight_strict_mode() -> bool:
    return bool(getattr(settings, "IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT", True))


def _single_flight_capability_error(*, detail: str) -> RuntimeError:
    return RuntimeError(
        "Owner-safe Redis single-flight capability is required for shared response caching when "
        "IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT=1, but the configured default cache backend is "
        f"incompatible: {detail}. Set IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT=0 only for explicit "
        "local or degraded startup modes."
    )


def _probe_single_flight_backend(*, client: object) -> None:
    redis_client = cast(Any, client)
    probe_key = (
        "immoapp:cache:single-flight:probe:"
        f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"
    )
    probe_token = uuid.uuid4().hex
    probe_lease_ms = 1500
    acquired = bool(redis_client.set(probe_key, probe_token, nx=True, px=probe_lease_ms))
    if not acquired:
        raise _single_flight_capability_error(
            detail="probe lease acquisition failed unexpectedly",
        )
    try:
        renewed = redis_client.eval(
            _SINGLE_FLIGHT_RENEW_SCRIPT,
            1,
            probe_key,
            probe_token,
            probe_lease_ms,
        )
        if not bool(int(renewed or 0)):
            raise _single_flight_capability_error(
                detail="probe lease renewal did not preserve token ownership",
            )
        released = redis_client.eval(
            _SINGLE_FLIGHT_RELEASE_SCRIPT,
            1,
            probe_key,
            probe_token,
        )
        if not bool(int(released or 0)):
            raise _single_flight_capability_error(
                detail="probe lease release did not honor token ownership",
            )
    except RuntimeError:
        raise
    except Exception as exc:
        raise _single_flight_capability_error(detail=str(exc) or exc.__class__.__name__) from exc


def ensure_single_flight_backend_ready(*, strict: bool | None = None) -> bool:
    strict_mode = _single_flight_strict_mode() if strict is None else bool(strict)
    client = _default_cache_client()
    if client is None:
        if strict_mode:
            raise _single_flight_capability_error(
                detail=(
                    "the default cache backend does not expose a raw django-redis client with "
                    "Redis Lua/lease support"
                ),
            )
        return False
    try:
        _probe_single_flight_backend(client=client)
    except RuntimeError:
        if strict_mode:
            raise
        return False
    return True


class _SingleFlightLease:
    def __init__(self, *, client: object, key: str, token: str, lease_ms: int) -> None:
        self._client = client
        self.key = key
        self.token = token
        self.lease_ms = max(1000, int(lease_ms))

    @classmethod
    def acquire(cls, *, client: object, key: str, lease_ms: int) -> _SingleFlightLease | None:
        token = str(uuid.uuid4())
        redis_client = cast(Any, client)
        acquired = bool(redis_client.set(key, token, nx=True, px=max(1000, int(lease_ms))))
        if not acquired:
            return None
        return cls(client=client, key=key, token=token, lease_ms=lease_ms)

    def renew(self) -> bool:
        redis_client = cast(Any, self._client)
        result = redis_client.eval(
            _SINGLE_FLIGHT_RENEW_SCRIPT,
            1,
            self.key,
            self.token,
            self.lease_ms,
        )
        return bool(int(result or 0))

    def release(self) -> bool:
        redis_client = cast(Any, self._client)
        result = redis_client.eval(
            _SINGLE_FLIGHT_RELEASE_SCRIPT,
            1,
            self.key,
            self.token,
        )
        return bool(int(result or 0))


class _SingleFlightLeaseRenewer:
    def __init__(self, *, lease: _SingleFlightLease, cache_name: str, tenant_scope: str) -> None:
        self._lease = lease
        self._cache_name = cache_name
        self._tenant_scope = tenant_scope
        self._stop = threading.Event()
        self._lost = False
        self._thread = threading.Thread(
            target=self._run,
            name=f"cache-single-flight-renew:{cache_name}",
            daemon=True,
        )

    @property
    def lost(self) -> bool:
        return self._lost

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(1.0, float(self._lease.lease_ms) / 1000.0))

    def _run(self) -> None:
        interval_seconds = max(0.25, min(float(self._lease.lease_ms) / 3000.0, 5.0))
        while not self._stop.wait(interval_seconds):
            try:
                if self._lease.renew():
                    record_cache_event(
                        self._cache_name,
                        "l2",
                        "single_flight_renew",
                        self._tenant_scope,
                    )
                    continue
                self._lost = True
                record_cache_event(
                    self._cache_name,
                    "l2",
                    "single_flight_renew_lost",
                    self._tenant_scope,
                )
                return
            except Exception:
                self._lost = True
                record_cache_event(
                    self._cache_name,
                    "l2",
                    "single_flight_renew_error",
                    self._tenant_scope,
                )
                return


class AdaptiveLocalCache:
    """Small bounded LRU cache with tenant-aware soft pressure control."""

    def __init__(self) -> None:
        self._entries: OrderedDict[str, CacheEntryEnvelope] = OrderedDict()
        self._expiry_heap: list[tuple[int, int, str]] = []
        self._tenant_bytes: dict[str, int] = defaultdict(int)
        self._admission_counts: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()
        self._max_bytes = _memory_budget_bytes()
        self._total_bytes = 0
        self._entry_version = 0
        self._last_admission_sweep = 0.0

    def _soft_share(self) -> int:
        active_tenants = max(1, len(self._tenant_bytes))
        return max(1 * 1024 * 1024, self._max_bytes // max(8, active_tenants))

    def _current_bytes(self) -> int:
        return self._total_bytes

    def _next_entry_version(self) -> int:
        self._entry_version += 1
        return self._entry_version

    def _expire(self, now_ms: int) -> None:
        while self._expiry_heap and int(self._expiry_heap[0][0]) <= now_ms:
            expires_at, version, key = heapq.heappop(self._expiry_heap)
            entry = self._entries.get(key)
            if entry is None:
                continue
            if int(entry.get("version", 0)) != int(version):
                continue
            if int(entry.get("expires_at_epoch_ms", 0)) != int(expires_at):
                continue
            self._evict_key(key, outcome="expired")
        self._compact_expiry_heap_if_needed()

    def _sweep_admission_counts(self, now: float | None = None) -> None:
        resolved_now = time.monotonic() if now is None else float(now)
        if resolved_now - self._last_admission_sweep < 5.0 and len(self._admission_counts) < 1024:
            return
        self._last_admission_sweep = resolved_now
        expired_keys = [
            key
            for key, (expires_at, _count) in self._admission_counts.items()
            if float(expires_at or 0.0) <= resolved_now
        ]
        for key in expired_keys:
            self._admission_counts.pop(key, None)

    def _compact_expiry_heap_if_needed(self) -> None:
        live = len(self._entries)
        if len(self._expiry_heap) <= max(live * 2, live + 1024):
            return
        self._expiry_heap = [
            (
                int(entry.get("expires_at_epoch_ms", 0) or 0),
                int(entry.get("version", 0) or 0),
                key,
            )
            for key, entry in self._entries.items()
        ]
        heapq.heapify(self._expiry_heap)

    def _evict_key(self, key: str, *, outcome: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is None:
            return
        tenant_key = str(entry.get("tenant_key") or "global")
        self._tenant_bytes[tenant_key] = max(
            0,
            int(self._tenant_bytes.get(tenant_key, 0)) - int(entry.get("payload_bytes", 0)),
        )
        self._total_bytes = max(0, self._total_bytes - int(entry.get("payload_bytes", 0)))
        if self._tenant_bytes[tenant_key] <= 0:
            self._tenant_bytes.pop(tenant_key, None)
        record_cache_event(entry.get("policy_name", "unknown"), "l1", outcome, tenant_key)

    def _track_admission(self, key: str) -> int:
        now = time.monotonic()
        self._sweep_admission_counts(now)
        expires_at, count = self._admission_counts.get(key, (0.0, 0))
        if expires_at <= now:
            count = 0
        count += 1
        self._admission_counts[key] = (now + 60.0, count)
        return count

    def _evict_under_pressure(self, *, preferred_tenant_key: str | None = None) -> None:
        high_bytes = int(self._max_bytes * _high_watermark_ratio())
        while self._current_bytes() > high_bytes and self._entries:
            candidate_key: str | None = None
            soft_share = self._soft_share()
            if (
                preferred_tenant_key
                and self._tenant_bytes.get(preferred_tenant_key, 0) > soft_share
            ):
                for key, entry in self._entries.items():
                    if str(entry.get("tenant_key")) == preferred_tenant_key:
                        candidate_key = key
                        break
            if candidate_key is None:
                for key, entry in self._entries.items():
                    tenant_key = str(entry.get("tenant_key") or "global")
                    if self._tenant_bytes.get(tenant_key, 0) > soft_share:
                        candidate_key = key
                        break
            if candidate_key is None:
                candidate_key = next(iter(self._entries))
            self._evict_key(candidate_key, outcome="evict")

    def get(self, *, cache_name: str, key: str) -> object | None:
        now_ms = int(time.time() * 1000.0)
        tenant_key = "none"
        payload: object | None = None
        with self._lock:
            self._expire(now_ms)
            entry = self._entries.get(key)
            if entry is None:
                payload = None
            else:
                self._entries.move_to_end(key)
                tenant_key = str(entry.get("tenant_key") or "global")
                payload = entry.get("payload")
        if payload is None:
            record_cache_event(cache_name, "l1", "miss", "none")
            record_cache_miss(f"{cache_name}_l1")
            return None
        record_cache_event(cache_name, "l1", "hit", tenant_key)
        record_cache_hit(f"{cache_name}_l1")
        return _clone_response_payload(payload)

    def set(
        self,
        *,
        cache_name: str,
        key: str,
        payload: object,
        tenant_key: str,
        policy_name: str,
        ttl_seconds: int,
        admit_after_hits: int,
        max_entry_bytes: int,
    ) -> bool:
        payload_size = _payload_bytes(payload)
        if payload_size > max_entry_bytes:
            record_cache_event(cache_name, "l1", "reject_entry_too_large", tenant_key)
            return False
        payload_copy = _clone_response_payload(payload)
        now_ms = int(time.time() * 1000.0)
        current_bytes_after = 0
        entry_count_after = 0
        with self._lock:
            self._expire(now_ms)
            current_bytes = self._current_bytes()
            if current_bytes >= int(
                self._max_bytes * _low_watermark_ratio()
            ) and self._track_admission(key) < max(1, admit_after_hits):
                record_cache_event(cache_name, "l1", "reject_first_seen", tenant_key)
                return False
            entry: CacheEntryEnvelope = {
                "version": self._next_entry_version(),
                "expires_at_epoch_ms": now_ms + (max(1, ttl_seconds) * 1000),
                "payload": payload_copy,
                "payload_bytes": payload_size,
                "tenant_key": tenant_key,
                "policy_name": policy_name,
            }
            existing = self._entries.pop(key, None)
            if existing is not None:
                existing_tenant = str(existing.get("tenant_key") or "global")
                self._tenant_bytes[existing_tenant] = max(
                    0,
                    int(self._tenant_bytes.get(existing_tenant, 0))
                    - int(existing.get("payload_bytes", 0)),
                )
                self._total_bytes = max(
                    0, self._total_bytes - int(existing.get("payload_bytes", 0))
                )
            self._entries[key] = entry
            self._tenant_bytes[tenant_key] += payload_size
            self._total_bytes += payload_size
            heapq.heappush(
                self._expiry_heap,
                (int(entry["expires_at_epoch_ms"]), int(entry["version"]), key),
            )
            self._evict_under_pressure(preferred_tenant_key=tenant_key)
            self._compact_expiry_heap_if_needed()
            current_bytes_after = self._current_bytes()
            entry_count_after = len(self._entries)
        record_cache_event(cache_name, "l1", "set", tenant_key)
        record_cache_payload_bytes(cache_name, "l1", payload_size)
        record_cache_pressure(cache_name, "l1", "state", current_bytes_after, entry_count_after)
        return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._expiry_heap.clear()
            self._tenant_bytes.clear()
            self._admission_counts.clear()
            self._total_bytes = 0
            self._entry_version = 0
            self._last_admission_sweep = 0.0


class SharedResponseCache:
    """Shared Redis-backed response cache with bounded local front cache."""

    def __init__(self) -> None:
        self._l1 = AdaptiveLocalCache()

    def _full_key(
        self,
        *,
        namespace: CacheNamespace,
        agency_id: int | None,
        actor_id: int | None,
        payload_key: str,
    ) -> tuple[str, str]:
        tenant_scope = namespace_key(namespace, agency_id=agency_id, actor_id=actor_id)
        key = f"{tenant_scope}:q:{payload_key}"
        return key, tenant_scope

    def get(
        self,
        *,
        namespace: CacheNamespace,
        agency_id: int | None,
        actor_id: int | None,
        payload_key: str,
        policy: CachePolicy,
    ) -> object | None:
        full_key, tenant_scope = self._full_key(
            namespace=namespace,
            agency_id=agency_id,
            actor_id=actor_id,
            payload_key=payload_key,
        )
        cache_name = namespace.value
        if policy["cache_layer"] == "l1_l2":
            cached = self._l1.get(cache_name=cache_name, key=full_key)
            if cached is not None:
                return cached
        try:
            payload = cache.get(full_key)
        except Exception:
            logger.warning("Shared cache lookup failed; falling back to source", exc_info=True)
            record_cache_event(cache_name, "l2", "error", tenant_scope)
            return None
        if payload is None:
            record_cache_event(cache_name, "l2", "miss", tenant_scope)
            record_cache_miss(f"{cache_name}_l2")
            return None
        record_cache_event(cache_name, "l2", "hit", tenant_scope)
        record_cache_hit(f"{cache_name}_l2")
        if policy["cache_layer"] == "l1_l2":
            self._l1.set(
                cache_name=cache_name,
                key=full_key,
                payload=payload,
                tenant_key=tenant_scope,
                policy_name=cache_name,
                ttl_seconds=_l1_seed_ttl_seconds(policy, key=full_key),
                admit_after_hits=max(1, int(policy["admit_after_hits"])),
                max_entry_bytes=max(4096, int(policy["max_entry_bytes"])),
            )
        return _clone_response_payload(payload)

    def set(
        self,
        *,
        namespace: CacheNamespace,
        agency_id: int | None,
        actor_id: int | None,
        payload_key: str,
        payload: object,
        policy: CachePolicy,
    ) -> None:
        full_key, tenant_scope = self._full_key(
            namespace=namespace,
            agency_id=agency_id,
            actor_id=actor_id,
            payload_key=payload_key,
        )
        cache_name = namespace.value
        l2_ttl_seconds = _jittered_ttl_seconds(int(policy["ttl_seconds"]), key=full_key)
        try:
            cache.set(full_key, payload, timeout=l2_ttl_seconds)
            record_cache_event(cache_name, "l2", "set", tenant_scope)
            record_cache_payload_bytes(cache_name, "l2", _payload_bytes(payload))
        except Exception:
            logger.warning("Shared cache write failed; continuing without L2", exc_info=True)
            record_cache_event(cache_name, "l2", "error", tenant_scope)
        if policy["cache_layer"] == "l1_l2":
            self._l1.set(
                cache_name=cache_name,
                key=full_key,
                payload=payload,
                tenant_key=tenant_scope,
                policy_name=cache_name,
                ttl_seconds=_l1_seed_ttl_seconds(policy, key=full_key),
                admit_after_hits=max(1, int(policy["admit_after_hits"])),
                max_entry_bytes=max(4096, int(policy["max_entry_bytes"])),
            )

    def get_or_fill(
        self,
        *,
        namespace: CacheNamespace,
        agency_id: int | None,
        actor_id: int | None,
        query_key: object,
        policy: CachePolicy,
        fill_fn: Callable[[], object],
    ) -> object:
        payload_key = _stable_hash(query_key)
        cached = self.get(
            namespace=namespace,
            agency_id=agency_id,
            actor_id=actor_id,
            payload_key=payload_key,
            policy=policy,
        )
        if cached is not None:
            return cached
        full_key, tenant_scope = self._full_key(
            namespace=namespace,
            agency_id=agency_id,
            actor_id=actor_id,
            payload_key=payload_key,
        )
        lock_key = f"{full_key}:lock"
        lease_seconds = _single_flight_lock_seconds()
        lease: _SingleFlightLease | None = None
        cache_client = _default_cache_client()
        if cache_client is not None:
            try:
                lease = _SingleFlightLease.acquire(
                    client=cache_client,
                    key=lock_key,
                    lease_ms=lease_seconds * 1000,
                )
            except Exception as err:
                lease = None
                record_cache_event(
                    namespace.value,
                    "l2",
                    "single_flight_backend_error",
                    tenant_scope,
                )
                if _single_flight_strict_mode():
                    raise _single_flight_capability_error(
                        detail="runtime lease acquisition failed after strict startup validation",
                    ) from err
        else:
            record_cache_event(
                namespace.value,
                "l2",
                "single_flight_backend_unavailable",
                tenant_scope,
            )
            if _single_flight_strict_mode():
                raise _single_flight_capability_error(
                    detail="runtime cache client is unavailable after strict startup validation",
                )
        if lease is None and cache_client is not None:
            record_cache_event(namespace.value, "l2", "single_flight_contended", tenant_scope)
            wait_deadline = time.monotonic() + _single_flight_wait_seconds(policy)
            while time.monotonic() < wait_deadline:
                time.sleep(0.025)
                cached = self.get(
                    namespace=namespace,
                    agency_id=agency_id,
                    actor_id=actor_id,
                    payload_key=payload_key,
                    policy=policy,
                )
                if cached is not None:
                    record_cache_event(namespace.value, "l2", "lock_wait", tenant_scope)
                    return cached
                try:
                    redis_client = cast(Any, cache_client)
                    if redis_client.get(lock_key) is None:
                        lease = _SingleFlightLease.acquire(
                            client=cache_client,
                            key=lock_key,
                            lease_ms=lease_seconds * 1000,
                        )
                        if lease is not None:
                            break
                except Exception as err:
                    record_cache_event(
                        namespace.value,
                        "l2",
                        "single_flight_backend_error",
                        tenant_scope,
                    )
                    if _single_flight_strict_mode():
                        raise _single_flight_capability_error(
                            detail=(
                                "runtime lease ownership probe failed after strict startup validation"
                            ),
                        ) from err
                    cache_client = None
                    break
        started = time.monotonic()
        renewer: _SingleFlightLeaseRenewer | None = None
        if lease is not None:
            record_cache_event(namespace.value, "l2", "single_flight_acquired", tenant_scope)
            renewer = _SingleFlightLeaseRenewer(
                lease=lease,
                cache_name=namespace.value,
                tenant_scope=tenant_scope,
            )
            renewer.start()
        try:
            payload = fill_fn()
            record_cache_fill_latency(namespace.value, "source", time.monotonic() - started)
            self.set(
                namespace=namespace,
                agency_id=agency_id,
                actor_id=actor_id,
                payload_key=payload_key,
                payload=payload,
                policy=policy,
            )
            return payload
        finally:
            if renewer is not None:
                renewer.stop()
            if lease is not None:
                try:
                    released = lease.release()
                    record_cache_event(
                        namespace.value,
                        "l2",
                        "single_flight_release" if released else "single_flight_release_lost",
                        tenant_scope,
                    )
                except Exception:
                    record_cache_event(
                        namespace.value,
                        "l2",
                        "single_flight_release_error",
                        tenant_scope,
                    )


_RESPONSE_CACHE: SharedResponseCache | None = None
_RESPONSE_CACHE_LOCK = threading.Lock()


def get_response_cache() -> SharedResponseCache:
    global _RESPONSE_CACHE
    with _RESPONSE_CACHE_LOCK:
        if _RESPONSE_CACHE is None:
            _RESPONSE_CACHE = SharedResponseCache()
        return _RESPONSE_CACHE


__all__ = [
    "AdaptiveLocalCache",
    "CacheEntryEnvelope",
    "SharedResponseCache",
    "ensure_single_flight_backend_ready",
    "get_response_cache",
]
