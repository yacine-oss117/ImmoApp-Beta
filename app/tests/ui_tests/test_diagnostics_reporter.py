from __future__ import annotations

from app.services import diagnostics_reporter


class _SignedPayload:
    def to_verify_request(self) -> dict[str, object]:
        return {"dummy": True}


def test_send_diagnostics_report_builds_and_submits(monkeypatch) -> None:
    called: dict[str, object] = {}

    def _fake_build_signed(**kwargs):
        called.update(kwargs)
        return _SignedPayload()

    def _fake_submit(_signed):
        return {
            "valid": True,
            "code": "SIGNATURE_VALID",
            "detail": "Diagnostics signature verified",
        }

    monkeypatch.setattr(diagnostics_reporter, "DiagnosticsSigner", lambda: object())
    monkeypatch.setattr(
        diagnostics_reporter, "build_signed_diagnostics_payload", _fake_build_signed
    )
    monkeypatch.setattr(diagnostics_reporter, "submit_diagnostics_verification", _fake_submit)
    monkeypatch.setattr(diagnostics_reporter, "_resolve_tenant_id_from_token", lambda: 22)
    monkeypatch.setenv("IMMOAPP_CLIENT_VERSION", "2.7.0")

    result = diagnostics_reporter.send_diagnostics_report(
        route_name="desktop.health.dialog",
        normalized_route="/desktop/settings/health",
        policy_id="desktop.settings.health",
        error_code="E_HEALTH",
        device_id="device-1",
        signature_key_id="sig-1",
        request_id="req-xyz",
    )

    assert result.valid is True
    assert result.code == "SIGNATURE_VALID"
    assert result.request_id == "req-xyz"
    assert called["client_version"] == "2.7.0"
    assert called["tenant_id"] == 22
    assert called["device_id"] == "device-1"
    assert called["signature_key_id"] == "sig-1"


def test_resolve_tenant_id_parses_token_claims(monkeypatch) -> None:
    monkeypatch.setattr(diagnostics_reporter, "peek_access_token", lambda: "token")
    monkeypatch.setattr(
        diagnostics_reporter,
        "decode_jwt_claims",
        lambda _token: {"agency_id": "17"},
    )
    assert diagnostics_reporter._resolve_tenant_id_from_token() == 17
