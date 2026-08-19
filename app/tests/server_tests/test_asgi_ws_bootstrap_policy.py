from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ASGI_PATH = REPO_ROOT / "server/immoapp_server/asgi.py"


def test_asgi_ws_bootstrap_logs_exceptions() -> None:
    content = ASGI_PATH.read_text(encoding="utf-8")
    assert "logger.exception(" in content


def test_asgi_ws_bootstrap_has_explicit_fallback_flag() -> None:
    content = ASGI_PATH.read_text(encoding="utf-8")
    assert "IMMOAPP_ALLOW_HTTP_ONLY_ASGI_FALLBACK" in content
    assert 'if os.environ.get("IMMOAPP_ALLOW_HTTP_ONLY_ASGI_FALLBACK", "0") == "1":' in content


def test_asgi_ws_bootstrap_raises_without_fallback() -> None:
    content = ASGI_PATH.read_text(encoding="utf-8")
    assert "else:" in content
    assert "\n        raise" in content
