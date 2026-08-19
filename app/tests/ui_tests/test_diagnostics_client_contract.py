from __future__ import annotations

import pytest

from app.services.diagnostics_client import submit_diagnostics_verification
from app.services.diagnostics_export import build_diagnostics_export_payload
from app.services.diagnostics_signing import DiagnosticsSigner, InMemoryDiagnosticsKeyStore
from core.contracts.diagnostics_contract import DIAGNOSTICS_EXPORT_FIELDS


def test_build_diagnostics_export_payload_has_fixed_schema() -> None:
    payload = build_diagnostics_export_payload(
        request_id="req-1",
        route_name="clients.list",
        normalized_route="/api/v1/clients/",
        policy_id="route.clients",
        client_version="1.2.3",
        device_id="device-1",
        error_code="E_TEST",
        tenant_id=42,
    )
    assert set(payload.keys()) == set(DIAGNOSTICS_EXPORT_FIELDS)
    assert payload["tenant_ref"] != "42"
    assert len(str(payload["tenant_ref"])) == 16


def test_diagnostics_signing_roundtrip(monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_ALLOW_EXPORTABLE_DIAGNOSTICS_FALLBACK", "1")
    signer = DiagnosticsSigner(store=InMemoryDiagnosticsKeyStore())
    payload = build_diagnostics_export_payload(
        request_id="req-2",
        route_name="matches.all",
        normalized_route="/api/v1/matches/clients/all/",
        policy_id="route.matches_clients_all",
        client_version="1.2.3",
        device_id="device-2",
        error_code="E_TIMEOUT",
        tenant_id=7,
    )
    signed = signer.sign_payload(
        payload=payload,
        device_id="device-2",
        signature_key_id="diag-key-1",
    )
    assert signer.verify_locally(
        payload=payload,
        device_id="device-2",
        signature_key_id="diag-key-1",
        signature_b64=signed.signature,
    )
    tampered = dict(payload)
    tampered["error_code"] = "E_OTHER"
    assert not signer.verify_locally(
        payload=tampered,
        device_id="device-2",
        signature_key_id="diag-key-1",
        signature_b64=signed.signature,
    )


def test_submit_diagnostics_uses_verify_endpoint(monkeypatch) -> None:
    called: dict[str, object] = {}

    def _fake_api_post(path: str, payload: dict[str, object]) -> dict[str, object]:
        called["path"] = path
        called["payload"] = payload
        return {"code": "SIGNATURE_VALID", "valid": True}

    monkeypatch.setattr("app.services.diagnostics_client.api_post", _fake_api_post)
    monkeypatch.setenv("IMMOAPP_ALLOW_EXPORTABLE_DIAGNOSTICS_FALLBACK", "1")
    signer = DiagnosticsSigner(store=InMemoryDiagnosticsKeyStore())
    payload = build_diagnostics_export_payload(
        request_id="req-3",
        route_name="meta.policy",
        normalized_route="/api/v1/meta/policy/",
        policy_id="route.meta_policy",
        client_version="1.2.3",
        device_id="device-3",
        error_code="E_NONE",
    )
    signed = signer.sign_payload(
        payload=payload,
        device_id="device-3",
        signature_key_id="diag-key-2",
    )
    response = submit_diagnostics_verification(signed)
    assert called["path"] == "diagnostics/verify/"
    assert isinstance(called["payload"], dict)
    assert response.get("valid") is True


def test_diagnostics_signer_strict_mode_rejects_exportable_store(monkeypatch) -> None:
    monkeypatch.setenv("IMMOAPP_DIAGNOSTICS_REQUIRE_NON_EXPORTABLE", "1")
    monkeypatch.delenv("IMMOAPP_ALLOW_EXPORTABLE_DIAGNOSTICS_FALLBACK", raising=False)
    with pytest.raises(RuntimeError):
        DiagnosticsSigner(store=InMemoryDiagnosticsKeyStore())
