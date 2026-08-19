from __future__ import annotations

import argparse

import pytest

from scripts.bootstrap_openbao_identity import (
    _default_app_role_name,
    _default_env_name,
    _default_secrets_path,
    _mask,
    _render_app_policy,
    _render_operator_policy,
    _resolve_admin_token,
    _split_kv_path,
)


def test_split_kv_path_accepts_kv_v2_path() -> None:
    mount, key = _split_kv_path("secret/data/immoapp")
    assert mount == "secret"
    assert key == "immoapp"


def test_split_kv_path_accepts_kv_style_without_data_segment() -> None:
    mount, key = _split_kv_path("secret/immoapp")
    assert mount == "secret"
    assert key == "immoapp"


def test_split_kv_path_rejects_missing_secret_key() -> None:
    with pytest.raises(RuntimeError, match="does not include a secret key path"):
        _split_kv_path("secret/data")


def test_render_app_policy_contains_read_paths() -> None:
    policy = _render_app_policy("secret/data/immoapp")
    assert 'path "secret/data/immoapp"' in policy
    assert 'capabilities = ["read"]' in policy
    assert 'path "secret/metadata/immoapp"' in policy


def test_render_operator_policy_contains_role_paths() -> None:
    policy = _render_operator_policy("secret/data/immoapp", "immoapp-server")
    assert 'path "auth/approle/role/immoapp-server"' in policy
    assert 'path "auth/approle/role/immoapp-server/*"' in policy
    assert 'path "secret/data/immoapp"' in policy


def test_mask_keeps_prefix_and_suffix() -> None:
    masked = _mask("abcdefghijklmnopqrstuvwxyz")
    assert masked.startswith("abcd...")
    assert masked.endswith("wxyz")


def test_default_env_name_prefers_immoapp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMOAPP_ENV", "staging")
    monkeypatch.setenv("DJANGO_DEBUG", "1")
    assert _default_env_name() == "staging"


def test_default_env_name_falls_back_to_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IMMOAPP_ENV", raising=False)
    monkeypatch.setenv("DJANGO_DEBUG", "1")
    assert _default_env_name() == "dev"


def test_default_role_and_path_are_env_scoped() -> None:
    assert _default_app_role_name("prod") == "immoapp-server-prod"
    assert _default_secrets_path("prod") == "secret/data/immoapp/prod"


def _args(*, admin_token: str = "", admin_token_file: str = "") -> argparse.Namespace:
    return argparse.Namespace(
        admin_token=admin_token,
        admin_token_file=admin_token_file,
    )


def test_resolve_admin_token_reads_token_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("BAO_TOKEN", raising=False)
    token_file = tmp_path / "admin.token"
    token_file.write_text("root-token\n", encoding="utf-8")
    token = _resolve_admin_token(_args(admin_token_file=str(token_file)))
    assert token == "root-token"


def test_resolve_admin_token_rejects_inline_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BAO_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="forbidden"):
        _resolve_admin_token(_args(admin_token="inline-token"))


def test_resolve_admin_token_rejects_plain_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAO_TOKEN", "inline-env-token")
    with pytest.raises(RuntimeError, match="BAO_TOKEN must stay empty"):
        _resolve_admin_token(_args())


def test_resolve_admin_token_requires_token_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BAO_TOKEN", raising=False)
    monkeypatch.delenv("BAO_TOKEN_FILE", raising=False)
    with pytest.raises(RuntimeError, match="Missing OpenBao admin token file"):
        _resolve_admin_token(_args())
