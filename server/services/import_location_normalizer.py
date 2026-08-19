"""Shared thread-safe LocationNormalizer provider for importer services."""

from __future__ import annotations

import threading

from core.importer.normalizers.location_normalizer import LocationNormalizer

_NORMALIZER_LOCK = threading.Lock()
_NORMALIZER_INSTANCE: LocationNormalizer | None = None


def shared_location_normalizer() -> LocationNormalizer:
    global _NORMALIZER_INSTANCE
    instance = _NORMALIZER_INSTANCE
    if instance is not None:
        return instance
    with _NORMALIZER_LOCK:
        instance = _NORMALIZER_INSTANCE
        if instance is None:
            instance = LocationNormalizer()
            _NORMALIZER_INSTANCE = instance
        return instance


def _reset_shared_location_normalizer_for_tests() -> None:
    global _NORMALIZER_INSTANCE
    with _NORMALIZER_LOCK:
        _NORMALIZER_INSTANCE = None


__all__ = ["shared_location_normalizer"]
