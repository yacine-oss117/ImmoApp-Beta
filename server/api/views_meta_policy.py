"""Policy metadata endpoint for client/server contract introspection."""

from __future__ import annotations

import os

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core.contracts.diagnostics_contract import DIAGNOSTICS_SUPPORTED_SIGNATURE_ALGORITHMS
from core.contracts.http_policy import HTTP_POLICY_VERSION
from core.contracts.idempotency_canonical_json import CANONICAL_JSON_VERSION
from core.contracts.idempotency_contract import (
    IDEMPOTENCY_HMAC_PAYLOAD_VERSION,
    SUPPORTED_HMAC_PAYLOAD_VERSIONS,
)
from core.contracts.semantic_header_registry import (
    SEMANTIC_HEADERS,
    semantic_header_registry_hash,
)
from server.api.route_registry import route, route_policy_manifest
from server.api.secured_view import secured_api_view


@route("meta/policy/", order=140)
@secured_api_view(["GET"], permission_classes=[IsAuthenticated])
def meta_policy(request: Request) -> Response:
    _ = request
    return Response(
        {
            "policy_version": HTTP_POLICY_VERSION,
            "semantic_header_registry_hash": semantic_header_registry_hash(),
            "semantic_headers": list(SEMANTIC_HEADERS),
            "retry_classes": [
                "CHEAP_READ",
                "EXPENSIVE_READ",
                "IDEMPOTENCY_KEY_WRITE",
                "CAS_WRITE",
                "NO_RETRY",
            ],
            "cost_classes": ["CHEAP", "BOUNDED", "EXPENSIVE"],
            "replay_modes": ["NONE", "FULL_SAFE", "REFERENCE_ONLY"],
            "canonical_json_version": CANONICAL_JSON_VERSION,
            "idempotency_hmac_version": IDEMPOTENCY_HMAC_PAYLOAD_VERSION,
            "supported_hmac_payload_versions": list(SUPPORTED_HMAC_PAYLOAD_VERSIONS),
            "bank_grade_mode": {
                "diagnostics_signing_model": "B",
                "diagnostics_supported_algorithms": list(
                    DIAGNOSTICS_SUPPORTED_SIGNATURE_ALGORITHMS
                ),
                "diagnostics_non_exportable_private_key_required": (
                    os.environ.get("IMMOAPP_DIAGNOSTICS_REQUIRE_NON_EXPORTABLE") or ""
                )
                .strip()
                .lower()
                not in {"0", "false", "no", "off"},
                "enforce_explicit_route_policy": True,
                "enforce_idempotency_key_write": (
                    os.environ.get("IMMOAPP_ENFORCE_IDEMPOTENCY_KEY_WRITE") or ""
                )
                .strip()
                .lower()
                in {"1", "true", "yes", "on"},
                "strict_openbao_only": (os.environ.get("IMMOAPP_ALLOW_ENV_SECRETS") or "")
                .strip()
                .lower()
                not in {"1", "true", "yes", "on"},
            },
            "budget_tiers": {
                "alert_budget": "Operational early-warning targets (mandatory).",
                "contract_budget": "Optional hard SLA envelope (opt-in).",
                "rules": {
                    "requires_contract_for_sla_facing": True,
                    "alert_budget_must_be_stricter_or_equal": True,
                },
            },
            "routes": route_policy_manifest(),
        }
    )


__all__ = ["meta_policy"]
