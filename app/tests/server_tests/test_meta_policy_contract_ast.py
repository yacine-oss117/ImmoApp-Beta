from __future__ import annotations

from pathlib import Path


def test_meta_policy_endpoint_exists() -> None:
    text = Path("server/api/views_meta_policy.py").read_text(encoding="utf-8")
    assert '@route("meta/policy/"' in text
    assert '"policy_version"' in text
    assert '"semantic_header_registry_hash"' in text
    assert '"canonical_json_version"' in text
    assert '"idempotency_hmac_version"' in text
    assert '"supported_hmac_payload_versions"' in text
    assert '"bank_grade_mode"' in text
    assert '"budget_tiers"' in text
    assert '"routes"' in text
