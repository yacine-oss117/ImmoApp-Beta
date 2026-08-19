from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from repo_layout import COMPOSE_PROD_YML, COMPOSE_YML

_WARNINGS: list[str] = []


def _checked_bool_env(name: str, *, default: bool = False) -> bool:
    from core.env_flags import EnvBoolError, bool_env

    try:
        return bool_env(name, default=default)
    except EnvBoolError as exc:
        raise AssertionError(str(exc)) from exc


def _is_strict_mode() -> bool:
    return _checked_bool_env("IMMOAPP_PROD_CONFIG_STRICT")


def _warn(message: str) -> None:
    _WARNINGS.append(message)
    print(f"verify_prod_config: WARNING: {message}")


def _set_defaults() -> None:
    os.environ.setdefault("POSTGRES_DB", "immoapp")
    os.environ.setdefault("POSTGRES_USER", "immoapp_app")
    os.environ.setdefault("POSTGRES_PASSWORD", "immoapp_app_password")
    os.environ.setdefault("POSTGRES_ADMIN_USER", "immoapp")
    os.environ.setdefault("POSTGRES_ADMIN_PASSWORD", "immoapp_admin_password")
    os.environ.setdefault(
        "CELERY_BROKER_URL", "amqp://immoapp:immoapp_rabbit_password@localhost:5672//"
    )
    os.environ.setdefault("DJANGO_DEBUG", "0")
    os.environ.setdefault("IMMOAPP_ENV", "production")
    os.environ.setdefault("IMMOAPP_MFA_ENFORCE_ROLES", "manager,owner")
    os.environ.setdefault("IMMOAPP_SKIP_CELERY_APP", "1")


def _set_import_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def _assert_no_schema_init_in_ready() -> None:
    text = Path("server/api/apps.py").read_text(encoding="utf-8")
    for token in ("ensure_schema", "warmup_pool", "assert_security_schema"):
        if token in text:
            raise AssertionError(f"apps.py should not call {token} in ApiConfig.ready()")


def _assert_celery_eager_off() -> None:
    text = Path("server/immoapp_server/settings_database.py").read_text(encoding="utf-8")
    if (
        'CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "0") == "1"'
        not in text
    ):
        raise AssertionError("CELERY_TASK_ALWAYS_EAGER must be env-gated with default 0.")
    if "CELERY_TASK_EAGER_PROPAGATES = CELERY_TASK_ALWAYS_EAGER" not in text:
        raise AssertionError("CELERY_TASK_EAGER_PROPAGATES must mirror CELERY_TASK_ALWAYS_EAGER.")
    if 'CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL")' not in text:
        raise AssertionError("CELERY_BROKER_URL must come from environment in production.")


def _assert_celery_reliability_defaults() -> None:
    text = Path("server/immoapp_server/settings_database.py").read_text(encoding="utf-8")
    required_tokens = (
        "CELERY_TASK_ACKS_LATE = True",
        "CELERY_TASK_REJECT_ON_WORKER_LOST = True",
        "CELERY_WORKER_PREFETCH_MULTIPLIER =",
        "CELERY_TASK_TRACK_STARTED = True",
        "CELERY_TASK_SOFT_TIME_LIMIT =",
        "CELERY_TASK_TIME_LIMIT =",
        'CELERY_TASK_DEFAULT_EXCHANGE = "immoapp.tasks"',
        'CELERY_TASK_DEFAULT_EXCHANGE_TYPE = "direct"',
        'CELERY_TASK_DEFAULT_QUEUE = "default"',
        'CELERY_TASK_DEFAULT_ROUTING_KEY = "default"',
        "CELERY_TASK_QUEUES =",
        'Queue("default", routing_key="default")',
        'Queue("maintenance", routing_key="maintenance")',
        'Queue("rebuild_batch", routing_key="rebuild_batch")',
        'Queue("match_pairs", routing_key="match_pairs")',
    )
    for token in required_tokens:
        if token not in text:
            raise AssertionError(f"Missing Celery reliability setting: {token}")


def _assert_openbao_only_policy() -> None:
    text = Path("server/secret_store/loader.py").read_text(encoding="utf-8")
    required_tokens = (
        'backend = os.environ.get("IMMOAPP_SECRETS_BACKEND", "openbao").strip().lower()',
        "def _strict_openbao_only()",
        "IMMOAPP_ALLOW_ENV_SECRETS",
        "OpenBao-only policy active.",
    )
    for token in required_tokens:
        if token not in text:
            raise AssertionError(f"Missing OpenBao-only enforcement token: {token}")


def _assert_schema_mode_guard() -> None:
    from server.pg import schema as schema_mod

    for invalid_mode in ("auto", "legacy"):
        os.environ["IMMOAPP_SCHEMA_MODE"] = invalid_mode
        try:
            schema_mod.ensure_schema()
        except RuntimeError:
            continue
        raise AssertionError(f"Schema mode guard did not block unsupported mode: {invalid_mode}")


def _assert_db_prepare_command_exists() -> None:
    command_path = Path("server/api/management/commands/immoapp_db_prepare.py")
    if not command_path.exists():
        raise AssertionError("Missing deployment schema command: immoapp_db_prepare.py")
    text = command_path.read_text(encoding="utf-8")
    for token in ("ensure_schema()", "assert_security_schema", "warmup_pool"):
        if token not in text:
            raise AssertionError(f"immoapp_db_prepare.py missing required step: {token}")


def _assert_notifications_purge_is_scheduled() -> None:
    text = Path("server/immoapp_server/settings_database.py").read_text(encoding="utf-8")
    if '"purge-notifications-daily"' not in text:
        raise AssertionError("Celery beat schedule missing purge-notifications-daily entry.")
    if (
        '"server.api.tasks_notifications.purge_notifications_task"' not in text
        and '"server.api.tasks.purge_notifications_task"' not in text
    ):
        raise AssertionError("Celery beat schedule missing purge_notifications_task binding.")
    if '"purge-old-auth-events-daily"' not in text:
        raise AssertionError("Celery beat schedule missing purge-old-auth-events-daily entry.")
    if '"server.api.tasks_maintenance.purge_old_auth_events_task"' not in text:
        raise AssertionError("Celery beat schedule missing purge_old_auth_events_task binding.")


def _assert_maintenance_crontab_schedule() -> None:
    text = Path("server/immoapp_server/settings_database.py").read_text(encoding="utf-8")
    forbidden_tokens = (
        '"schedule": 60 * 60 * 24',
        '"schedule": 60 * 60 * 24 * 7',
    )
    for token in forbidden_tokens:
        if token in text:
            raise AssertionError(f"Legacy interval schedule token must not be used: {token}")
    required_tokens = (
        '"purge-old-audit-logs-daily"',
        '"purge-old-auth-events-daily"',
        '"purge-deleted-storage-daily"',
        '"purge-pending-storage-daily"',
        '"purge-ale-pii-daily"',
        '"ale-rotation-alert-daily"',
        '"schedule": crontab(minute=0, hour=2)',
        '"schedule": crontab(minute=20, hour=2)',
        '"schedule": crontab(minute=40, hour=2)',
        '"schedule": crontab(minute=0, hour=3)',
        '"schedule": crontab(minute=20, hour=3)',
        '"schedule": crontab(minute=40, hour=3)',
    )
    for token in required_tokens:
        if token not in text:
            raise AssertionError(f"Missing required maintenance crontab token: {token}")


def _assert_worker_beat_healthchecks_enabled() -> None:
    compose = COMPOSE_YML.read_text(encoding="utf-8")
    if "worker:" not in compose or "worker-match:" not in compose or "beat:" not in compose:
        raise AssertionError(
            "compose.yml missing worker, worker-match, or beat service definitions."
        )
    if "disable: true" in compose:
        raise AssertionError("Worker/beat healthcheck disable flag is not allowed.")
    required_tokens = (
        "inspect ping -d",
        "--pidfile=/tmp/celerybeat.pid",
        "kill -0 $(cat /tmp/celerybeat.pid)",
        "-Q match_pairs -c ${CELERY_MATCH_PAIRS_CONCURRENCY_DOCKER:?hub_runtime_profile_required}",
    )
    for token in required_tokens:
        if token not in compose:
            raise AssertionError(f"Missing worker/beat healthcheck token: {token}")


def _assert_step_up_controls() -> None:
    urls_text = Path("server/immoapp_server/urls.py").read_text(encoding="utf-8")
    if 'path("api/auth/step-up/", StepUpAuthView.as_view(), name="step_up_auth")' not in urls_text:
        raise AssertionError("Missing /api/auth/step-up/ endpoint registration.")

    settings_text = Path("server/immoapp_server/settings_api.py").read_text(encoding="utf-8")
    if '"step_up_auth": os.environ.get("STEP_UP_AUTH_THROTTLE", "20/hour")' not in settings_text:
        raise AssertionError("Missing step_up_auth throttle scope in API settings.")

    step_up_text = Path("server/api/step_up.py").read_text(encoding="utf-8")
    if 'os.environ.get("IMMOAPP_REQUIRE_STEP_UP_SENSITIVE", "1")' not in step_up_text:
        raise AssertionError("Step-up runtime policy must default to required mode.")


def _csp_directive_values(csp: str, directive: str) -> list[str]:
    for raw_part in csp.split(";"):
        part = raw_part.strip()
        if not part:
            continue
        tokens = part.split()
        if tokens and tokens[0].lower() == directive.lower():
            return tokens[1:]
    return []


def _assert_csp_policy_contract() -> None:
    settings_text = Path("server/immoapp_server/settings_api.py").read_text(encoding="utf-8")
    security_middleware_text = Path("server/immoapp_server/security_middleware.py").read_text(
        encoding="utf-8"
    )

    if "CSP_HEADER" not in settings_text:
        raise AssertionError("CSP_HEADER must be owned by settings_api.py.")
    if "Content-Security-Policy" in security_middleware_text:
        raise AssertionError("SecurityHeadersMiddleware must not write Content-Security-Policy.")

    env_csp = os.environ.get("CSP_HEADER")
    os.environ.pop("CSP_HEADER", None)
    settings_api = importlib.import_module("server.immoapp_server.settings_api")
    try:
        settings_api = importlib.reload(settings_api)
        csp = str(settings_api.CSP_HEADER or "")
    finally:
        if env_csp is None:
            os.environ.pop("CSP_HEADER", None)
        else:
            os.environ["CSP_HEADER"] = env_csp
        importlib.reload(settings_api)

    script_src = _csp_directive_values(csp, "script-src")
    if "'unsafe-inline'" in script_src:
        raise AssertionError("CSP script-src must not allow 'unsafe-inline'.")

    if _is_strict_mode():
        strict_env_csp = str(os.environ.get("CSP_HEADER") or "")
        if strict_env_csp and "'unsafe-inline'" in _csp_directive_values(
            strict_env_csp, "script-src"
        ):
            raise AssertionError(
                "CSP_HEADER must not allow script-src 'unsafe-inline' in strict mode."
            )


def _assert_auth_session_tracking_contract() -> None:
    if not _is_strict_mode():
        return
    tracking_enabled = _checked_bool_env("IMMOAPP_AUTH_SESSION_TRACKING_ENABLED")
    require_sid = _checked_bool_env("IMMOAPP_REQUIRE_SESSION_ID_CLAIM")
    if tracking_enabled and not require_sid:
        raise AssertionError(
            "IMMOAPP_REQUIRE_SESSION_ID_CLAIM=1 is required when "
            "IMMOAPP_AUTH_SESSION_TRACKING_ENABLED=1 in production."
        )


def _assert_mfa_role_enforcement_configured() -> None:
    raw = os.environ.get("IMMOAPP_MFA_ENFORCE_ROLES", "")
    values = [token.strip() for token in raw.split(",") if token.strip()]
    if not values:
        raise AssertionError("IMMOAPP_MFA_ENFORCE_ROLES must be non-empty in production.")


def _warn_insecure_runtime_defaults() -> None:
    compose = COMPOSE_YML.read_text(encoding="utf-8")
    insecure_tokens = {
        "${POSTGRES_ADMIN_PASSWORD:-immoapp_admin_password}": "compose default admin DB password fallback is enabled",
        "${POSTGRES_PASSWORD:-immoapp_app_password}": "compose default app DB password fallback is enabled",
        "${RABBITMQ_PASSWORD:-immoapp_rabbit_password}": "compose default RabbitMQ password fallback is enabled",
        "BAO_VERIFY_SSL_DOCKER:-0": "OpenBao TLS verification defaults to off",
    }
    for token, warning in insecure_tokens.items():
        if token in compose:
            _warn(warning)

    reg_text = Path("server/services/registration_lifecycle.py").read_text(encoding="utf-8")
    if '"return "http://localhost:8000", "fallback_localhost"' in reg_text:
        _warn("IMMOAPP_PUBLIC_BASE_URL fallback_localhost path is enabled")

    if not COMPOSE_PROD_YML.exists():
        _warn("compose.prod.yml is missing; secure production override profile is recommended")


def _assert_strict_prod_runtime_env() -> None:
    if not _is_strict_mode():
        return

    if _checked_bool_env("DJANGO_DEBUG", default=False):
        raise AssertionError("DJANGO_DEBUG must be disabled in strict mode.")
    for name in ("IMMOAPP_E2E_TEST_MODE", "IMMOAPP_E2E_TEST_MODE_DOCKER"):
        if _checked_bool_env(name, default=False):
            raise AssertionError(f"{name} must be disabled in strict mode.")

    public_base_url = (os.environ.get("IMMOAPP_PUBLIC_BASE_URL") or "").strip()
    if not public_base_url:
        raise AssertionError(
            "IMMOAPP_PUBLIC_BASE_URL is required when IMMOAPP_PROD_CONFIG_STRICT=1."
        )
    if not public_base_url.lower().startswith("https://"):
        raise AssertionError("IMMOAPP_PUBLIC_BASE_URL must use https:// in strict mode.")

    allowed_hosts_raw = (os.environ.get("DJANGO_ALLOWED_HOSTS") or "").strip()
    if not allowed_hosts_raw:
        raise AssertionError("DJANGO_ALLOWED_HOSTS is required in strict mode.")
    allowed_hosts = [host.strip() for host in allowed_hosts_raw.split(",") if host.strip()]
    if not allowed_hosts:
        raise AssertionError("DJANGO_ALLOWED_HOSTS must contain at least one host in strict mode.")

    tls_domain = (os.environ.get("IMMOAPP_TLS_DOMAIN") or "").strip()
    if not tls_domain:
        raise AssertionError("IMMOAPP_TLS_DOMAIN is required in strict mode.")
    if tls_domain not in allowed_hosts:
        raise AssertionError("DJANGO_ALLOWED_HOSTS must include IMMOAPP_TLS_DOMAIN in strict mode.")

    if not _checked_bool_env("BAO_VERIFY_SSL_DOCKER"):
        raise AssertionError("BAO_VERIFY_SSL_DOCKER must be enabled in strict mode.")

    bao_cacert = (os.environ.get("BAO_CACERT_DOCKER") or "").strip()
    if not bao_cacert:
        raise AssertionError("BAO_CACERT_DOCKER is required in strict mode.")

    raw_addrs = (
        os.environ.get("BAO_ADDRS_DOCKER")
        or os.environ.get("BAO_ADDRS")
        or os.environ.get("BAO_ADDR_DOCKER")
        or os.environ.get("BAO_ADDR")
        or ""
    ).strip()
    if not raw_addrs:
        raise AssertionError("BAO_ADDR_DOCKER (or BAO_ADDRS_DOCKER) is required in strict mode.")

    addrs = [addr.strip() for addr in raw_addrs.split(",") if addr.strip()]
    if not addrs:
        raise AssertionError("OpenBao address list is empty in strict mode.")
    if any(not addr.lower().startswith("https://") for addr in addrs):
        raise AssertionError(
            "All OpenBao addresses must use https:// when IMMOAPP_PROD_CONFIG_STRICT=1."
        )

    for name in (
        "SECURE_SSL_REDIRECT_DOCKER",
        "SESSION_COOKIE_SECURE_DOCKER",
        "CSRF_COOKIE_SECURE_DOCKER",
    ):
        if not _checked_bool_env(name):
            raise AssertionError(f"{name}=1 is required in strict mode.")

    secret_defaults = {
        "POSTGRES_ADMIN_PASSWORD": "immoapp_admin_password",
        "POSTGRES_PASSWORD": "immoapp_app_password",
        "RABBITMQ_PASSWORD": "immoapp_rabbit_password",
    }
    for name, default_value in secret_defaults.items():
        value = (os.environ.get(name) or "").strip()
        if not value:
            raise AssertionError(f"{name} is required in strict mode.")
        if value == default_value:
            raise AssertionError(f"{name} must not use insecure fallback default in strict mode.")


def main() -> None:
    _set_import_path()
    _set_defaults()
    _assert_no_schema_init_in_ready()
    _assert_openbao_only_policy()
    _assert_celery_eager_off()
    _assert_celery_reliability_defaults()
    _assert_schema_mode_guard()
    _assert_db_prepare_command_exists()
    _assert_notifications_purge_is_scheduled()
    _assert_maintenance_crontab_schedule()
    _assert_worker_beat_healthchecks_enabled()
    _assert_step_up_controls()
    _assert_csp_policy_contract()
    _assert_auth_session_tracking_contract()
    _assert_mfa_role_enforcement_configured()
    _warn_insecure_runtime_defaults()
    _assert_strict_prod_runtime_env()
    print("verify_prod_config: OK")


if __name__ == "__main__":
    main()
