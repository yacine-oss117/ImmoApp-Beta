from __future__ import annotations

from app.services import agency_settings_cache as module
from app.services.offline_account_scope import OfflineAccountScope


def _scope(suffix: str) -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_agency_settings_cache_is_scoped_by_account(monkeypatch) -> None:
    scope_a = _scope("settings-a")
    scope_b = _scope("settings-b")
    module._settings_cache.clear()
    payloads = iter(
        [
            {"settings": {"agency_name": "Alpha Agency"}},
            {"settings": {"agency_name": "Beta Agency"}},
        ]
    )
    monkeypatch.setattr(module, "api_get", lambda _path: next(payloads))

    monkeypatch.setattr(module, "get_active_account_scope", lambda: scope_a)
    assert module.get_agency_name() == "Alpha Agency"

    monkeypatch.setattr(module, "get_active_account_scope", lambda: scope_b)
    assert module.get_agency_name() == "Beta Agency"

    monkeypatch.setattr(module, "get_active_account_scope", lambda: scope_a)
    assert module.get_agency_name() == "Alpha Agency"
