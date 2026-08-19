from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from server.services import storage_client


def _config(
    *,
    endpoint_url: str = "http://minio:9000",
    access_key: str = "ak",
    secret_key: str = "sk",
    region: str = "us-east-1",
    use_ssl: bool = False,
    bucket: str = "immoapp",
) -> SimpleNamespace:
    return SimpleNamespace(
        endpoint_url=endpoint_url,
        access_key=access_key,
        secret_key=secret_key,
        region=region,
        use_ssl=use_ssl,
        bucket=bucket,
    )


@pytest.fixture(autouse=True)
def _reset_storage_singleton() -> None:
    storage_client._CLIENT = None
    storage_client._CLIENT_CONFIG_FINGERPRINT = None
    storage_client._BUCKET_READY_KEY = None
    storage_client._BUCKET_READY_UNTIL_MONOTONIC = 0.0


def test_get_storage_client_is_thread_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage_client, "get_storage_config", lambda: _config())
    created: list[object] = []

    def _fake_client(*_args: object, **_kwargs: object) -> object:
        # Widen the race window to prove lock behavior.
        time.sleep(0.01)
        client = object()
        created.append(client)
        return client

    monkeypatch.setattr(storage_client.boto3, "client", _fake_client)

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _n: storage_client.get_storage_client(), range(40)))

    assert len(created) == 1
    assert all(result is created[0] for result in results)


def test_get_storage_client_rebuilds_on_config_change(monkeypatch: pytest.MonkeyPatch) -> None:
    config_slot = {"value": _config()}
    monkeypatch.setattr(storage_client, "get_storage_config", lambda: config_slot["value"])
    created: list[object] = []

    def _fake_client(*_args: object, **_kwargs: object) -> object:
        client = object()
        created.append(client)
        return client

    monkeypatch.setattr(storage_client.boto3, "client", _fake_client)

    first = storage_client.get_storage_client()
    config_slot["value"] = _config(access_key="new-ak")
    second = storage_client.get_storage_client()

    assert len(created) == 2
    assert first is not second


def _head_bucket_error(code: str, status: int) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "boom"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        "HeadBucket",
    )


class _BucketClient:
    def __init__(self, *, head_error: ClientError | None = None) -> None:
        self._head_error = head_error
        self.created = 0

    def head_bucket(self, **_kwargs: object) -> None:
        if self._head_error is not None:
            raise self._head_error

    def create_bucket(self, **_kwargs: object) -> None:
        self.created += 1


def test_ensure_bucket_creates_only_for_missing_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _BucketClient(head_error=_head_bucket_error("NoSuchBucket", 404))
    monkeypatch.setattr(storage_client, "get_storage_client", lambda: client)
    monkeypatch.setattr(storage_client, "get_storage_config", lambda: _config(bucket="immoapp"))

    storage_client.ensure_bucket()

    assert client.created == 1


def test_ensure_bucket_raises_on_access_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    err = _head_bucket_error("AccessDenied", 403)
    client = _BucketClient(head_error=err)
    monkeypatch.setattr(storage_client, "get_storage_client", lambda: client)
    monkeypatch.setattr(storage_client, "get_storage_config", lambda: _config(bucket="immoapp"))

    with pytest.raises(ClientError):
        storage_client.ensure_bucket()

    assert client.created == 0


def test_ensure_bucket_raises_retryable_storage_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    err = _head_bucket_error("ServiceUnavailable", 503)
    client = _BucketClient(head_error=err)
    monkeypatch.setattr(storage_client, "get_storage_client", lambda: client)
    monkeypatch.setattr(storage_client, "get_storage_config", lambda: _config(bucket="immoapp"))

    with pytest.raises(storage_client.StorageNotReadyError):
        storage_client.ensure_bucket()

    assert client.created == 0
