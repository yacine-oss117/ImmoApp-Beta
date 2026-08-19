from __future__ import annotations

from app.services import dashboard_cache as module
from app.services.offline_account_scope import OfflineAccountScope


def _scope(suffix: str) -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_dashboard_cache_is_scoped_by_account(monkeypatch) -> None:
    scope_a = _scope("dash-a")
    scope_b = _scope("dash-b")
    module._api_cache.clear()
    payloads = iter(
        [
            {"client_count": 1, "listing_count": 2},
            {"client_count": 7, "listing_count": 9},
        ]
    )
    monkeypatch.setattr(module, "api_get", lambda _path: next(payloads))

    monkeypatch.setattr(module, "get_active_account_scope", lambda: scope_a)
    assert module.refresh_dashboard_stats().client_count == 1

    monkeypatch.setattr(module, "get_active_account_scope", lambda: scope_b)
    assert module.refresh_dashboard_stats().client_count == 7

    monkeypatch.setattr(module, "get_active_account_scope", lambda: scope_a)
    assert module.get_dashboard_stats().client_count == 1
