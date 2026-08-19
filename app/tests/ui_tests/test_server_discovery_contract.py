from __future__ import annotations

import json
from typing import Any

import pytest

from app.services import server_discovery


def _discovery_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "immoapp_hub_discovery",
        "schema_version": 1,
        "hub_display_name": "Main Office",
        "front_door_url": "http://10.10.10.10:8000",
        "front_door_port": 8000,
        "protocol": "http",
        "health_path": "/api/v1/health/",
        "app_version": "1.0",
        "api_version": "v1",
        "machine_hostname_readonly": "HUB-PC",
    }
    payload.update(overrides)
    return payload


def test_json_discovery_accepts_safe_public_front_door_fields() -> None:
    parsed = server_discovery._parse_json_beacon(json.dumps(_discovery_payload()))

    assert parsed is not None
    assert parsed["hub_display_name"] == "Main Office"
    assert parsed["front_door_url"] == "http://10.10.10.10:8000"
    assert parsed["proof_scope"] == "front_door_discovery"
    assert parsed["connectable"] is True


@pytest.mark.parametrize(
    "field",
    ["apiKey", "clientSecret", "accessToken", "Authorization", "X-Amz-Signature"],
)
def test_json_discovery_rejects_secret_looking_fields(field: str) -> None:
    parsed = server_discovery._parse_json_beacon(
        json.dumps(_discovery_payload(**{field: "raw-secret"}))
    )

    assert parsed is None


def test_json_discovery_rejects_nested_secret_fields() -> None:
    parsed = server_discovery._parse_json_beacon(
        json.dumps(_discovery_payload(machine_hostname_readonly={"private_key": "raw"}))
    )

    assert parsed is None


def test_json_discovery_rejects_url_credentials() -> None:
    parsed = server_discovery._parse_json_beacon(
        json.dumps(_discovery_payload(front_door_url="http://user:pass@10.10.10.10:8000"))
    )

    assert parsed is None


@pytest.mark.parametrize("schema_version", ["abc", {}, []])
def test_json_discovery_rejects_malformed_schema_version(schema_version: object) -> None:
    parsed = server_discovery._parse_json_beacon(
        json.dumps(_discovery_payload(schema_version=schema_version))
    )

    assert parsed is None


def test_json_discovery_rejects_malformed_front_door_port() -> None:
    parsed = server_discovery._parse_json_beacon(
        json.dumps(_discovery_payload(front_door_port="abc"))
    )

    assert parsed is None


@pytest.mark.parametrize("payload", ["{", "[]", '"value"', "42"])
def test_json_discovery_rejects_malformed_or_non_object_json(payload: str) -> None:
    parsed = server_discovery._parse_json_beacon(payload)

    assert parsed is None


def test_json_discovery_rejects_unknown_fields() -> None:
    parsed = server_discovery._parse_json_beacon(
        json.dumps(_discovery_payload(internal_service_ports=[5432]))
    )

    assert parsed is None


def test_legacy_beacon_is_internal_only_and_not_connectable() -> None:
    parsed = server_discovery._parse_beacon("IMMOAPP_BEACON|10.10.10.10|18000|Agency|1.0")

    assert parsed is not None
    assert parsed["proof_scope"] == "internal_only"
    assert parsed["connectable"] is False
    assert "front_door_url" not in parsed
