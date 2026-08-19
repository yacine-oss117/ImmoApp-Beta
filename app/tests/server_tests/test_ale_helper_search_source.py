from __future__ import annotations

import core.encryption as enc_mod
from server.pg.uow import use_security_context
from server.services.ale_helper import normalize_ale_fields


def test_normalize_ale_fields_populates_search_source_not_hashes(monkeypatch):
    monkeypatch.setenv("ALE_MASTER_KEY", "test-master-key-32-bytes-minimum")
    monkeypatch.setenv("ALE_SEARCH_SECRET", "test-search-secret")
    monkeypatch.setenv("ALE_KDF_SALT", "test-kdf-salt-123456")
    monkeypatch.setenv("ALE_KEY_VERSION", "v1")
    monkeypatch.setenv("DJANGO_DEBUG", "1")
    monkeypatch.setenv("IMMOAPP_REQUIRE_ALE_KEY", "0")
    monkeypatch.setattr(enc_mod, "_instance", None)

    payload: dict[str, object] = {"family_name": "Märçô", "phone": "+213 555 11 22"}
    with use_security_context(agency_id=1, is_superuser=False):
        normalize_ale_fields(
            payload,
            [("family_name", True, True), ("phone", True, True)],
            changed_fields={"family_name", "phone"},
        )

    assert payload.get("family_name_search_src") == "Märçô"
    assert payload.get("phone_search_src") == "+213 555 11 22"
    assert "family_name_search_idx" not in payload
    assert "phone_search_idx" not in payload


def test_normalize_ale_fields_clears_blank_masked_strings_to_empty_strings():
    payload: dict[str, object] = {"address_line2": ""}

    normalize_ale_fields(
        payload,
        [("address_line2", True, False)],
        changed_fields={"address_line2"},
    )

    assert payload["address_line2"] == ""
    assert payload["address_line2_enc"] == ""
