from __future__ import annotations

from types import SimpleNamespace

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402

from server.api import views_import_admin  # noqa: E402


def _superuser() -> object:
    return SimpleNamespace(is_authenticated=True, is_superuser=True)


def _regular_user() -> object:
    return SimpleNamespace(is_authenticated=True, is_superuser=False)


def test_import_security_limits_status_requires_superuser() -> None:
    request = APIRequestFactory().get("/api/v1/import/admin/security-limits/")
    force_authenticate(request, user=_regular_user())

    response = views_import_admin.import_security_limits_status(request)

    assert response.status_code == 403


def test_import_security_limits_reload_returns_refreshed_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(
        views_import_admin,
        "reload_import_security_limits",
        lambda: SimpleNamespace(max_rows=22000),
    )
    monkeypatch.setattr(
        views_import_admin,
        "import_security_limits_snapshot",
        lambda: {"max_rows": 22000, "cache_policy": "process_cached_until_reload_or_restart"},
    )
    request = APIRequestFactory().post("/api/v1/import/admin/security-limits/reload/")
    force_authenticate(request, user=_superuser())

    response = views_import_admin.import_security_limits_reload(request)

    assert response.status_code == 200
    assert response.data["reloaded"] is True
    assert int(response.data["max_rows"]) == 22000
