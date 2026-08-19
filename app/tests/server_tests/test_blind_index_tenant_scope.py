from __future__ import annotations

from core.blind_index import get_search_secret


def test_search_secret_is_tenant_derived(monkeypatch):
    monkeypatch.setenv("ALE_SEARCH_SECRET_MASTER", "tenant-master-secret")
    s1 = get_search_secret(agency_id=1)
    s2 = get_search_secret(agency_id=2)
    assert s1 != s2
