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

    def zremrangebyscore(self, key, _min_score, max_score):
        bucket = self._data.setdefault(str(key), {})
        max_score = int(max_score)
        for item, score in list(bucket.items()):
            if score <= max_score:
                bucket.pop(item, None)

    def zcard(self, key):
        return len(self._data.setdefault(str(key), {}))

    def scan_iter(self, match):
        prefix = str(match).rstrip("*")
        for key in list(self._data):
            if key.startswith(prefix):
                yield key


@dataclass
class _User:
    id: int
    pk: int
    agency_id: int | None
    is_superuser: bool = False
    is_authenticated: bool = True


def _request(user: _User):
    return SimpleNamespace(user=user, META={"REMOTE_ADDR": "127.0.0.1"})


def test_same_agency_users_share_one_throttle_counter(monkeypatch) -> None:
    from server.api import throttling

    class _Throttle(throttling.HeaderAgencyRateThrottle):
        rate = "2/minute"

    fake = _FakeRedis()
    monkeypatch.setattr(throttling, "_default_cache_client", lambda: fake)
    monkeypatch.setattr(throttling.time, "time", lambda: 1000.0)

    request1 = _request(_User(id=1, pk=1, agency_id=9))
    request2 = _request(_User(id=2, pk=2, agency_id=9))
    request3 = _request(_User(id=1, pk=1, agency_id=9))

    throttle = _Throttle()
    assert throttle.allow_request(request1, object()) is True
    assert throttle.allow_request(request2, object()) is True
    assert throttle.allow_request(request3, object()) is False


def test_different_agencies_have_independent_counters(monkeypatch) -> None:
    from server.api import throttling

    class _Throttle(throttling.HeaderAgencyRateThrottle):
        rate = "1/minute"

    fake = _FakeRedis()
    monkeypatch.setattr(throttling, "_default_cache_client", lambda: fake)
    monkeypatch.setattr(throttling.time, "time", lambda: 1000.0)

    request1 = _request(_User(id=1, pk=1, agency_id=9))
    request2 = _request(_User(id=2, pk=2, agency_id=10))

    throttle = _Throttle()
    assert throttle.allow_request(request1, object()) is True
    assert throttle.allow_request(request2, object()) is True


def test_superuser_without_agency_falls_back_to_user_key(monkeypatch) -> None:
    from server.api import throttling

    class _Throttle(throttling.HeaderAgencyRateThrottle):
        rate = "1/minute"

    fake = _FakeRedis()
    monkeypatch.setattr(throttling, "_default_cache_client", lambda: fake)
    monkeypatch.setattr(throttling.time, "time", lambda: 1000.0)

    request1 = _request(_User(id=11, pk=11, agency_id=None, is_superuser=True))
    request2 = _request(_User(id=12, pk=12, agency_id=None, is_superuser=True))

    throttle = _Throttle()
    assert throttle.allow_request(request1, object()) is True
    assert throttle.allow_request(request2, object()) is True


def test_headers_reflect_most_restrictive_active_throttle(monkeypatch) -> None:
    from server.api import throttling

    class _AgencyThrottle(throttling.HeaderAgencyRateThrottle):
        rate = "2/minute"

    class _UserThrottle(throttling.HeaderUserRateThrottle):
        rate = "5/minute"

    fake = _FakeRedis()
    monkeypatch.setattr(throttling, "_default_cache_client", lambda: fake)
    monkeypatch.setattr(throttling.time, "time", lambda: 1000.0)

    request = _request(_User(id=3, pk=3, agency_id=21))

    assert _AgencyThrottle().allow_request(request, object()) is True
    assert _UserThrottle().allow_request(request, object()) is True

    entries = getattr(request, "_rate_limit_headers", [])
    assert isinstance(entries, list)
    chosen = sorted(entries, key=lambda item: item.get("remaining", 0))[0]
    assert chosen["limit"] == 2
    assert chosen["remaining"] == 1
