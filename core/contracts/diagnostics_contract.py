"""Shared diagnostics payload/signature contract."""

from __future__ import annotations

from dataclasses import dataclass

DIAGNOSTICS_PAYLOAD_VERSION = "v1"
DIAGNOSTICS_SCHEMA_VERSION = "v1"
DIAGNOSTICS_SIGNATURE_ALGORITHM_ED25519 = "ed25519"
DIAGNOSTICS_SIGNATURE_ALGORITHM_CNG_P256 = "ecdsa-p256-sha256"
DIAGNOSTICS_SIGNATURE_ALGORITHM = DIAGNOSTICS_SIGNATURE_ALGORITHM_ED25519
DIAGNOSTICS_SUPPORTED_SIGNATURE_ALGORITHMS: tuple[str, ...] = (
    DIAGNOSTICS_SIGNATURE_ALGORITHM_ED25519,
    DIAGNOSTICS_SIGNATURE_ALGORITHM_CNG_P256,
)

DIAGNOSTICS_EXPORT_FIELDS: tuple[str, ...] = (
    "request_id",
    "timestamp",
    "tenant_ref",
    "route_name",
    "normalized_route",
    "policy_id",
    "client_version",
    "device_id",
    "server_version",
    "error_code",
)

DIAGNOSTICS_FORBIDDEN_FIELDS: tuple[str, ...] = (
    "request_body",
    "authorization",
    "token",
    "password",
    "phone",
    "email",
)


@dataclass(frozen=True)
class DiagnosticsVerifyResult:
    valid: bool
    code: str
    detail: str


__all__ = [
    "DIAGNOSTICS_EXPORT_FIELDS",
    "DIAGNOSTICS_FORBIDDEN_FIELDS",
    "DIAGNOSTICS_PAYLOAD_VERSION",
    "DIAGNOSTICS_SCHEMA_VERSION",
    "DIAGNOSTICS_SIGNATURE_ALGORITHM",
    "DIAGNOSTICS_SIGNATURE_ALGORITHM_CNG_P256",
    "DIAGNOSTICS_SIGNATURE_ALGORITHM_ED25519",
    "DIAGNOSTICS_SUPPORTED_SIGNATURE_ALGORITHMS",
    "DiagnosticsVerifyResult",
]
