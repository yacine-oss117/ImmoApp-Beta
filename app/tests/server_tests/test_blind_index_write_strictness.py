from __future__ import annotations

import pytest

from core.blind_index import blind_index_for_agency, blind_index_for_write
from server.pg.uow import use_security_context


def test_blind_index_for_write_requires_tenant_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALE_SEARCH_SECRET_MASTER", "tenant-master-secret")
    with pytest.raises(RuntimeError, match="Missing tenant context"):
        blind_index_for_write("0555123456")


def test_blind_index_for_write_uses_current_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALE_SEARCH_SECRET_MASTER", "tenant-master-secret")
    with use_security_context(agency_id=7, is_superuser=False):
        digest = blind_index_for_write("0555123456")
    assert isinstance(digest, str)
    assert len(digest) == 32


def test_blind_index_for_agency_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALE_SEARCH_SECRET_MASTER", "tenant-master-secret")
    first = blind_index_for_agency("0555123456", agency_id=2)
    second = blind_index_for_agency("0555123456", agency_id=2)
    assert first == second
