"""
Base Django settings for immoapp_server.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from core.env_files import resolve_env_file
from core.paths import get_app_data_dir

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
ENV_PATH = resolve_env_file(REPO_ROOT, BASE_DIR)
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    # No local env file present; rely on process environment.
    load_dotenv(override=False)
APPDATA_ROOT = get_app_data_dir()

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY is required")


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT = _env_flag("IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT", True)

_allowed_hosts_raw = os.environ.get("DJANGO_ALLOWED_HOSTS")
if _allowed_hosts_raw:
    ALLOWED_HOSTS = [host.strip() for host in _allowed_hosts_raw.split(",") if host.strip()]
elif DEBUG:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
else:
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must be set when DEBUG=False")

DJANGO_ADMIN_PATH = os.environ.get("DJANGO_ADMIN_PATH", "admin/")
DJANGO_ADMIN_PATH = DJANGO_ADMIN_PATH.strip().lstrip("/")
if not DJANGO_ADMIN_PATH:
    DJANGO_ADMIN_PATH = "admin"
if not DJANGO_ADMIN_PATH.endswith("/"):
    DJANGO_ADMIN_PATH = f"{DJANGO_ADMIN_PATH}/"

_admin_ips_raw = os.environ.get("DJANGO_ADMIN_ALLOWED_IPS", "")
ADMIN_ALLOWED_IPS = [ip.strip() for ip in _admin_ips_raw.split(",") if ip.strip()]

INSTALLED_APPS = [
    "daphne",
    "server.api",
    "server.accounts",
    "server.imports",
    "corsheaders",
    "channels",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "server.immoapp_server.middleware.CorrelationIdMiddleware",
    "server.immoapp_server.middleware.AdminAccessMiddleware",
    "server.api.middleware_security.PermissionEnforcementMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "server.immoapp_server.middleware.SchemaRoutingMiddleware",
    "server.immoapp_server.middleware.SecurityContextMiddleware",
    "server.immoapp_server.middleware.RateLimitHeadersMiddleware",
    "server.immoapp_server.middleware.DeprecationHeadersMiddleware",
    "server.immoapp_server.middleware.CspHeaderMiddleware",
    "server.immoapp_server.security_middleware.SecurityHeadersMiddleware",
    "server.immoapp_server.security_middleware.RequestLoggingMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "server.immoapp_server.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "server.immoapp_server.wsgi.application"
ASGI_APPLICATION = "server.immoapp_server.asgi.application"

LANGUAGE_CODE = os.environ.get("DJANGO_LANGUAGE_CODE", "en-us")
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Africa/Algiers")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = APPDATA_ROOT / "static"
MEDIA_URL = "/media/"
MEDIA_ROOT = APPDATA_ROOT / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

_storage_import_mb = os.environ.get("STORAGE_MAX_IMPORT_MB")
_storage_default_mb = os.environ.get("STORAGE_MAX_FILE_MB", "25")
_proxy_upload_default_mb = _storage_import_mb or _storage_default_mb
_proxy_upload_default_bytes = int(_proxy_upload_default_mb) * 1024 * 1024
IMMOAPP_PROXY_UPLOAD_MAX_BYTES = int(
    os.environ.get("IMMOAPP_PROXY_UPLOAD_MAX_BYTES", str(_proxy_upload_default_bytes))
)
IMMOAPP_FILE_UPLOAD_MEMORY_THRESHOLD = int(
    os.environ.get("IMMOAPP_FILE_UPLOAD_MEMORY_THRESHOLD", str(2 * 1024 * 1024))
)
# Keep request-body cap aligned to import upload limits for proxy uploads.
DATA_UPLOAD_MAX_MEMORY_SIZE = IMMOAPP_PROXY_UPLOAD_MAX_BYTES
FILE_UPLOAD_MAX_MEMORY_SIZE = IMMOAPP_FILE_UPLOAD_MEMORY_THRESHOLD

__all__ = [
    "ADMIN_ALLOWED_IPS",
    "ALLOWED_HOSTS",
    "APPDATA_ROOT",
    "ASGI_APPLICATION",
    "AUTH_USER_MODEL",
    "BASE_DIR",
    "DEBUG",
    "DEFAULT_AUTO_FIELD",
    "DJANGO_ADMIN_PATH",
    "DATA_UPLOAD_MAX_MEMORY_SIZE",
    "ENV_PATH",
    "FILE_UPLOAD_MAX_MEMORY_SIZE",
    "IMMOAPP_FILE_UPLOAD_MEMORY_THRESHOLD",
    "IMMOAPP_PROXY_UPLOAD_MAX_BYTES",
    "IMMOAPP_REQUIRE_STRICT_SINGLE_FLIGHT",
    "INSTALLED_APPS",
    "LANGUAGE_CODE",
    "MEDIA_ROOT",
    "MEDIA_URL",
    "MIDDLEWARE",
    "REPO_ROOT",
    "ROOT_URLCONF",
    "SECRET_KEY",
    "STATIC_ROOT",
    "STATIC_URL",
    "TIME_ZONE",
    "TEMPLATES",
    "USE_I18N",
    "USE_TZ",
    "WSGI_APPLICATION",
]
