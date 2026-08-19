from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace


class _FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, int]] = {}

    def eval(self, _script, _numkeys, key, now_ms, window_ms, limit, member):
        now_ms = int(now_ms)
        window_ms = int(window_ms)
        limit = int(limit)
        bucket = self._data.setdefault(str(key), {})
        cutoff = now_ms - window_ms
        for item, score in list(bucket.items()):
            if score <= cutoff:
                bucket.pop(item, None)
        count = len(bucket)
        allowed = 0
        if count < limit:
            bucket[str(member)] = now_ms
            count += 1
            allowed = 1
        oldest = min(bucket.values()) if bucket else 0
        return [allowed, count, oldest]


@dataclass
class _User:
    id: int = 7
    pk: int = 7
    agency_id: int | None = 12
    is_authenticated: bool = True


def _request():
    return SimpleNamespace(user=_User(), META={"REMOTE_ADDR": "127.0.0.1"})


def test_sliding_window_counts_evenly_spread_requests(monkeypatch) -> None:
    from server.api import throttling

    class _Throttle(throttling.HeaderUserRateThrottle):
        rate = "2/minute"

    fake = _FakeRedis()
    now = {"value": 1000.0}
    monkeypatch.setattr(throttling, "_default_cache_client", lambda: fake)
    monkeypatch.setattr(throttling.time, "time", lambda: now["value"])

    request = _request()

    throttle = _Throttle()
    assert throttle.allow_request(request, object()) is True
    now["value"] += 10.0
    assert throttle.allow_request(request, object()) is True
    now["value"] += 10.0
    assert throttle.allow_request(request, object()) is False


def test_sliding_window_blocks_boundary_double_burst(monkeypatch) -> None:
    from server.api import throttling

    class _Throttle(throttling.HeaderUserRateThrottle):
        rate = "2/minute"

    fake = _FakeRedis()
    now = {"value": 1000.0 + 58.0}
    monkeypatch.setattr(throttling, "_default_cache_client", lambda: fake)
    monkeypatch.setattr(throttling.time, "time", lambda: now["value"])

    request = _request()

    throttle = _Throttle()
    assert throttle.allow_request(request, object()) is True
    now["value"] = 1000.0 + 59.0
    assert throttle.allow_request(request, object()) is True
    now["value"] = 1000.0 + 60.0
    assert throttle.allow_request(request, object()) is False


def test_sliding_window_prunes_entries_after_window(monkeypatch) -> None:
    from server.api import throttling

    class _Throttle(throttling.HeaderUserRateThrottle):
        rate = "1/minute"

    fake = _FakeRedis()
    now = {"value": 1000.0}
    monkeypatch.setattr(throttling, "_default_cache_client", lambda: fake)
    monkeypatch.setattr(throttling.time, "time", lambda: now["value"])

    request = _request()

    throttle = _Throttle()
    assert throttle.allow_request(request, object()) is True
    now["value"] += 61.0
    assert throttle.allow_request(request, object()) is True


def test_sliding_window_fails_open_when_valkey_unavailable(monkeypatch) -> None:
    from server.api import throttling

    class _Throttle(throttling.HeaderUserRateThrottle):
        rate = "1/minute"

    monkeypatch.setattr(throttling, "_default_cache_client", lambda: None)

    request = _request()

    assert _Throttle().allow_request(request, object()) is True


def test_sliding_window_wait_uses_oldest_timestamp(monkeypatch) -> None:
    from server.api import throttling

    class _Throttle(throttling.HeaderUserRateThrottle):
        rate = "1/minute"

    fake = _FakeRedis()
    now = {"value": 1000.0}
    monkeypatch.setattr(throttling, "_default_cache_client", lambda: fake)
    monkeypatch.setattr(throttling.time, "time", lambda: now["value"])

    request = _request()

    throttle = _Throttle()
    assert throttle.allow_request(request, object()) is True
    now["value"] += 10.0
    assert throttle.allow_request(request, object()) is False
    wait = throttle.wait()
    assert wait is not None
    assert 49.0 <= wait <= 51.0
    entries = getattr(request, "_rate_limit_headers", [])
    assert isinstance(entries, list)
    assert entries[-1]["reset"] == int(now["value"] + wait)
