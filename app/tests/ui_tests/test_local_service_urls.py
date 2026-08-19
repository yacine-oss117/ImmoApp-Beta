from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.services.local_service_urls import rewrite_local_service_request, rewrite_local_service_url

pytestmark = pytest.mark.ui


def test_rewrite_local_service_url_maps_minio_to_loopback(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    monkeypatch.setenv("IMMOAPP_API_BASE_URL", "https://localhost")

    assert (
        rewrite_local_service_url("http://minio:9000/immoapp/object-key")
        == "http://127.0.0.1:9000/immoapp/object-key"
    )


def test_rewrite_local_service_url_keeps_unknown_hosts(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    monkeypatch.setenv("IMMOAPP_API_BASE_URL", "https://localhost")

    assert (
        rewrite_local_service_url("https://example.com/upload/path")
        == "https://example.com/upload/path"
    )


@pytest.mark.parametrize("host", ["db", "rabbitmq", "openbao", "valkey", "web"])
def test_rewrite_local_service_url_does_not_rewrite_non_photo_stack_services(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
    host: str,
) -> None:
    monkeypatch.setenv("IMMOAPP_API_BASE_URL", "https://localhost")
    original = f"http://{host}:9000/internal"

    assert rewrite_local_service_url(original) == original
    assert rewrite_local_service_request(original) == (original, {})


def test_rewrite_local_service_url_does_not_apply_for_remote_api(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    monkeypatch.setenv("IMMOAPP_API_BASE_URL", "https://api.immoapp.test")

    assert (
        rewrite_local_service_url("http://minio:9000/immoapp/object-key")
        == "http://minio:9000/immoapp/object-key"
    )
    assert rewrite_local_service_request("http://minio:9000/immoapp/object-key") == (
        "http://minio:9000/immoapp/object-key",
        {},
    )


def test_rewrite_local_service_request_preserves_signed_host_for_local_minio(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    monkeypatch.setenv("IMMOAPP_API_BASE_URL", "https://localhost")

    url, headers = rewrite_local_service_request(
        "http://minio:9000/immoapp/object-key?X-Amz-Signature=test"
    )

    assert url == "http://127.0.0.1:9000/immoapp/object-key?X-Amz-Signature=test"
    assert headers == {"Host": "minio:9000"}
