from __future__ import annotations

import runpy
from pathlib import Path

import pytest
from django.test import override_settings

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

REPO_ROOT = Path(__file__).resolve().parents[3]


def _prepare_common_bootstrap_patches(
    monkeypatch: pytest.MonkeyPatch,
    *,
    raw_client: object | None,
) -> None:
    monkeypatch.setattr("server.secret_store.load_secrets", lambda: None)
    monkeypatch.setattr(
        "server.immoapp_server.observability.setup_observability",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr("server.immoapp_server.pycache.configure_pycache", lambda: None)
    monkeypatch.setattr(
        "server.services.cache_layers._default_cache_client",
        lambda: raw_client,
    )


@override_settings(IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT=True, DEBUG=True)
def test_wsgi_startup_fails_fast_when_explicit_strict_policy_requires_single_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_common_bootstrap_patches(monkeypatch, raw_client=None)
    monkeypatch.setattr(
        "django.core.wsgi.get_wsgi_application",
        lambda: (_ for _ in ()).throw(AssertionError("WSGI app init should not run")),
    )

    with pytest.raises(RuntimeError, match="IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT=1"):
        runpy.run_path(str(REPO_ROOT / "server/immoapp_server/wsgi.py"), run_name="__test_wsgi__")


@override_settings(IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT=True, DEBUG=True)
def test_asgi_startup_fails_fast_when_explicit_strict_policy_requires_single_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_common_bootstrap_patches(monkeypatch, raw_client=None)
    monkeypatch.setattr(
        "django.core.asgi.get_asgi_application",
        lambda: (_ for _ in ()).throw(AssertionError("ASGI app init should not run")),
    )

    with pytest.raises(RuntimeError, match="IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT=1"):
        runpy.run_path(str(REPO_ROOT / "server/immoapp_server/asgi.py"), run_name="__test_asgi__")


@override_settings(IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT=True, DEBUG=True)
def test_celery_startup_fails_fast_when_explicit_strict_policy_requires_single_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_common_bootstrap_patches(monkeypatch, raw_client=None)
    monkeypatch.setattr(
        "celery.Celery",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Celery app init should not run")
        ),
    )

    with pytest.raises(RuntimeError, match="IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT=1"):
        runpy.run_path(
            str(REPO_ROOT / "server/immoapp_server/celery.py"),
            run_name="__test_celery__",
        )


@override_settings(IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT=False, DEBUG=False)
def test_wsgi_startup_allows_explicit_degraded_mode_when_policy_disables_strictness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    _prepare_common_bootstrap_patches(monkeypatch, raw_client=None)
    monkeypatch.setattr("django.core.wsgi.get_wsgi_application", lambda: sentinel)

    namespace = runpy.run_path(
        str(REPO_ROOT / "server/immoapp_server/wsgi.py"),
        run_name="__test_wsgi_degraded__",
    )

    assert namespace["application"] is sentinel
