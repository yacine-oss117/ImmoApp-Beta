from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _module(path: str) -> ast.Module:
    return ast.parse(_read(path), filename=path)


def _function_names(path: str) -> set[str]:
    return {
        node.name
        for node in _module(path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _line_count(path: str) -> int:
    return len(_read(path).splitlines())


def _method_node(path: str, class_name: str, method_name: str) -> ast.FunctionDef:
    for node in _module(path).body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == method_name:
                return item
    raise AssertionError(f"{class_name}.{method_name} not found in {path}")


def _call_lines(method: ast.FunctionDef, dotted_name: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(method):
        if not isinstance(node, ast.Call):
            continue
        parts: list[str] = []
        current: ast.AST = node.func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        resolved = ".".join(reversed(parts))
        if resolved == dotted_name or resolved.endswith(f".{dotted_name}"):
            lines.append(node.lineno)
    return sorted(lines)


def _super_validate_lines(method: ast.FunctionDef) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(method):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "validate":
            continue
        value = func.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "super"
        ):
            lines.append(node.lineno)
    return sorted(lines)


def test_registration_lifecycle_stays_compatibility_façade() -> None:
    path = "server/services/registration_lifecycle.py"
    text = _read(path)
    names = _function_names(path)

    assert "registration_tokens" in text
    assert "registration_approval" in text
    assert "registration_invites" in text
    assert {
        "RegistrationUnavailableError",
        "InviteResendCooldownError",
        "EmailQueueUnavailableError",
    }.issubset({node.name for node in _module(path).body if isinstance(node, ast.ClassDef)})
    assert {
        "_public_base_url_with_source",
        "_load_registration_for_signed_token",
        "_registration_plain",
        "_issue_auth_tokens",
        "_safe_record_and_notify",
    }.issubset(names)
    assert _line_count(path) <= 500


def test_user_auth_lifecycle_extracts_token_mechanics() -> None:
    path = "server/services/user_auth_lifecycle.py"
    text = _read(path)
    names = _function_names(path)

    assert "server.services.auth_token_actions" in text
    assert "_issue_token_record" not in names
    assert "_consume_token_or_raise" not in names
    assert _line_count(path) <= 520


def test_auth_sessions_stays_thin_over_lifecycle_and_revocation_helpers() -> None:
    path = "server/services/auth_sessions.py"
    text = _read(path)
    names = _function_names(path)

    assert "session_lifecycle" in text
    assert "session_revocation" in text
    assert {
        "_refresh_days",
        "_session_lifetime",
        "_session_validate_cache_seconds",
        "_session_touch_min_interval_seconds",
        "_invalidate_validation_cache",
        "_to_uuid",
        "_token_iat_to_dt",
    }.isdisjoint(names)
    assert {
        "issue_session",
        "bind_refresh_jti",
        "touch_session",
        "validate_token_session",
        "revoke_user_sessions",
    }.issubset(names)
    assert _line_count(path) <= 100


def test_jwt_auth_does_not_cache_user_objects() -> None:
    text = _read("server/api/auth_session_jwt.py")

    assert "_AUTH_USER_CACHE" not in text
    assert "IMMOAPP_AUTH_USER_CACHE_TTL_SECONDS" not in text
    assert "super().get_user(validated_token)" in text
    assert "is_active" in text


def test_refresh_serializer_inactive_user_regression_is_directly_covered() -> None:
    text = _read("app/tests/server_tests/test_auth_sessions_contract.py")

    assert "test_deactivated_user_refresh_token_is_rejected_when_tracking_disabled" in text
    assert "test_deactivated_user_refresh_token_is_rejected_without_rotation" in text
    assert "test_revoked_session_refresh_token_is_rejected_before_rotation" in text
    assert "SessionAwareTokenRefreshSerializer" in text
    assert "users.deactivate_user" in text
    assert "AuthenticationFailed" in text


def test_refresh_serializer_validates_user_and_session_before_rotation() -> None:
    path = "server/api/auth_session_jwt.py"
    text = _read(path)
    method = _method_node(path, "SessionAwareTokenRefreshSerializer", "validate")

    assert (
        "if not _session_tracking_enabled():\n            return super().validate(attrs)"
        not in text
    )

    refresh_subject_lines = _call_lines(method, "_refresh_subject")
    session_validation_lines = _call_lines(method, "auth_sessions.validate_token_session")
    super_validate_lines = _super_validate_lines(method)

    assert refresh_subject_lines
    assert session_validation_lines
    assert super_validate_lines
    first_super_validate = min(super_validate_lines)
    assert max(refresh_subject_lines) < first_super_validate
    assert max(session_validation_lines) < first_super_validate


def test_session_validation_keeps_explicit_require_sid_contract() -> None:
    text = _read("server/services/session_lifecycle.py")
    parser_text = _read("core/env_flags.py")

    assert "from core.env_flags import require_session_id_claim" in text
    assert '"missing_session_id"' in text
    assert "require_session_id_claim()" in text
    assert 'return (False, "missing_session_id") if require_sid else (True, None)' in text
    assert "IMMOAPP_REQUIRE_SESSION_ID_CLAIM" in parser_text
    assert '"true"' not in text
    assert '"yes"' not in text
    assert '"on"' not in text


def test_strict_prod_config_enforces_tracking_requires_sid() -> None:
    text = _read("scripts/verify_prod_config.py")

    assert "def _checked_bool_env" in text
    assert "from core.env_flags import EnvBoolError, bool_env" in text
    assert "def _assert_auth_session_tracking_contract()" in text
    assert "IMMOAPP_AUTH_SESSION_TRACKING_ENABLED" in text
    assert "IMMOAPP_REQUIRE_SESSION_ID_CLAIM" in text
    assert '_checked_bool_env("IMMOAPP_AUTH_SESSION_TRACKING_ENABLED")' in text
    assert '_checked_bool_env("IMMOAPP_REQUIRE_SESSION_ID_CLAIM")' in text
    assert "tracking_enabled and not require_sid" in text
    assert "is required when" in text
    assert "in production." in text


def test_auth_session_flags_use_shared_boolean_parser() -> None:
    parser_text = _read("core/env_flags.py")
    jwt_text = _read("server/api/auth_session_jwt.py")
    registration_text = _read("server/services/registration_tokens.py")
    prod_config_text = _read("scripts/verify_prod_config.py")

    assert "BOOLEAN_TRUE_VALUES = frozenset" in parser_text
    assert '{"1", "true", "yes", "on"}' in parser_text
    assert '{"", "0", "false", "no", "off"}' in parser_text
    assert "from core.env_flags import auth_session_tracking_enabled" in jwt_text
    assert "from core.env_flags import auth_session_tracking_enabled" in registration_text
    assert "from core.env_flags import EnvBoolError, bool_env" in prod_config_text
    for path, text in {
        "server/api/auth_session_jwt.py": jwt_text,
        "server/services/registration_tokens.py": registration_text,
        "server/services/session_lifecycle.py": _read("server/services/session_lifecycle.py"),
        "scripts/verify_prod_config.py": prod_config_text,
    }.items():
        if path == "scripts/verify_prod_config.py":
            assert 'in {"1", "true", "yes", "on"}' not in text
        else:
            assert 'IMMOAPP_AUTH_SESSION_TRACKING_ENABLED", "0").strip()' not in text
            assert 'IMMOAPP_REQUIRE_SESSION_ID_CLAIM", "0").strip()' not in text


def test_verify_prod_config_has_no_anonymous_boolean_parser() -> None:
    text = _read("scripts/verify_prod_config.py")

    assert "def _is_truthy" not in text
    assert "<inline boolean>" not in text
    assert "parse_bool_env_value" not in text
    assert 'in {"1", "true", "yes", "on"}' not in text
    assert ".strip().lower() in" not in text
    assert '_checked_bool_env("IMMOAPP_PROD_CONFIG_STRICT")' in text
    assert '_checked_bool_env("IMMOAPP_AUTH_SESSION_TRACKING_ENABLED")' in text
    assert '_checked_bool_env("IMMOAPP_REQUIRE_SESSION_ID_CLAIM")' in text
    assert '_checked_bool_env("BAO_VERIFY_SSL_DOCKER")' in text
    assert "_checked_bool_env(name)" in text
    for name in (
        "SECURE_SSL_REDIRECT_DOCKER",
        "SESSION_COOKIE_SECURE_DOCKER",
        "CSRF_COOKIE_SECURE_DOCKER",
    ):
        assert f'"{name}"' in text


def test_jwt_authentication_validates_session_when_tracking_enabled() -> None:
    path = "server/api/auth_session_jwt.py"
    method = _method_node(path, "SessionAwareJWTAuthentication", "authenticate")
    tracking_lines = _call_lines(method, "_session_tracking_enabled")
    validation_lines = _call_lines(method, "auth_sessions.validate_token_session")

    assert tracking_lines
    assert validation_lines
    assert min(tracking_lines) < min(validation_lines)


def test_user_deactivation_paths_call_session_revocation_owner() -> None:
    text = _read("server/services/users_mutations.py")

    assert "auth_sessions.revoke_user_sessions" in text
    assert 'reason="user_deactivated"' in text


def test_permission_elevation_stays_thin_and_auditable() -> None:
    path = "server/services/permission_elevation.py"
    text = _read(path)
    names = _function_names(path)

    assert "permission_grant_queries" in text
    assert "permission_grant_workflow" in text
    assert {
        "_serialize_request",
        "_target_user_for_actor",
        "_require_owner_or_superuser",
    }.isdisjoint(names)
    assert {
        "request_elevation",
        "list_requests",
        "decide_request",
        "revoke_request",
        "has_effective_permission",
        "list_effective_permissions",
    }.issubset(names)
    assert _line_count(path) <= 220


def test_sensitive_auth_views_keep_step_up_guards() -> None:
    auth_sessions_view = _read("server/api/views_auth_sessions.py")
    user_permissions_view = _read("server/api/views_user_permissions.py")

    assert "require_step_up" in auth_sessions_view
    assert "require_step_up" in user_permissions_view
