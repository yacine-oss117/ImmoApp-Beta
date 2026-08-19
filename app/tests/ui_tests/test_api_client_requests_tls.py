from __future__ import annotations

import threading
from pathlib import Path

from app.services import api_client_requests as module


def test_resolve_session_verify_uses_local_caddy_ca_for_https_localhost(
    monkeypatch, tmp_path: Path
) -> None:
    cert = (
        tmp_path
        / "data"
        / "caddy"
        / "data"
        / "caddy"
        / "pki"
        / "authorities"
        / "local"
        / "root.crt"
    )
    cert.parent.mkdir(parents=True, exist_ok=True)
    cert.write_text("dummy", encoding="utf-8")

    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(module, "get_api_base_url", lambda: "https://localhost")
    monkeypatch.setattr(module, "get_app_data_dir", lambda: tmp_path)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "unused-programdata"))

    assert module._resolve_session_verify() == str(cert)  # noqa: SLF001


def test_resolve_session_verify_keeps_default_for_non_local_https(monkeypatch) -> None:
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(module, "get_api_base_url", lambda: "https://example.test")

    assert module._resolve_session_verify() is True  # noqa: SLF001


def test_run_client_sets_immoapp_appdata_root_for_supported_path() -> None:
    text = Path("scripts/run_client.ps1").read_text(encoding="utf-8")
    assert "$env:IMMOAPP_APPDATA_ROOT = $APPDATA_ROOT" in text


def test_apply_tls_policy_logs_local_ca_bundle_only_once(monkeypatch, tmp_path: Path) -> None:
    cert = tmp_path / "root.crt"
    cert.write_text("dummy", encoding="utf-8")
    monkeypatch.setattr(module, "_resolve_session_verify", lambda: str(cert))
    monkeypatch.setattr(module, "_logged_verify_path", None)
    messages: list[str] = []
    monkeypatch.setattr(module.logger, "info", lambda message, value: messages.append(str(value)))

    class _Session:
        verify: str | bool = True

    session = _Session()

    module._apply_tls_policy(session)  # noqa: SLF001
    module._apply_tls_policy(session)  # noqa: SLF001

    assert session.verify == str(cert)
    assert messages == [str(cert)]


def test_get_session_is_thread_local(monkeypatch) -> None:
    class _FakeSession:
        def __init__(self) -> None:
            self.verify: str | bool = True

        def close(self) -> None:
            return None

    created: list[_FakeSession] = []

    class _Requests:
        @staticmethod
        def Session() -> _FakeSession:
            session = _FakeSession()
            created.append(session)
            return session

    monkeypatch.setattr(module, "get_requests", lambda: _Requests)
    monkeypatch.setattr(module, "_resolve_session_verify", lambda: True)
    monkeypatch.setattr(module, "_sessions_by_thread", {})

    main_session = module.get_session()
    assert module.get_session() is main_session

    threaded: list[_FakeSession] = []

    def _worker() -> None:
        threaded.append(module.get_session())
        module.close_session()

    thread = threading.Thread(target=_worker)
    thread.start()
    thread.join()

    assert len(created) == 2
    assert threaded[0] is not main_session

    module.close_session()
