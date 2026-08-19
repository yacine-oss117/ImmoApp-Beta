from __future__ import annotations

import pytest

from app.services import locations_repository as repo
from app.services.offline_account_scope import OfflineAccountScope


def _scope(suffix: str) -> OfflineAccountScope:
    return OfflineAccountScope(
        account_key=f"http://test|1|2|{suffix}",
        api_base="http://test",
        agency_id=1,
        user_id=2,
        account_dir=f"acct_{suffix}",
    )


def test_get_all_locations_returns_cached_values_on_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo._cached_locations = {}
    monkeypatch.setattr(repo, "get_active_account_scope", lambda: _scope("first"))

    monkeypatch.setattr(
        repo,
        "api_get",
        lambda _path: {"items": ["Hydra, Algiers - 16", "Ben Aknoun, Algiers - 16"]},
    )
    first = repo.get_all_locations()
    assert first == ["Hydra, Algiers - 16", "Ben Aknoun, Algiers - 16"]

    def _boom(_path: str) -> object:
        raise RuntimeError("temporary outage")

    monkeypatch.setattr(repo, "api_get", _boom)
    second = repo.get_all_locations()
    assert second == first


def test_add_location_updates_local_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    repo._cached_locations = {_scope("add").account_key: ["Hydra, Algiers - 16"]}
    monkeypatch.setattr(repo, "get_active_account_scope", lambda: _scope("add"))
    monkeypatch.setattr(repo, "api_post", lambda _path, _payload: {"created": True})

    created = repo.add_location("Bir Mourad Rais, Algiers - 16")
    assert created is True
    assert "Bir Mourad Rais, Algiers - 16" in repo._cached_locations[_scope("add").account_key]


def test_locations_cache_is_scoped_by_account(monkeypatch: pytest.MonkeyPatch) -> None:
    scope_a = _scope("loc-a")
    scope_b = _scope("loc-b")
    repo._cached_locations = {}
    payloads = iter(
        [
            {"items": ["Hydra, Algiers - 16"]},
            {"items": ["Bir Mourad Rais, Algiers - 16"]},
        ]
    )
    monkeypatch.setattr(repo, "api_get", lambda _path: next(payloads))

    monkeypatch.setattr(repo, "get_active_account_scope", lambda: scope_a)
    assert repo.get_all_locations() == ["Hydra, Algiers - 16"]

    monkeypatch.setattr(repo, "get_active_account_scope", lambda: scope_b)
    assert repo.get_all_locations() == ["Bir Mourad Rais, Algiers - 16"]

    monkeypatch.setattr(repo, "get_active_account_scope", lambda: scope_a)
    assert repo.peek_cached_locations() == ["Hydra, Algiers - 16"]
