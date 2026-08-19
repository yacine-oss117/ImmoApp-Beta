"""
Shared pytest fixtures for application tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from core.paths import get_app_data_dir

_PYCACHE_PREFIX = str(get_app_data_dir() / "cache" / "pycache")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
os.environ.setdefault("PYTHONPYCACHEPREFIX", _PYCACHE_PREFIX)
# Test harness defaults for fail-secure ALE requirements.
os.environ.setdefault("ALE_KEY_VERSION", "v1")
os.environ.setdefault("ALE_MASTER_KEY", "test-master-key-32-bytes-minimum")
os.environ.setdefault("ALE_SEARCH_SECRET", "test-search-secret")
os.environ.setdefault("ALE_KDF_SALT", "test-kdf-salt-16+")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-django-secret-key-unsafe-for-prod")
os.environ.setdefault("DJANGO_DEBUG", "1")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
os.environ.setdefault("IMMOAPP_SKIP_CELERY_APP", "1")
os.environ.setdefault("IMMOAPP_REQUIRE_ALE_KEY", "1")
os.environ.setdefault("IMMOAPP_ENV", "test")
os.environ.setdefault("IMMOAPP_SCHEMA_MODE", "alembic")
os.environ.setdefault("IMMOAPP_SECRETS_BACKEND", "env")
os.environ.setdefault("IMMOAPP_ALLOW_ENV_SECRETS", "1")
os.environ.setdefault("IMMOAPP_SECRETS_REQUIRED", "0")
os.environ.setdefault("POSTGRES_HOST", "127.0.0.1")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "immoapp")
os.environ.setdefault("POSTGRES_USER", "immoapp_app")
os.environ.setdefault("POSTGRES_PASSWORD", "immoapp_app_password")
os.environ.setdefault("POSTGRES_ADMIN_USER", "immoapp")
os.environ.setdefault("POSTGRES_ADMIN_PASSWORD", "immoapp_admin_password")
os.environ.setdefault("VALKEY_URL", "redis://127.0.0.1:6379/1")
os.environ.setdefault("CHANNEL_LAYER_URL", "redis://127.0.0.1:6379/2")
os.environ.setdefault(
    "CELERY_BROKER_URL", "amqp://immoapp:immoapp_rabbit_password@127.0.0.1:5672//"
)
os.environ.setdefault("STORAGE_ENDPOINT_URL", "http://127.0.0.1:9000")
os.environ.setdefault("STORAGE_ACCESS_KEY", "immoapp")
os.environ.setdefault("STORAGE_SECRET_KEY", "immoapp123")
os.environ.setdefault("STORAGE_BUCKET", "immoapp")
os.environ.setdefault("STORAGE_REGION", "us-east-1")
os.environ.setdefault("STORAGE_USE_SSL", "0")
sys.dont_write_bytecode = True
if hasattr(sys, "pycache_prefix"):
    sys.pycache_prefix = _PYCACHE_PREFIX

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def sandbox_appdata(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Redirect all AppData paths to a temporary sandbox for every test."""
    test_root = tmp_path_factory.mktemp("immoapp_test_root")
    os.environ["IMMOAPP_APPDATA_ROOT"] = str(test_root)
    pycache_dir = Path(test_root) / "cache" / "pycache"
    os.environ["PYTHONPYCACHEPREFIX"] = str(pycache_dir)
    if hasattr(sys, "pycache_prefix"):
        sys.pycache_prefix = str(pycache_dir)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-label expensive suites so CI lanes can select tests by marker."""
    for item in items:
        nodeid = item.nodeid.lower()
        if "integration" in nodeid:
            item.add_marker(pytest.mark.integration)
        if "e2e" in nodeid:
            item.add_marker(pytest.mark.e2e)
        if any(token in nodeid for token in ("large", "benchmark", "messy")):
            item.add_marker(pytest.mark.slow)
