from __future__ import annotations

from pathlib import Path


def test_compliance_endpoints_require_owner_and_step_up() -> None:
    text = Path("server/api/views_compliance.py").read_text(encoding="utf-8")
    required_tokens = (
        "from .rbac import require_owner",
        "from .step_up import parse_step_up_claims, step_up_iat_to_datetime",
        "deny = require_owner(request)",
        "claims, step_up_error = parse_step_up_claims(request)",
        "step_up_verified_at = step_up_iat_to_datetime(",
    )
    for token in required_tokens:
        assert token in text


def test_compliance_endpoint_throttle_scopes_are_defined() -> None:
    text = Path("server/api/views_compliance.py").read_text(encoding="utf-8")
    required_tokens = (
        'view.throttle_scope = "compliance_export"',
        'view.throttle_scope = "compliance_delete"',
        "@throttle_classes([ScopedRateThrottle])",
    )
    for token in required_tokens:
        assert token in text
