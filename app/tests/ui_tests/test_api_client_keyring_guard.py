from __future__ import annotations

import time
from types import SimpleNamespace

from app.services import api_client_auth


def test_keyring_timeout_disables_runtime_persistence(monkeypatch) -> None:
    monkeypatch.setattr(api_client_auth, "_KEYRING_DISABLED", False)
    monkeypatch.setattr(api_client_auth, "_KEYRING_RUNTIME_DISABLED", False)
    monkeypatch.setattr(api_client_auth, "_KEYRING_PROBED", True)
    monkeypatch.setattr(api_client_auth, "_KEYRING_DISABLE_REASON", None)
    monkeypatch.setattr(api_client_auth, "_KEYRING_TIMEOUT_SECONDS", 0.1)

    def _slow_call(_keyring):
        time.sleep(0.5)
        return "late"

    value = api_client_auth._run_keyring_call("timeout-op", _slow_call, "default")
    assert value == "default"
    assert api_client_auth._KEYRING_RUNTIME_DISABLED is True


def test_keyring_runtime_disabled_skips_future_calls(monkeypatch) -> None:
    monkeypatch.setattr(api_client_auth, "_KEYRING_DISABLED", False)
    monkeypatch.setattr(api_client_auth, "_KEYRING_RUNTIME_DISABLED", True)
    monkeypatch.setattr(api_client_auth, "_KEYRING_PROBED", True)

    called = {"count": 0}

    def _callback(_keyring):
        called["count"] += 1
        return "value"

    value = api_client_auth._run_keyring_call("store-op", _callback, "default")
    assert value == "default"
    assert called["count"] == 0


def test_clear_token_missing_keyring_entry_does_not_disable_runtime(monkeypatch) -> None:
    class _DeleteMissingError(Exception):
        pass

    class _FakeKeyring:
        def delete_password(self, _service: str, _username: str) -> None:
            raise _DeleteMissingError("missing")

    fake_keyring = SimpleNamespace(
        errors=SimpleNamespace(PasswordDeleteError=_DeleteMissingError),
        delete_password=_FakeKeyring().delete_password,
    )

    monkeypatch.setattr(api_client_auth, "_KEYRING_DISABLED", False)
    monkeypatch.setattr(api_client_auth, "_KEYRING_RUNTIME_DISABLED", False)
    monkeypatch.setattr(api_client_auth, "_KEYRING_PROBED", True)
    monkeypatch.setattr(api_client_auth, "_KEYRING_DISABLE_REASON", None)
    monkeypatch.setattr(api_client_auth, "_get_keyring", lambda: fake_keyring)

    api_client_auth._clear_refresh_token("owner@example.com")

    assert api_client_auth._KEYRING_RUNTIME_DISABLED is False


def test_keyring_probe_disables_runtime_when_backend_unavailable(monkeypatch) -> None:
    class _FailBackend:
        __module__ = "keyring.backends.fail"
        __name__ = "Keyring"

    fake_keyring = SimpleNamespace(get_keyring=lambda: _FailBackend())
    monkeypatch.setattr(api_client_auth, "_KEYRING_DISABLED", False)
    monkeypatch.setattr(api_client_auth, "_KEYRING_RUNTIME_DISABLED", False)
    monkeypatch.setattr(api_client_auth, "_KEYRING_PROBED", False)
    monkeypatch.setattr(api_client_auth, "_KEYRING_DISABLE_REASON", None)
    monkeypatch.setattr(api_client_auth, "_get_keyring", lambda: fake_keyring)

    called = {"count": 0}

    def _callback(_keyring):
        called["count"] += 1
        return "value"

    value = api_client_auth._run_keyring_call("probe-op", _callback, "default")
    assert value == "default"
    assert called["count"] == 0
    assert api_client_auth._KEYRING_RUNTIME_DISABLED is True
    assert api_client_auth._KEYRING_DISABLE_REASON == "backend_unavailable"


def test_keyring_probe_skips_backend_check_when_not_supported(monkeypatch) -> None:
    fake_keyring = SimpleNamespace()
    monkeypatch.setattr(api_client_auth, "_KEYRING_DISABLED", False)
    monkeypatch.setattr(api_client_auth, "_KEYRING_RUNTIME_DISABLED", False)
    monkeypatch.setattr(api_client_auth, "_KEYRING_PROBED", False)
    monkeypatch.setattr(api_client_auth, "_KEYRING_DISABLE_REASON", None)
    monkeypatch.setattr(api_client_auth, "_get_keyring", lambda: fake_keyring)

    value = api_client_auth._run_keyring_call("probe-skip-op", lambda _keyring: "ok", "default")
    assert value == "ok"
    assert api_client_auth._KEYRING_RUNTIME_DISABLED is False
