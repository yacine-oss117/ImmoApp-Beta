"""End-to-end diagnostics export + sign + verify client flow."""

from __future__ import annotations

from typing import Any

from app.services.api_client import api_post
from app.services.api_client_utils import as_dict

from .diagnostics_export import build_diagnostics_export_payload
from .diagnostics_signing import DiagnosticsSigner, SignedDiagnosticsPayload


def build_signed_diagnostics_payload(
    *,
    signer: DiagnosticsSigner,
    request_id: str,
    route_name: str,
    normalized_route: str,
    policy_id: str,
    client_version: str,
    device_id: str,
    signature_key_id: str,
    error_code: str,
    tenant_id: int | str | None = None,
    server_version: str | None = None,
    timestamp_iso: str | None = None,
) -> SignedDiagnosticsPayload:
    payload = build_diagnostics_export_payload(
        request_id=request_id,
        route_name=route_name,
        normalized_route=normalized_route,
        policy_id=policy_id,
        client_version=client_version,
        device_id=device_id,
        error_code=error_code,
        tenant_id=tenant_id,
        server_version=server_version,
        timestamp_iso=timestamp_iso,
    )
    return signer.sign_payload(
        payload=payload,
        device_id=device_id,
        signature_key_id=signature_key_id,
    )


def submit_diagnostics_verification(
    signed_payload: SignedDiagnosticsPayload,
) -> dict[str, Any]:
    result = api_post("diagnostics/verify/", signed_payload.to_verify_request())
    if result is None:
        return {}
    return as_dict(result)


__all__ = ["build_signed_diagnostics_payload", "submit_diagnostics_verification"]
