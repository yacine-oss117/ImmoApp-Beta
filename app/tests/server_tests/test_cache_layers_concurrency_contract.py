from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from django.test import override_settings

from server.services.cache_control import CacheNamespace
from server.services.cache_layers import (
    AdaptiveLocalCache,
    SharedResponseCache,
    _single_flight_strict_mode,
    _SingleFlightLease,
    ensure_single_flight_backend_ready,
)


class _FakeL2Cache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, object] = {}

    def get(self, key: str) -> object | None:
        with self._lock:
            return self._values.get(key)

    def set(self, key: str, value: object, timeout: int | None = None) -> None:
        del timeout
        with self._lock:
            self._values[key] = value


class _FakeRedisLeaseClient:
    def __init__(self, *, clock) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._leases: dict[str, tuple[str, float]] = {}

    def _purge_expired(self, key: str) -> None:
        current = self._leases.get(key)
        if current is None:
            return
        _token, expires_at = current
        if expires_at <= self._clock():
            self._leases.pop(key, None)

    def set(self, key: str, value: str, *, nx: bool, px: int) -> bool:
        with self._lock:
            self._purge_expired(key)
            if nx and key in self._leases:
                return False
            self._leases[key] = (value, self._clock() + (float(px) / 1000.0))
            return True

    def get(self, key: str) -> str | None:
        with self._lock:
            self._purge_expired(key)
            current = self._leases.get(key)
            return current[0] if current is not None else None

    def eval(self, script: str, num_keys: int, key: str, token: str, *args: Any) -> int:
        del num_keys
        with self._lock:
            self._purge_expired(key)
            current = self._leases.get(key)
            if current is None or current[0] != token:
                return 0
            if "DEL" in script:
                self._leases.pop(key, None)
                return 1
            if "PEXPIRE" in script:
                lease_ms = int(args[0])
                self._leases[key] = (token, self._clock() + (float(lease_ms) / 1000.0))
                return 1
        return 0


def _cache_policy() -> dict[str, object]:
    return {
        "ttl_seconds": 30,
        "stale_while_revalidate_seconds": 0,
        "cache_layer": "l2_only",
        "admit_after_hits": 1,
        "max_entry_bytes": 262144,
        "cache_deep_offsets": False,
        "cache_search_queries": True,
    }


def test_single_flight_release_only_succeeds_for_current_owner() -> None:
    now = 0.0

    def _clock() -> float:
        return now

    client = _FakeRedisLeaseClient(clock=_clock)
    lease1 = _SingleFlightLease.acquire(client=client, key="sf:lock", lease_ms=1000)
    assert lease1 is not None

    now = 1.25
    lease2 = _SingleFlightLease.acquire(client=client, key="sf:lock", lease_ms=1000)
    assert lease2 is not None
    assert lease2.token != lease1.token

    assert lease1.release() is False
    assert client.get("sf:lock") == lease2.token
    assert lease2.release() is True
    assert client.get("sf:lock") is None


def test_shared_cache_single_flight_renews_lease_for_long_fill(
    monkeypatch,
) -> None:
    fake_l2 = _FakeL2Cache()
    lease_client = _FakeRedisLeaseClient(clock=time.monotonic)
    cache_events: list[tuple[str, str, str, str]] = []
    started = threading.Event()
    results: list[object] = []
    fill_count = 0
    fill_count_lock = threading.Lock()

    monkeypatch.setattr("server.services.cache_layers.cache", fake_l2)
    monkeypatch.setattr("server.services.cache_layers._default_cache_client", lambda: lease_client)
    monkeypatch.setattr("server.services.cache_layers._single_flight_lock_seconds", lambda: 1)
    monkeypatch.setattr(
        "server.services.cache_layers._single_flight_wait_seconds", lambda _policy: 3.0
    )
    monkeypatch.setattr(
        "server.services.cache_layers.record_cache_event",
        lambda cache_name, layer, outcome, tenant_scope: cache_events.append(
            (str(cache_name), str(layer), str(outcome), str(tenant_scope))
        ),
    )
    monkeypatch.setattr(
        "server.services.cache_layers.record_cache_fill_latency", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "server.services.cache_layers.record_cache_payload_bytes", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "server.services.cache_layers.record_cache_pressure", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "server.services.cache_layers.record_cache_hit", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "server.services.cache_layers.record_cache_miss", lambda *args, **kwargs: None
    )

    shared_cache = SharedResponseCache()

    def _fill() -> dict[str, object]:
        nonlocal fill_count
        with fill_count_lock:
            fill_count += 1
        started.set()
        time.sleep(1.35)
        return {"items": [1], "total": 1}

    def _call() -> None:
        results.append(
            shared_cache.get_or_fill(
                namespace=CacheNamespace.CLIENTS_COUNT,
                agency_id=17,
                actor_id=9,
                query_key=("clients-count", 17),
                policy=_cache_policy(),
                fill_fn=_fill,
            )
        )

    thread_a = threading.Thread(target=_call)
    thread_b = threading.Thread(target=_call)
    thread_a.start()
    assert started.wait(timeout=1.0)
    thread_b.start()
    thread_a.join(timeout=5.0)
    thread_b.join(timeout=5.0)

    assert fill_count == 1
    assert results == [{"items": [1], "total": 1}, {"items": [1], "total": 1}]
    assert any(outcome == "single_flight_renew" for _name, _layer, outcome, _scope in cache_events)
    assert any(outcome == "lock_wait" for _name, _layer, outcome, _scope in cache_events)


def test_adaptive_local_cache_expires_entries_without_full_hot_path_scan() -> None:
    cache = AdaptiveLocalCache()
    assert cache.set(
        cache_name="clients_count",
        key="k1",
        payload={"items": [1]},
        tenant_key="agency:1",
        policy_name="clients_count",
        ttl_seconds=1,
        admit_after_hits=1,
        max_entry_bytes=262144,
    )
    assert cache.get(cache_name="clients_count", key="k1") == {"items": [1]}
    time.sleep(1.05)
    assert cache.get(cache_name="clients_count", key="k1") is None


@override_settings(IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT=True, DEBUG=True)
def test_explicit_single_flight_policy_requires_owner_safe_backend(monkeypatch) -> None:
    monkeypatch.setattr("server.services.cache_layers._default_cache_client", lambda: None)

    try:
        ensure_single_flight_backend_ready()
    except RuntimeError as exc:
        assert "IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT=1" in str(exc)
    else:  # pragma: no cover - defensive assertion branch
        raise AssertionError("strict startup gate should fail when the raw Redis client is missing")


@override_settings(IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT=False, DEBUG=False)
def test_explicit_single_flight_policy_allows_degraded_fallback(monkeypatch) -> None:
    monkeypatch.setattr("server.services.cache_layers._default_cache_client", lambda: None)

    assert ensure_single_flight_backend_ready() is False


@override_settings(IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT=True, DEBUG=False)
def test_explicit_single_flight_policy_accepts_owner_safe_backend(monkeypatch) -> None:
    lease_client = _FakeRedisLeaseClient(clock=time.monotonic)
    monkeypatch.setattr("server.services.cache_layers._default_cache_client", lambda: lease_client)

    assert ensure_single_flight_backend_ready() is True


@override_settings(IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT=True, DEBUG=True)
def test_single_flight_policy_ignores_debug_when_explicitly_strict() -> None:
    assert _single_flight_strict_mode() is True


@override_settings(IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT=False, DEBUG=False)
def test_single_flight_policy_ignores_debug_when_explicitly_relaxed() -> None:
    assert _single_flight_strict_mode() is False


def test_cache_layers_source_guards_keep_safe_single_flight_and_heap_expiry() -> None:
    source = Path("server/services/cache_layers.py").read_text(encoding="utf-8")
    asgi_source = Path("server/immoapp_server/asgi.py").read_text(encoding="utf-8")
    wsgi_source = Path("server/immoapp_server/wsgi.py").read_text(encoding="utf-8")
    celery_source = Path("server/immoapp_server/celery.py").read_text(encoding="utf-8")

    get_section = source.split("def get(", 1)[1].split("def set(", 1)[0]
    set_section = source.split("def set(", 1)[1].split("def clear(", 1)[0]

    assert "cache.delete(lock_key)" not in source
    assert "_expiry_heap" in source
    assert "_entries.items()" not in get_section
    assert "_entries.items()" not in set_section
    assert "read_namespace_version" not in source
    assert "build_versioned_cache_key" not in source
    assert "IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT" in source
    assert 'getattr(settings, "DEBUG"' not in source
    assert "ensure_single_flight_backend_ready()" in asgi_source
    assert "ensure_single_flight_backend_ready()" in wsgi_source
    assert "ensure_single_flight_backend_ready()" in celery_source
