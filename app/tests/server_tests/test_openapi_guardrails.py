"""
OpenAPI guardrails (static).

These checks ensure OpenAPI generation is wired and not accidentally removed.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).parents[3]


def test_openapi_routes_present() -> None:
    urls_text = (_REPO_ROOT / "server" / "immoapp_server" / "urls.py").read_text(encoding="utf-8")
    assert "SpectacularAPIView" in urls_text, "OpenAPI schema route removed."
    assert "api/schema/" in urls_text, "OpenAPI schema path missing."
    assert "SpectacularSwaggerView" in urls_text, "Swagger UI route removed."


def test_openapi_settings_present() -> None:
    base_text = (_REPO_ROOT / "server" / "immoapp_server" / "settings_base.py").read_text(
        encoding="utf-8"
    )
    api_text = (_REPO_ROOT / "server" / "immoapp_server" / "settings_api.py").read_text(
        encoding="utf-8"
    )
    assert "drf_spectacular" in base_text, "drf_spectacular missing from settings."
    assert "DEFAULT_SCHEMA_CLASS" in api_text, "DEFAULT_SCHEMA_CLASS missing."
    assert "drf_spectacular.openapi.AutoSchema" in api_text, "AutoSchema not configured."


def test_api_view_wrapper_sets_schema() -> None:
    view_text = (_REPO_ROOT / "server" / "api" / "api_view.py").read_text(encoding="utf-8")
    secured_text = (_REPO_ROOT / "server" / "api" / "secured_view.py").read_text(encoding="utf-8")
    assert "secured_api_view" in view_text, "api_view must expose secured_api_view wrapper."
    assert "extend_schema" in secured_text, "secured api wrapper no longer applies schema defaults."
