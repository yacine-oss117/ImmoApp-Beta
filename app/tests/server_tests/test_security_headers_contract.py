from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import cast

import pytest
from django.http import HttpRequest, HttpResponse
from django.test import override_settings

REPO_ROOT = Path(__file__).resolve().parents[3]
STRICT_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self' data:; connect-src 'self'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)
BOOLEAN_TRUE_CASES = ("1", "true", "yes", "on", " TRUE ")
BOOLEAN_FALSE_CASES = (None, "", "0", "false", "no", "off", " OFF ")
STRICT_RUNTIME_BOOLEAN_NAMES = (
    "BAO_VERIFY_SSL_DOCKER",
    "SECURE_SSL_REDIRECT_DOCKER",
    "SESSION_COOKIE_SECURE_DOCKER",
    "CSRF_COOKIE_SECURE_DOCKER",
)


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def _response_from_security_stack() -> HttpResponse:
    _ensure_django()
    from server.immoapp_server.middleware import CspHeaderMiddleware
    from server.immoapp_server.security_middleware import SecurityHeadersMiddleware

    request = HttpRequest()
    request.method = "GET"
    security_headers = SecurityHeadersMiddleware(lambda _request: HttpResponse("ok"))

    def _security_response(security_request: HttpRequest) -> HttpResponse:
        return cast(HttpResponse, security_headers(security_request))

    handler = CspHeaderMiddleware(_security_response)
    return handler(request)


def _headers_named(response: HttpResponse, name: str) -> list[str]:
    return [value for key, value in response.items() if key.lower() == name.lower()]


def _set_valid_strict_prod_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMOAPP_PROD_CONFIG_STRICT", "1")
    monkeypatch.setenv("DJANGO_DEBUG", "0")
    monkeypatch.setenv("IMMOAPP_E2E_TEST_MODE", "0")
    monkeypatch.setenv("IMMOAPP_E2E_TEST_MODE_DOCKER", "0")
    monkeypatch.setenv("IMMOAPP_PUBLIC_BASE_URL", "https://app.example.test")
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "app.example.test")
    monkeypatch.setenv("IMMOAPP_TLS_DOMAIN", "app.example.test")
    monkeypatch.setenv("BAO_VERIFY_SSL_DOCKER", "1")
    monkeypatch.setenv("BAO_CACERT_DOCKER", "/run/secrets/openbao-ca.pem")
    monkeypatch.setenv("BAO_ADDR_DOCKER", "https://openbao.example.test:8200")
    monkeypatch.setenv("SECURE_SSL_REDIRECT_DOCKER", "1")
    monkeypatch.setenv("SESSION_COOKIE_SECURE_DOCKER", "1")
    monkeypatch.setenv("CSRF_COOKIE_SECURE_DOCKER", "1")
    monkeypatch.setenv("POSTGRES_ADMIN_PASSWORD", "prod-admin-secret")
    monkeypatch.setenv("POSTGRES_PASSWORD", "prod-app-secret")
    monkeypatch.setenv("RABBITMQ_PASSWORD", "prod-rabbit-secret")


def test_production_security_stack_writes_exactly_one_strict_csp_header() -> None:
    _ensure_django()
    with override_settings(DEBUG=False, CSP_HEADER=STRICT_CSP):
        response = _response_from_security_stack()

    csp_headers = _headers_named(response, "Content-Security-Policy")
    assert csp_headers == [STRICT_CSP]
    assert "script-src 'self'" in csp_headers[0]
    assert "script-src 'unsafe-inline'" not in csp_headers[0]
    assert "frame-ancestors 'none'" in csp_headers[0]
    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"


def test_security_headers_middleware_does_not_fallback_write_csp() -> None:
    _ensure_django()
    from server.immoapp_server.security_middleware import SecurityHeadersMiddleware

    request = HttpRequest()
    request.method = "GET"
    with override_settings(DEBUG=False, CSP_HEADER=STRICT_CSP):
        response = cast(
            HttpResponse,
            SecurityHeadersMiddleware(lambda _request: HttpResponse("ok"))(request),
        )

    assert "Content-Security-Policy" not in response
    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"


def test_debug_mode_does_not_emit_csp_from_production_middleware() -> None:
    _ensure_django()
    with override_settings(DEBUG=True, CSP_HEADER=STRICT_CSP):
        response = _response_from_security_stack()

    assert "Content-Security-Policy" not in response


def test_default_csp_header_has_no_inline_script() -> None:
    _ensure_django()
    from server.immoapp_server import settings_api

    assert "script-src 'unsafe-inline'" not in settings_api.CSP_HEADER
    assert "script-src 'self'" in settings_api.CSP_HEADER


def test_security_headers_source_does_not_own_csp() -> None:
    text = (REPO_ROOT / "server/immoapp_server/security_middleware.py").read_text(encoding="utf-8")

    assert "Content-Security-Policy" not in text


def test_hsts_remains_enabled_in_production_settings_source() -> None:
    text = (REPO_ROOT / "server/immoapp_server/settings_security.py").read_text(encoding="utf-8")

    assert "SECURE_HSTS_SECONDS = 31536000" in text
    assert "SECURE_HSTS_INCLUDE_SUBDOMAINS = True" in text
    assert "SECURE_HSTS_PRELOAD = True" in text


def test_strict_prod_config_rejects_inline_script_csp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verify_prod_config = importlib.import_module("verify_prod_config")
    monkeypatch.setenv("IMMOAPP_PROD_CONFIG_STRICT", "1")
    monkeypatch.setenv(
        "CSP_HEADER",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
    )

    with pytest.raises(AssertionError, match="unsafe-inline"):
        verify_prod_config._assert_csp_policy_contract()


def test_non_strict_local_csp_does_not_poison_default_csp_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verify_prod_config = importlib.import_module("verify_prod_config")
    monkeypatch.setenv("IMMOAPP_PROD_CONFIG_STRICT", "0")
    monkeypatch.setenv(
        "CSP_HEADER",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
    )

    verify_prod_config._assert_csp_policy_contract()


@pytest.mark.parametrize("raw", BOOLEAN_FALSE_CASES)
def test_strict_prod_config_requires_sid_claim_when_tracking_enabled(
    monkeypatch: pytest.MonkeyPatch,
    raw: str | None,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verify_prod_config = importlib.import_module("verify_prod_config")
    monkeypatch.setenv("IMMOAPP_PROD_CONFIG_STRICT", "1")
    monkeypatch.setenv("IMMOAPP_AUTH_SESSION_TRACKING_ENABLED", "1")
    if raw is None:
        monkeypatch.delenv("IMMOAPP_REQUIRE_SESSION_ID_CLAIM", raising=False)
    else:
        monkeypatch.setenv("IMMOAPP_REQUIRE_SESSION_ID_CLAIM", raw)

    with pytest.raises(
        AssertionError,
        match=(
            "IMMOAPP_REQUIRE_SESSION_ID_CLAIM=1 is required when "
            "IMMOAPP_AUTH_SESSION_TRACKING_ENABLED=1 in production"
        ),
    ):
        verify_prod_config._assert_auth_session_tracking_contract()


@pytest.mark.parametrize("raw", BOOLEAN_TRUE_CASES)
def test_strict_prod_config_accepts_truthy_tracked_sessions_with_required_sid(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verify_prod_config = importlib.import_module("verify_prod_config")
    monkeypatch.setenv("IMMOAPP_PROD_CONFIG_STRICT", "1")
    monkeypatch.setenv("IMMOAPP_AUTH_SESSION_TRACKING_ENABLED", raw)
    monkeypatch.setenv("IMMOAPP_REQUIRE_SESSION_ID_CLAIM", raw)

    verify_prod_config._assert_auth_session_tracking_contract()


def test_strict_prod_config_does_not_require_sid_when_tracking_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verify_prod_config = importlib.import_module("verify_prod_config")
    monkeypatch.setenv("IMMOAPP_PROD_CONFIG_STRICT", "1")
    monkeypatch.setenv("IMMOAPP_AUTH_SESSION_TRACKING_ENABLED", "0")
    monkeypatch.setenv("IMMOAPP_REQUIRE_SESSION_ID_CLAIM", "0")

    verify_prod_config._assert_auth_session_tracking_contract()


def test_non_strict_prod_config_keeps_sid_escape_hatch_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verify_prod_config = importlib.import_module("verify_prod_config")
    monkeypatch.setenv("IMMOAPP_PROD_CONFIG_STRICT", "0")
    monkeypatch.setenv("IMMOAPP_AUTH_SESSION_TRACKING_ENABLED", "1")
    monkeypatch.setenv("IMMOAPP_REQUIRE_SESSION_ID_CLAIM", "0")

    verify_prod_config._assert_auth_session_tracking_contract()


@pytest.mark.parametrize(
    ("tracking", "require_sid", "expected_name"),
    (
        ("enabled", "1", "IMMOAPP_AUTH_SESSION_TRACKING_ENABLED"),
        ("1", "enabled", "IMMOAPP_REQUIRE_SESSION_ID_CLAIM"),
    ),
)
def test_strict_prod_config_rejects_invalid_session_boolean_values(
    monkeypatch: pytest.MonkeyPatch,
    tracking: str,
    require_sid: str,
    expected_name: str,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verify_prod_config = importlib.import_module("verify_prod_config")
    monkeypatch.setenv("IMMOAPP_PROD_CONFIG_STRICT", "1")
    monkeypatch.setenv("IMMOAPP_AUTH_SESSION_TRACKING_ENABLED", tracking)
    monkeypatch.setenv("IMMOAPP_REQUIRE_SESSION_ID_CLAIM", require_sid)

    with pytest.raises(AssertionError, match=expected_name):
        verify_prod_config._assert_auth_session_tracking_contract()


def test_strict_prod_config_rejects_invalid_strict_mode_boolean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verify_prod_config = importlib.import_module("verify_prod_config")
    monkeypatch.setenv("IMMOAPP_PROD_CONFIG_STRICT", "enabled")

    with pytest.raises(AssertionError, match="IMMOAPP_PROD_CONFIG_STRICT"):
        verify_prod_config._assert_auth_session_tracking_contract()


@pytest.mark.parametrize("name", STRICT_RUNTIME_BOOLEAN_NAMES)
def test_strict_prod_config_rejects_invalid_runtime_boolean_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verify_prod_config = importlib.import_module("verify_prod_config")
    _set_valid_strict_prod_env(monkeypatch)
    monkeypatch.setenv(name, "enabled")

    with pytest.raises(AssertionError, match=name):
        verify_prod_config._assert_strict_prod_runtime_env()


@pytest.mark.parametrize("name", STRICT_RUNTIME_BOOLEAN_NAMES)
@pytest.mark.parametrize("raw", BOOLEAN_TRUE_CASES)
def test_strict_prod_config_accepts_truthy_runtime_boolean_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    raw: str,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verify_prod_config = importlib.import_module("verify_prod_config")
    _set_valid_strict_prod_env(monkeypatch)
    monkeypatch.setenv(name, raw)

    verify_prod_config._assert_strict_prod_runtime_env()


@pytest.mark.parametrize("name", STRICT_RUNTIME_BOOLEAN_NAMES)
@pytest.mark.parametrize("raw", BOOLEAN_FALSE_CASES)
def test_strict_prod_config_rejects_falsy_runtime_boolean_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    raw: str | None,
) -> None:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    verify_prod_config = importlib.import_module("verify_prod_config")
    _set_valid_strict_prod_env(monkeypatch)
    if raw is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, raw)

    with pytest.raises(AssertionError, match=name):
        verify_prod_config._assert_strict_prod_runtime_env()
