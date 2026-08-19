from __future__ import annotations

from pathlib import Path

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

import server.services.dashboard as dashboard  # noqa: E402


def test_fetch_dashboard_stats_reads_live_results_without_server_side_cache(
    monkeypatch,
) -> None:
    values = iter(
        [
            {
                "client_count": 1,
                "listing_count": 1,
                "today_visits": [],
                "pending_contracts": [],
                "expiring_contracts": [],
                "hot_leads": [],
            },
            {
                "client_count": 2,
                "listing_count": 2,
                "today_visits": [],
                "pending_contracts": [],
                "expiring_contracts": [],
                "hot_leads": [],
            },
        ]
    )
    monkeypatch.setattr(dashboard, "_compute_dashboard_stats", lambda: next(values))

    first = dashboard.fetch_dashboard_stats()
    second = dashboard.fetch_dashboard_stats()

    assert first["client_count"] == 1
    assert second["client_count"] == 2


def test_dashboard_service_exposes_no_dead_invalidation_api() -> None:
    assert not hasattr(dashboard, "invalidate_dashboard_cache")


def test_dashboard_service_no_longer_uses_server_side_cache_calls() -> None:
    source = Path("server/services/dashboard.py").read_text(encoding="utf-8")

    assert "django.core.cache" not in source
    assert "cache.get(" not in source
    assert "cache.set(" not in source
    assert "cache.delete(" not in source


def test_dashboard_invalidation_call_sites_are_removed() -> None:
    for path in (
        Path("server/services/clients.py"),
        Path("server/services/listings.py"),
        Path("server/services/demandes.py"),
        Path("server/services/offers.py"),
        Path("server/services/crm_contracts.py"),
        Path("server/services/crm_visits.py"),
        Path("server/services/import_finalize_service.py"),
    ):
        assert "invalidate_dashboard_cache" not in path.read_text(encoding="utf-8")


def test_follow_up_code_no_longer_mentions_dashboard_invalidation() -> None:
    for path in (
        Path("server/services/import_finalize_service.py"),
        Path("server/services/import_status_payload.py"),
    ):
        assert "dashboard_invalidation" not in path.read_text(encoding="utf-8")
