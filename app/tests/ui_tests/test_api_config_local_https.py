from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.services import api_config
from app.services.api_config import (
    get_api_config,
    normalize_api_base_url,
    normalize_hub_front_door_url,
    set_verified_api_config,
    verify_hub_front_door_url,
)


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def get(self, url: str, *, timeout: float) -> _FakeResponse:
        del timeout
        self.urls.append(url)
        return self.responses.pop(0)


def _patch_hub_probe_session(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[_FakeResponse],
) -> _FakeSession:
    from app.services import api_client_requests

    session = _FakeSession(responses)
    monkeypatch.setattr(api_client_requests, "get_session", lambda: session)
    return session


def test_normalize_api_base_url_preserves_explicit_local_https() -> None:
    assert normalize_api_base_url("https://localhost") == "https://localhost"
    assert normalize_api_base_url("https://127.0.0.1:8443") == "https://127.0.0.1:8443"


def test_normalize_api_base_url_defaults_unschemed_local_to_http() -> None:
    assert normalize_api_base_url("localhost:8000") == "http://localhost:8000"
    assert normalize_api_base_url("127.0.0.1:8443") == "http://127.0.0.1:8443"


def test_hub_front_door_normalization_rejects_workstation_localhost_and_internal_port() -> None:
    assert normalize_hub_front_door_url("main-office.local:8000") == "http://main-office.local:8000"
    with pytest.raises(ValueError):
        normalize_hub_front_door_url("http://localhost:8000")
    with pytest.raises(ValueError):
        normalize_hub_front_door_url("http://10.10.10.10:18000")


def test_verify_hub_front_door_rejects_missing_caddy_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_hub_probe_session(
        monkeypatch,
        [
            _FakeResponse(status_code=200),
            _FakeResponse(
                status_code=200,
                payload={"kind": "immoapp_hub_front_door_identity", "schema_version": 1},
            ),
        ],
    )

    with pytest.raises(ValueError, match="front door"):
        verify_hub_front_door_url("http://10.10.10.10:8000")


def test_verify_hub_front_door_rejects_invalid_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_hub_probe_session(
        monkeypatch,
        [
            _FakeResponse(status_code=200),
            _FakeResponse(status_code=200, headers={"X-ImmoApp-Front-Door": "caddy"}, payload={}),
        ],
    )

    with pytest.raises(ValueError, match="identity"):
        verify_hub_front_door_url("http://10.10.10.10:8000")


def test_verify_hub_front_door_requires_health_200(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_hub_probe_session(
        monkeypatch,
        [
            _FakeResponse(status_code=204),
            _FakeResponse(
                status_code=200,
                headers={"X-ImmoApp-Front-Door": "caddy"},
                payload={"kind": "immoapp_hub_front_door_identity", "schema_version": 1},
            ),
        ],
    )

    with pytest.raises(ValueError, match="health"):
        verify_hub_front_door_url("http://10.10.10.10:8000")


def test_set_verified_api_config_persists_only_after_front_door_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    _patch_hub_probe_session(
        monkeypatch,
        [
            _FakeResponse(status_code=200),
            _FakeResponse(
                status_code=200,
                headers={"X-ImmoApp-Front-Door": "caddy"},
                payload={
                    "kind": "immoapp_hub_front_door_identity",
                    "schema_version": 1,
                    "hub_display_name": "Main Office",
                    "api_version": "v1",
                },
            ),
        ],
    )

    verified = set_verified_api_config(
        base_url="10.10.10.10:8000",
        connection_source="manual",
    )

    assert verified["normalized_url"] == "http://10.10.10.10:8000"
    assert verified["hub_display_name"] == "Main Office"
    config = get_api_config()
    assert config.base_url == "http://10.10.10.10:8000"
    data = api_config._read_config_file()
    assert data["hub_display_name"] == "Main Office"
    assert data["connection_source"] == "manual"


def test_set_verified_api_config_rejects_dev_unverified_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_hub_probe_session(monkeypatch, [])

    with pytest.raises(ValueError, match="Unverified dev"):
        set_verified_api_config(
            base_url="http://10.10.10.10:8000",
            connection_source="local_dev_unverified",
        )


def test_get_api_config_accepts_utf8_bom_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    monkeypatch.delenv("IMMOAPP_API_BASE_URL", raising=False)
    monkeypatch.delenv("IMMOAPP_API_USERNAME", raising=False)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "client_api.json").write_text(
        '{"base_url":"127.0.0.1:8000","username":"owner"}',
        encoding="utf-8-sig",
    )

    config = get_api_config()

    assert config.base_url == "http://127.0.0.1:8000"
    assert config.username == "owner"


def test_get_api_config_env_override_ignores_stale_file_connection_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    monkeypatch.setenv("IMMOAPP_API_BASE_URL", "http://127.0.0.1:8000")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "client_api.json").write_text(
        json.dumps(
            {
                "base_url": "http://10.10.10.10:8000",
                "connection_source": "manual",
            }
        ),
        encoding="utf-8",
    )

    config = get_api_config()

    assert config.base_url == "http://127.0.0.1:8000"


def test_get_api_config_file_manual_source_applies_hub_front_door_normalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    monkeypatch.delenv("IMMOAPP_API_BASE_URL", raising=False)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "client_api.json").write_text(
        json.dumps(
            {
                "base_url": "10.10.10.10:8000",
                "connection_source": "manual",
            }
        ),
        encoding="utf-8",
    )

    config = get_api_config()

    assert config.base_url == "http://10.10.10.10:8000"


def test_get_api_config_file_local_hub_source_allows_localhost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", str(tmp_path))
    monkeypatch.delenv("IMMOAPP_API_BASE_URL", raising=False)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "client_api.json").write_text(
        json.dumps(
            {
                "base_url": "http://localhost:8000",
                "connection_source": "local_hub",
            }
        ),
        encoding="utf-8",
    )

    config = get_api_config()

    assert config.base_url == "http://localhost:8000"
