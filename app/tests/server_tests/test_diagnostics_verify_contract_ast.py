from __future__ import annotations

from pathlib import Path


def test_diagnostics_verify_route_contract() -> None:
    text = Path("server/api/views_diagnostics_verify.py").read_text(encoding="utf-8")
    assert '@route("diagnostics/verify/"' in text
    assert "DiagnosticsVerifySerializer" in text
    assert "verify_diagnostics_signature" in text
