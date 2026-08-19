from __future__ import annotations

from pathlib import Path


def _assert_contains(path: str, token: str) -> None:
    text = Path(path).read_text(encoding="utf-8")
    assert token in text, f"{path} must include {token!r}"


def test_users_write_endpoints_require_step_up() -> None:
    path = "server/api/views_users.py"
    _assert_contains(path, "from .step_up import require_step_up")
    _assert_contains(path, 'if request.method == "POST":')
    _assert_contains(path, 'if request.method == "PUT":')
    _assert_contains(path, "step_up_response = require_step_up(request)")


def test_diagnostics_key_endpoints_require_step_up() -> None:
    path = "server/api/views_diagnostics_keys.py"
    _assert_contains(path, "from .step_up import require_step_up")
    _assert_contains(path, "step_up_response = require_step_up(request)")
