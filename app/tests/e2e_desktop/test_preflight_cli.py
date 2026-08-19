from __future__ import annotations

import json

import pytest

from app.tests.e2e_desktop import preflight_cli
from app.tests.e2e_desktop.backend import BackendPreflightResult


def test_preflight_cli_success_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _ready(*args: object, **kwargs: object) -> BackendPreflightResult:
        return BackendPreflightResult(
            base_url="http://127.0.0.1:8000",
            expected_code_identity={"source_fingerprint": "expected"},
            actual_identity={
                "code_identity": {"source_fingerprint": "expected"},
                "e2e_test_mode": True,
                "runtime_source_mode": "image",
                "route_presence": {"e2e/runtime/identity/": True},
            },
            missing_routes=(),
            identity_match=True,
        )

    monkeypatch.setattr(preflight_cli.backend, "ensure_backend_ready", _ready)

    exit_code = preflight_cli.main(["--base-url", "http://127.0.0.1:8000"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert payload["base_url"] == "http://127.0.0.1:8000"
    assert payload["identity_match"] is True
    assert payload["actual_code_identity"]["source_fingerprint"] == "expected"


def test_preflight_cli_expected_failure_is_clean_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _fail(*args: object, **kwargs: object) -> BackendPreflightResult:
        raise RuntimeError("Desktop E2E backend preflight failed.\nReason: stale backend")

    monkeypatch.setattr(preflight_cli.backend, "ensure_backend_ready", _fail)

    exit_code = preflight_cli.main(["--base-url", "http://127.0.0.1:8000"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "Desktop E2E backend preflight failed." in captured.err
    assert "Reason: stale backend" in captured.err
    assert "Traceback" not in captured.err
