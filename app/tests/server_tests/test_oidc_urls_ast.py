from __future__ import annotations

from pathlib import Path


def test_oidc_auth_routes_are_registered() -> None:
    urls_path = Path("server/immoapp_server/urls.py")
    text = urls_path.read_text(encoding="utf-8")
    assert '"api/auth/oidc/config/"' in text
    assert '"api/auth/oidc/token/"' in text
