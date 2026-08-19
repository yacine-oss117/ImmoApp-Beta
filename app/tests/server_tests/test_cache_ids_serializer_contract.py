from __future__ import annotations

import os

import pytest

from server.api.request_schemas_cache import CacheIdsSerializer


def _ensure_django() -> None:
    pytest.importorskip("daphne", reason="serializer tests require server deps")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def test_cache_ids_serializer_rejects_oversized_payload() -> None:
    _ensure_django()
    ids = list(range(1, 6002))
    serializer = CacheIdsSerializer(data={"ids": ids})
    assert serializer.is_valid() is False
    assert "ids" in serializer.errors
