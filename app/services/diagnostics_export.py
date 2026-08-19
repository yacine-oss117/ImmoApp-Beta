"""Client diagnostics export payload builder with strict redaction rules."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Mapping

from core.contracts.diagnostics_contract import (
    DIAGNOSTICS_EXPORT_FIELDS,
    DIAGNOSTICS_FORBIDDEN_FIELDS,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tenant_ref(tenant_id: int | str | None) -> str:
    if tenant_id is None:
        return "unknown"
    digest = hashlib.sha256(str(tenant_id).encode("utf-8")).hexdigest()
    return digest[:16]


def _sanitize_route(value: str) -> str:
    return str(value or "").split("?", 1)[0].strip()


def _assert_no_forbidden_fields(payload: Mapping[str, object]) -> None:
    forbidden = {name.lower() for name in DIAGNOSTICS_FORBIDDEN_FIELDS}
    for key in payload.keys():
        key_lower = str(key).strip().lower()
        if key_lower in forbidden:
            raise ValueError(f"Forbidden diagnostics field: {key}")


def build_diagnostics_export_payload(
    *,
    request_id: str,
    route_name: str,
    normalized_route: str,
    policy_id: str,
    client_version: str,
    device_id: str,
    error_code: str,
    tenant_id: int | str | None = None,
    server_version: str | None = None,
    timestamp_iso: str | None = None,
    extra_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build diagnostics payload constrained by the shared export schema contract."""

    if extra_context:
        _assert_no_forbidden_fields(extra_context)
    payload: dict[str, object] = {
        "request_id": str(request_id or "").strip(),
        "timestamp": str(timestamp_iso or _utc_now_iso()),
        "tenant_ref": _tenant_ref(tenant_id),
        "route_name": str(route_name or "").strip(),
        "normalized_route": _sanitize_route(normalized_route),
        "policy_id": str(policy_id or "").strip(),
        "client_version": str(client_version or "").strip(),
        "device_id": str(device_id or "").strip(),
        "server_version": str(server_version or "").strip() if server_version else "",
        "error_code": str(error_code or "").strip(),
    }
    # Enforce fixed schema keys and preserve deterministic field set.
    keys = set(payload.keys())
    expected = set(DIAGNOSTICS_EXPORT_FIELDS)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise ValueError(f"Diagnostics payload schema mismatch. missing={missing}, extra={extra}")
    _assert_no_forbidden_fields(payload)
    return payload


__all__ = ["build_diagnostics_export_payload"]
