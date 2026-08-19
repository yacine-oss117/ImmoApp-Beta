from __future__ import annotations

import pytest

import core.encryption as encryption_module
from core.blind_index import get_search_secret


def _reset_encryption_singleton() -> None:
    encryption_module._instance = None


def test_blind_index_requires_explicit_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALE_SEARCH_SECRET", raising=False)
    monkeypatch.delenv("ALE_SEARCH_SECRET_MASTER", raising=False)
    with pytest.raises(RuntimeError, match="ALE_SEARCH_SECRET_MASTER"):
        get_search_secret()


def test_encryption_requires_explicit_key_material(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALE_KEY_VERSION", "v1")
    monkeypatch.setenv("ALE_KDF_SALT", "test-kdf-salt-123456")
    monkeypatch.delenv("ALE_MASTER_KEY", raising=False)
    monkeypatch.delenv("ALE_MASTER_KEYS", raising=False)
    monkeypatch.delenv("ALE_MASTER_KEY_V1", raising=False)
    _reset_encryption_singleton()
    with pytest.raises(RuntimeError, match="master key material is required"):
        encryption_module.get_encryption_service()


def test_encryption_requires_explicit_kdf_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALE_KEY_VERSION", "v1")
    monkeypatch.setenv("ALE_MASTER_KEY", "test-master-key-32-bytes-minimum")
    monkeypatch.delenv("ALE_KDF_SALT", raising=False)
    _reset_encryption_singleton()
    with pytest.raises(RuntimeError, match="ALE_KDF_SALT"):
        encryption_module.get_encryption_service()
