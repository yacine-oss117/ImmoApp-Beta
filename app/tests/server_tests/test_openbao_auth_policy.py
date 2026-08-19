from __future__ import annotations

import pytest

import server.secret_store.openbao as openbao_module
from server.secret_store import loader
from server.secret_store.openbao import (
    OpenBaoError,
    _build_config,
    fetch_secret_data,
    normalize_secret_path,
)


def test_production_rejects_plain_bao_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMOAPP_ALLOW_ENV_SECRETS", "0")
    monkeypatch.setenv("BAO_TOKEN", "plain-token")
    monkeypatch.delenv("BAO_TOKEN_FILE", raising=False)
    monkeypatch.delenv("BAO_APPROLE_FILE", raising=False)
    monkeypatch.delenv("BAO_ROLE_ID", raising=False)
    monkeypatch.delenv("BAO_SECRET_ID", raising=False)
    with pytest.raises(RuntimeError, match="BAO_TOKEN"):
        loader._validate_openbao_auth_policy(production_mode=True)


def test_production_requires_token_file_or_approle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMOAPP_ALLOW_ENV_SECRETS", "0")
    monkeypatch.delenv("BAO_TOKEN", raising=False)
    monkeypatch.delenv("BAO_TOKEN_FILE", raising=False)
    monkeypatch.delenv("BAO_APPROLE_FILE", raising=False)
    monkeypatch.delenv("BAO_ROLE_ID", raising=False)
    monkeypatch.delenv("BAO_SECRET_ID", raising=False)
    with pytest.raises(RuntimeError, match="OpenBao auth is not configured"):
        loader._validate_openbao_auth_policy(production_mode=True)


def test_production_accepts_approle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMOAPP_ALLOW_ENV_SECRETS", "0")
    monkeypatch.delenv("BAO_TOKEN", raising=False)
    monkeypatch.delenv("BAO_TOKEN_FILE", raising=False)
    monkeypatch.delenv("BAO_APPROLE_FILE", raising=False)
    monkeypatch.setenv("BAO_ROLE_ID", "role")
    monkeypatch.setenv("BAO_SECRET_ID", "secret")
    loader._validate_openbao_auth_policy(production_mode=True)


def test_production_accepts_approle_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    approle_file = tmp_path / "openbao-approle.json"
    approle_file.write_text(
        '{"app_role_id":"role-from-file","app_secret_id":"secret-from-file"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("IMMOAPP_ALLOW_ENV_SECRETS", "0")
    monkeypatch.delenv("BAO_TOKEN", raising=False)
    monkeypatch.delenv("BAO_TOKEN_FILE", raising=False)
    monkeypatch.delenv("BAO_ROLE_ID", raising=False)
    monkeypatch.delenv("BAO_SECRET_ID", raising=False)
    monkeypatch.setenv("BAO_APPROLE_FILE", str(approle_file))
    loader._validate_openbao_auth_policy(production_mode=True)


def test_load_secrets_fails_before_fetch_when_plain_token_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(loader, "_ENV_LOADED", True)
    monkeypatch.setenv("IMMOAPP_SECRETS_BACKEND", "openbao")
    monkeypatch.setenv("IMMOAPP_ALLOW_ENV_SECRETS", "0")
    monkeypatch.setenv("IMMOAPP_ENV", "production")
    monkeypatch.setenv("DJANGO_DEBUG", "0")
    monkeypatch.setenv(
        "IMMOAPP_SECRETS_REQUIRED_KEYS",
        "DJANGO_SECRET_KEY,ALE_KEY_VERSION,ALE_MASTER_KEY,ALE_SEARCH_SECRET,ALE_KDF_SALT",
    )
    monkeypatch.setenv("BAO_TOKEN", "plain-token")
    monkeypatch.delenv("BAO_TOKEN_FILE", raising=False)
    monkeypatch.delenv("BAO_APPROLE_FILE", raising=False)
    monkeypatch.delenv("BAO_ROLE_ID", raising=False)
    monkeypatch.delenv("BAO_SECRET_ID", raising=False)

    called: list[str] = []

    def _fake_fetch(path: str) -> dict[str, str]:
        called.append(path)
        return {}

    monkeypatch.setattr(loader, "fetch_secret_data", _fake_fetch)

    with pytest.raises(RuntimeError, match="BAO_TOKEN"):
        loader.load_secrets()
    assert called == []


def test_load_secrets_allows_approle_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loader, "_ENV_LOADED", True)
    monkeypatch.setenv("IMMOAPP_SECRETS_BACKEND", "openbao")
    monkeypatch.setenv("IMMOAPP_ALLOW_ENV_SECRETS", "0")
    monkeypatch.setenv("IMMOAPP_ENV", "production")
    monkeypatch.setenv("DJANGO_DEBUG", "0")
    monkeypatch.setenv("IMMOAPP_SECRETS_OVERWRITE", "1")
    monkeypatch.setenv(
        "IMMOAPP_SECRETS_REQUIRED_KEYS",
        "DJANGO_SECRET_KEY,ALE_KEY_VERSION,ALE_MASTER_KEY,ALE_SEARCH_SECRET,ALE_KDF_SALT",
    )
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    monkeypatch.delenv("ALE_KEY_VERSION", raising=False)
    monkeypatch.delenv("ALE_MASTER_KEY", raising=False)
    monkeypatch.delenv("ALE_SEARCH_SECRET", raising=False)
    monkeypatch.delenv("ALE_KDF_SALT", raising=False)
    monkeypatch.delenv("BAO_TOKEN", raising=False)
    monkeypatch.delenv("BAO_TOKEN_FILE", raising=False)
    monkeypatch.delenv("BAO_APPROLE_FILE", raising=False)
    monkeypatch.setenv("BAO_ROLE_ID", "role")
    monkeypatch.setenv("BAO_SECRET_ID", "secret")

    monkeypatch.setattr(
        loader,
        "fetch_secret_data",
        lambda _path: {
            "DJANGO_SECRET_KEY": "k",
            "ALE_KEY_VERSION": "v1",
            "ALE_MASTER_KEY": "master",
            "ALE_SEARCH_SECRET": "search",
            "ALE_KDF_SALT": "salt",
        },
    )

    loaded = loader.load_secrets()
    assert loaded["DJANGO_SECRET_KEY"] == "k"


def test_openbao_config_reads_token_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    token_file = tmp_path / "bao.token"
    token_file.write_text("token-from-file\n", encoding="utf-8")
    monkeypatch.setenv("BAO_TOKEN_FILE", str(token_file))
    monkeypatch.delenv("BAO_TOKEN", raising=False)
    config = _build_config()
    assert config.token == "token-from-file"


def test_openbao_config_fails_for_missing_token_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAO_TOKEN_FILE", r"C:\does-not-exist\bao.token")
    monkeypatch.delenv("BAO_TOKEN", raising=False)
    with pytest.raises(OpenBaoError, match="Failed to read BAO_TOKEN_FILE"):
        _build_config()


def test_openbao_config_reads_approle_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    approle_file = tmp_path / "openbao-approle.json"
    approle_file.write_text(
        '{"app_role_id":"role-from-file","app_secret_id":"secret-from-file"}',
        encoding="utf-8",
    )
    monkeypatch.delenv("BAO_TOKEN_FILE", raising=False)
    monkeypatch.delenv("BAO_TOKEN", raising=False)
    monkeypatch.delenv("BAO_ROLE_ID", raising=False)
    monkeypatch.delenv("BAO_SECRET_ID", raising=False)
    monkeypatch.setenv("BAO_APPROLE_FILE", str(approle_file))
    config = _build_config()
    assert config.role_id == "role-from-file"
    assert config.secret_id == "secret-from-file"


def test_openbao_config_rejects_windows_approle_file_in_non_windows_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(openbao_module.os, "name", "posix", raising=False)
    monkeypatch.delenv("BAO_TOKEN_FILE", raising=False)
    monkeypatch.delenv("BAO_TOKEN", raising=False)
    monkeypatch.delenv("BAO_ROLE_ID", raising=False)
    monkeypatch.delenv("BAO_SECRET_ID", raising=False)
    monkeypatch.setenv("BAO_APPROLE_FILE", r"C:\ProgramData\ImmoApp\secrets\openbao-approle.json")
    with pytest.raises(OpenBaoError, match="Windows host path"):
        _build_config()


def test_openbao_config_rejects_windows_token_file_in_non_windows_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(openbao_module.os, "name", "posix", raising=False)
    monkeypatch.setenv("BAO_TOKEN_FILE", r"C:\ProgramData\ImmoApp\secrets\openbao.token")
    monkeypatch.delenv("BAO_TOKEN", raising=False)
    with pytest.raises(OpenBaoError, match="Windows host path"):
        _build_config()


def test_normalize_secret_path_accepts_kv_v2_data_path() -> None:
    assert normalize_secret_path("secret/data/immoapp/dev") == "secret/data/immoapp/dev"


def test_normalize_secret_path_upgrades_logical_kv_path() -> None:
    assert normalize_secret_path("secret/immoapp/dev") == "secret/data/immoapp/dev"


def test_fetch_secret_data_uses_normalized_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAO_ADDR", "http://openbao:8200")
    monkeypatch.setenv("BAO_TOKEN", "token")
    monkeypatch.delenv("BAO_TOKEN_FILE", raising=False)
    monkeypatch.delenv("BAO_APPROLE_FILE", raising=False)
    monkeypatch.delenv("BAO_ROLE_ID", raising=False)
    monkeypatch.delenv("BAO_SECRET_ID", raising=False)

    observed: dict[str, str] = {}

    def _fake_request(
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        payload=None,
        timeout: float,
        verify_ssl: bool,
    ) -> dict[str, object]:
        observed["method"] = method
        observed["url"] = url
        observed["token"] = str((headers or {}).get("X-Vault-Token", ""))
        return {"data": {"data": {"POSTGRES_PASSWORD": "secret"}}}

    monkeypatch.setattr(openbao_module, "_request_json", _fake_request)

    payload = fetch_secret_data("secret/immoapp/dev")
    assert observed["method"] == "GET"
    assert observed["url"] == "http://openbao:8200/v1/secret/data/immoapp/dev"
    assert observed["token"] == "token"
    assert payload["POSTGRES_PASSWORD"] == "secret"


def test_strict_openbao_rejects_plain_token_even_in_non_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMMOAPP_ALLOW_ENV_SECRETS", "0")
    monkeypatch.setenv("BAO_TOKEN", "plain-token")
    monkeypatch.delenv("BAO_TOKEN_FILE", raising=False)
    monkeypatch.delenv("BAO_APPROLE_FILE", raising=False)
    monkeypatch.delenv("BAO_ROLE_ID", raising=False)
    monkeypatch.delenv("BAO_SECRET_ID", raising=False)
    with pytest.raises(RuntimeError, match="BAO_TOKEN"):
        loader._validate_openbao_auth_policy(production_mode=False)


def test_non_strict_non_production_allows_plain_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMOAPP_ALLOW_ENV_SECRETS", "1")
    monkeypatch.setenv("BAO_TOKEN", "plain-token")
    monkeypatch.delenv("BAO_TOKEN_FILE", raising=False)
    monkeypatch.delenv("BAO_APPROLE_FILE", raising=False)
    monkeypatch.delenv("BAO_ROLE_ID", raising=False)
    monkeypatch.delenv("BAO_SECRET_ID", raising=False)
    loader._validate_openbao_auth_policy(production_mode=False)
