from __future__ import annotations

from server.services import latency_rollups


def test_latency_rollups_empty_snapshot_is_none() -> None:
    latency_rollups.clear_latency_rollups()
    assert latency_rollups.route_latency_snapshot("route.users") is None


def test_latency_rollups_record_and_list_snapshots() -> None:
    latency_rollups.clear_latency_rollups()
    for ms in (10.0, 20.0, 30.0, 40.0, 50.0):
        latency_rollups.record_latency_sample(route_name="route.users", duration_ms=ms)
    for ms in (5.0, 7.0, 8.0):
        latency_rollups.record_latency_sample(route_name="route.notifications", duration_ms=ms)

    one = latency_rollups.route_latency_snapshot("route.users")
    assert one is not None
    assert int(one["sample_count"]) == 5
    assert float(one["p95_ms"]) >= 40.0
    assert float(one["p99_ms"]) >= float(one["p95_ms"])

    items = latency_rollups.list_latency_snapshots(limit=10)
    assert items
    assert items[0]["route_name"] == "route.users"
    assert int(items[0]["sample_count"]) == 5
