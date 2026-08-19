from __future__ import annotations

import hmac
from hashlib import sha256

from core.blind_index import (
    get_previous_search_key_version,
    get_search_key_version,
    get_search_secret,
    get_search_secret_set,
)


def test_search_secret_v1_matches_legacy_derivation(monkeypatch):
    monkeypatch.setenv("ALE_SEARCH_SECRET_MASTER", "master-secret")
    monkeypatch.setenv("ALE_SEARCH_KEY_VERSION", "v1")
    monkeypatch.delenv("ALE_SEARCH_KEY_PREVIOUS_VERSION", raising=False)

    expected = hmac.new(
        b"master-secret",
        b"agency:42",
        sha256,
    ).hexdigest()
    assert get_search_secret(agency_id=42, version="v1") == expected


def test_search_secret_versioned_derivation_differs_from_v1(monkeypatch):
    monkeypatch.setenv("ALE_SEARCH_SECRET_MASTER", "master-secret")
    monkeypatch.setenv("ALE_SEARCH_KEY_VERSION", "v2")
    monkeypatch.delenv("ALE_SEARCH_KEY_PREVIOUS_VERSION", raising=False)

    v1 = get_search_secret(agency_id=42, version="v1")
    v2 = get_search_secret(agency_id=42, version="v2")
    assert v1 != v2


def test_search_secret_set_uses_current_then_previous(monkeypatch):
    monkeypatch.setenv("ALE_SEARCH_SECRET_MASTER", "master-secret")
    monkeypatch.setenv("ALE_SEARCH_KEY_VERSION", "v3")
    monkeypatch.setenv("ALE_SEARCH_KEY_PREVIOUS_VERSION", "v2")

    assert get_search_key_version() == "v3"
    assert get_previous_search_key_version() == "v2"

    secrets = get_search_secret_set(agency_id=7)
    assert len(secrets) == 2
    assert secrets[0] == get_search_secret(agency_id=7, version="v3")
    assert secrets[1] == get_search_secret(agency_id=7, version="v2")
