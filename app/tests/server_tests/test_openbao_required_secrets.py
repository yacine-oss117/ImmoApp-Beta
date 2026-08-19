from __future__ import annotations

import json

from server.secret_store import openbao_runtime_guard, openbao_runtime_seed
from server.secret_store.required_keys import DEFAULT_OPENBAO_REQUIRED_KEYS


def test_openbao_runtime_contract_requires_idempotency_hmac_key(
    monkeypatch,
    tmp_path,
) -> None:
    source = tmp_path / "runtime-secrets.json"
    source.write_text(
        json.dumps(
            {
                "DJANGO_SECRET_KEY": "django-secret",
                "ALE_KEY_VERSION": "v1",
                "ALE_MASTER_KEY": "ale-master",
                "ALE_SEARCH_SECRET": "ale-search",
                "ALE_KDF_SALT": "ale-salt",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("IMMOAPP_BOOTSTRAP_SECRETS_FILE", str(source))
    monkeypatch.delenv("IMMOAPP_SECRETS_REQUIRED_KEYS", raising=False)

    payload, resolved_source = openbao_runtime_seed._build_seed_payload()

    assert resolved_source == source
    assert payload["IMMOAPP_IDEMPOTENCY_HMAC_KEY"]
    assert "IMMOAPP_IDEMPOTENCY_HMAC_KEY" in DEFAULT_OPENBAO_REQUIRED_KEYS
    assert openbao_runtime_guard._required_keys() == list(DEFAULT_OPENBAO_REQUIRED_KEYS)


def test_explicit_openbao_required_keys_cannot_omit_idempotency_hmac(
    monkeypatch,
) -> None:
    monkeypatch.setenv("IMMOAPP_SECRETS_REQUIRED_KEYS", "DJANGO_SECRET_KEY")

    assert openbao_runtime_seed._required_keys() == [
        "DJANGO_SECRET_KEY",
        "IMMOAPP_IDEMPOTENCY_HMAC_KEY",
    ]
    assert openbao_runtime_guard._required_keys() == [
        "DJANGO_SECRET_KEY",
        "IMMOAPP_IDEMPOTENCY_HMAC_KEY",
    ]


def test_openbao_seed_drops_runtime_topology_from_legacy_source(
    monkeypatch,
    tmp_path,
) -> None:
    source = tmp_path / "runtime-secrets.json"
    source.write_text(
        json.dumps(
            {
                "DJANGO_SECRET_KEY": "django-secret",
                "ALE_KEY_VERSION": "v1",
                "ALE_MASTER_KEY": "ale-master",
                "ALE_SEARCH_SECRET": "ale-search",
                "ALE_KDF_SALT": "ale-salt",
                "IMMOAPP_IDEMPOTENCY_HMAC_KEY": "idem-key",
                "VALKEY_URL": "redis://localhost:6379/1",
                "CHANNEL_LAYER_URL": "redis://localhost:6379/3",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("IMMOAPP_BOOTSTRAP_SECRETS_FILE", str(source))
    monkeypatch.setenv("VALKEY_URL", "redis://valkey:6379/1")
    monkeypatch.setenv("CHANNEL_LAYER_URL", "redis://valkey:6379/3")

    payload, _ = openbao_runtime_seed._build_seed_payload()

    assert "VALKEY_URL" not in payload
    assert "CHANNEL_LAYER_URL" not in payload
