from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _User:
    id: int = 1
    pk: int = 1
    agency_id: int | None = 10
    is_superuser: bool = False
    is_authenticated: bool = True


class _Session:
    def __init__(self, total: int | None) -> None:
        self._total = total

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, _sql, _params=()):
        class _Result:
            def __init__(self, total: int | None) -> None:
                self._total = total

            def fetchone(self):
                if self._total is None:
                    return None
                return {"total": self._total}

            def fetchall(self):
                if self._total is None:
                    return []
                return [{"agency_id": 10}]

        return _Result(self._total)


class _Uow:
    def __init__(self, total: int | None) -> None:
        self._total = total

    def session(self):
        return _Session(self._total)


class _FakeRedis:
    def __init__(self, count: int) -> None:
        self._count = count

    def zremrangebyscore(self, *_args, **_kwargs):
        return None

    def zcard(self, _key):
        return self._count

    def scan_iter(self, _match):
        return []


def test_compute_tenant_usage_zero_when_idle(monkeypatch) -> None:
    from server.services import tenant_usage_gauge

    monkeypatch.setattr(tenant_usage_gauge, "_in_flight_ratio", lambda _agency_id: 0.0)
    monkeypatch.setattr(tenant_usage_gauge, "_api_rate_ratio", lambda _agency_id: 0.0)

    payload = tenant_usage_gauge.compute_tenant_usage(10)
    assert payload["composite_ratio"] == 0.0


def test_in_flight_ratio_uses_global_slot_budget(monkeypatch) -> None:
    from server.services import tenant_usage_gauge

    monkeypatch.setattr(tenant_usage_gauge, "get_uow", lambda: _Uow(3))
    monkeypatch.setattr(tenant_usage_gauge, "_global_slot_budget", lambda: 4)

    assert tenant_usage_gauge._in_flight_ratio(10) == 0.75


def test_api_rate_ratio_uses_agency_throttle_budget(monkeypatch) -> None:
    from server.services import tenant_usage_gauge

    monkeypatch.setattr(tenant_usage_gauge, "_default_cache_client", lambda: _FakeRedis(15000))
    monkeypatch.setattr(tenant_usage_gauge, "_agency_rate_limit", lambda: 30000)

    assert tenant_usage_gauge._api_rate_ratio(10) == 0.5


def test_composite_ratio_is_max_of_components(monkeypatch) -> None:
    from server.services import tenant_usage_gauge

    monkeypatch.setattr(tenant_usage_gauge, "_in_flight_ratio", lambda _agency_id: 0.25)
    monkeypatch.setattr(tenant_usage_gauge, "_api_rate_ratio", lambda _agency_id: 0.5)

    payload = tenant_usage_gauge.compute_tenant_usage(10)
    assert payload["composite_ratio"] == 0.5


def test_no_leases_does_not_crash(monkeypatch) -> None:
    from server.services import tenant_usage_gauge

    monkeypatch.setattr(tenant_usage_gauge, "get_uow", lambda: _Uow(None))
    monkeypatch.setattr(tenant_usage_gauge, "_global_slot_budget", lambda: 4)

    assert tenant_usage_gauge._in_flight_ratio(10) == 0.0


def test_health_snapshot_includes_tenant_usage_when_requested(monkeypatch) -> None:
    from server.services import health as health_service

    monkeypatch.setattr(
        health_service,
        "fetch_health_snapshot",
        lambda: health_service.HealthSnapshot(
            db_path="postgres://localhost:5432/immoapp",
            active_connections=1,
            audit_actor="system",
            schema_version="1",
            settings_schema_version="1",
            last_repair=None,
            last_backup_ts=None,
            last_backup_reason=None,
            last_backup_path=None,
        ),
    )
    monkeypatch.setattr(health_service, "get_pool_stats", lambda: {})
    monkeypatch.setattr(health_service, "get_cache_stats", lambda: {})
    monkeypatch.setattr(
        health_service.tenant_usage_gauge, "compute_all_tenant_usage", lambda: [{"agency_id": 10}]
    )
    monkeypatch.setattr(health_service, "_check_database", lambda: {"ok": True})
    monkeypatch.setattr(health_service, "_check_cache", lambda: {"ok": True})
    monkeypatch.setattr(health_service, "_check_broker", lambda: {"ok": True})
    monkeypatch.setattr(health_service, "cache", None, raising=False)

    payload = health_service.health_snapshot(include_tenant_usage=True)
    assert payload["tenant_usage"] == [{"agency_id": 10}]


def test_health_snapshot_omits_tenant_usage_by_default(monkeypatch) -> None:
    from server.services import health as health_service

    monkeypatch.setattr(
        health_service,
        "fetch_health_snapshot",
        lambda: health_service.HealthSnapshot(
            db_path="postgres://localhost:5432/immoapp",
            active_connections=1,
            audit_actor="system",
            schema_version="1",
            settings_schema_version="1",
            last_repair=None,
            last_backup_ts=None,
            last_backup_reason=None,
            last_backup_path=None,
        ),
    )
    monkeypatch.setattr(health_service, "get_pool_stats", lambda: {})
    monkeypatch.setattr(health_service, "get_cache_stats", lambda: {})
    monkeypatch.setattr(
        health_service.tenant_usage_gauge, "compute_all_tenant_usage", lambda: [{"agency_id": 10}]
    )

    payload = health_service.health_snapshot(include_tenant_usage=False)
    assert "tenant_usage" not in payload
