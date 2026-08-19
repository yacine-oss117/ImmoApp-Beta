from __future__ import annotations

import os


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def test_public_base_url_prefers_explicit_env(monkeypatch) -> None:
    _ensure_django()
    from server.services import registration_lifecycle as module

    monkeypatch.setenv("IMMOAPP_PUBLIC_BASE_URL", "https://example.test/")

    base_url, source = module._public_base_url_with_source()  # noqa: SLF001

    assert base_url == "https://example.test"
    assert source == "env"


def test_public_base_url_defaults_to_local_proxy_inside_container(monkeypatch) -> None:
    _ensure_django()
    from server.services import registration_lifecycle as module

    monkeypatch.delenv("IMMOAPP_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", "/var/lib/immoapp")

    base_url, source = module._public_base_url_with_source()  # noqa: SLF001

    assert base_url == "https://localhost"
    assert source == "fallback_local_proxy"


def test_public_base_url_defaults_to_host_local_server_outside_container(monkeypatch) -> None:
    _ensure_django()
    from server.services import registration_lifecycle as module

    monkeypatch.delenv("IMMOAPP_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", r"C:\ProgramData\ImmoApp")

    base_url, source = module._public_base_url_with_source()  # noqa: SLF001

    assert base_url == "http://127.0.0.1:8000"
    assert source == "fallback_localhost"


def test_public_base_url_upgrades_legacy_local_http_env_inside_container(monkeypatch) -> None:
    _ensure_django()
    from server.services import registration_lifecycle as module

    monkeypatch.setenv("IMMOAPP_PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("IMMOAPP_APPDATA_ROOT", "/var/lib/immoapp")

    base_url, source = module._public_base_url_with_source()  # noqa: SLF001

    assert base_url == "https://localhost"
    assert source == "env_local_proxy_upgraded"
