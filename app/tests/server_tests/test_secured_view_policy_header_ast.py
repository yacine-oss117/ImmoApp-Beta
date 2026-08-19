from __future__ import annotations

from pathlib import Path


def test_secured_view_attaches_policy_header() -> None:
    text = Path("server/api/secured_view.py").read_text(encoding="utf-8")
    assert "X-Request-Policy" in text
    assert "get_route_policy" in text
    assert "resolve_route_template" in text
