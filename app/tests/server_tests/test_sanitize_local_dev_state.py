from __future__ import annotations

import os

from scripts import sanitize_local_dev_state as module


def test_force_host_runtime_endpoints_sets_host_safe_defaults(monkeypatch) -> None:
    for name in (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "PGCONNECT_TIMEOUT",
        "BAO_ADDR",
        "VALKEY_URL",
        "CHANNEL_LAYER_URL",
        "STORAGE_ENDPOINT_URL",
        "STORAGE_CLAMD_HOST",
    ):
        monkeypatch.delenv(name, raising=False)

    module._force_host_runtime_endpoints()

    assert os.environ["POSTGRES_HOST"] == "127.0.0.1"
    assert os.environ["POSTGRES_PORT"] == "5432"
    assert os.environ["PGCONNECT_TIMEOUT"] == "5"
    assert os.environ["BAO_ADDR"] == "http://127.0.0.1:8200"
    assert os.environ["VALKEY_URL"] == "redis://127.0.0.1:6379/1"
    assert os.environ["CHANNEL_LAYER_URL"] == "redis://127.0.0.1:6379/3"
    assert os.environ["STORAGE_ENDPOINT_URL"] == "http://127.0.0.1:9000"
    assert os.environ["STORAGE_CLAMD_HOST"] == "127.0.0.1"


def test_force_host_runtime_endpoints_rewrites_docker_service_urls(monkeypatch) -> None:
    monkeypatch.setenv("BAO_ADDR", "http://openbao:8200")
    monkeypatch.setenv("VALKEY_URL", "redis://valkey:6379/9")
    monkeypatch.setenv("CHANNEL_LAYER_URL", "redis://valkey:6379/8")
    monkeypatch.setenv("STORAGE_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setenv("STORAGE_CLAMD_HOST", "clamav")
    monkeypatch.setenv(
        "CELERY_BROKER_URL",
        "amqp://immoapp:immoapp_rabbit_password@rabbitmq:5672//",
    )

    module._force_host_runtime_endpoints()

    assert os.environ["BAO_ADDR"] == "http://127.0.0.1:8200"
    assert os.environ["VALKEY_URL"] == "redis://127.0.0.1:6379/1"
    assert os.environ["CHANNEL_LAYER_URL"] == "redis://127.0.0.1:6379/3"
    assert os.environ["STORAGE_ENDPOINT_URL"] == "http://127.0.0.1:9000"
    assert os.environ["STORAGE_CLAMD_HOST"] == "127.0.0.1"
    assert os.environ["CELERY_BROKER_URL"].endswith("@127.0.0.1:5672//")
