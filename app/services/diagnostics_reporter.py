"""High-level diagnostics reporting flow for desktop UI triggers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import uuid4

from app.services.api_client import get_access_token, peek_access_token
from app.services.api_client_utils import decode_jwt_claims
from app.services.diagnostics_client import (
    build_signed_diagnostics_payload,
    submit_diagnostics_verification,
)
from app.services.diagnostics_signing import DiagnosticsSigner


@dataclass(frozen=True)
class DiagnosticsReportResult:
    valid: bool
    code: str
    detail: str
    request_id: str
    response: dict[str, object]


def _resolve_tenant_id_from_token() -> int | None:
    token = peek_access_token() or get_access_token()
    if not token:
        return None
    claims = decode_jwt_claims(token)
    if not isinstance(claims, dict):
        return None
    raw = claims.get("agency_id")
    if isinstance(raw, int) and raw > 0:
        return raw
    if isinstance(raw, str) and raw.strip().isdigit():
        parsed = int(raw.strip())
        return parsed if parsed > 0 else None
    return None


def _client_version() -> str:
    value = str(os.environ.get("IMMOAPP_CLIENT_VERSION", "") or "").strip()
    return value or "desktop"


def send_diagnostics_report(
    *,
    route_name: str,
    normalized_route: str,
    policy_id: str,
    error_code: str,
    device_id: str,
    signature_key_id: str,
    request_id: str | None = None,
    server_version: str | None = None,
) -> DiagnosticsReportResult:
    resolved_request_id = str(request_id or uuid4())
    signer = DiagnosticsSigner()
    signed = build_signed_diagnostics_payload(
        signer=signer,
        request_id=resolved_request_id,
        route_name=route_name,
        normalized_route=normalized_route,
        policy_id=policy_id,
        client_version=_client_version(),
        device_id=device_id,
        signature_key_id=signature_key_id,
        error_code=error_code,
        tenant_id=_resolve_tenant_id_from_token(),
        server_version=server_version,
    )
    response = submit_diagnostics_verification(signed)
    valid = bool(response.get("valid"))
    code = str(response.get("code") or ("SIGNATURE_VALID" if valid else "UNKNOWN"))
    detail = str(response.get("detail") or "").strip()
    if not detail:
        detail = "Diagnostics signature verified." if valid else "Diagnostics verification failed."
    return DiagnosticsReportResult(
        valid=valid,
        code=code,
        detail=detail,
        request_id=resolved_request_id,
        response=response,
    )


__all__ = ["DiagnosticsReportResult", "send_diagnostics_report"]
