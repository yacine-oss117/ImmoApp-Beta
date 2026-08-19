"""
Cache + simulation schemas.
"""

from __future__ import annotations

import os

from rest_framework import serializers

from .request_schemas_common import LOCATION_PATTERN, validate_allowlist

_CACHE_IDS_MAX = max(1, int(os.environ.get("IMMOAPP_CACHE_IDS_MAX", "5000")))


class CacheIdsSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=_CACHE_IDS_MAX,
    )


class CacheStoreCountSerializer(serializers.Serializer):
    client_id = serializers.IntegerField(min_value=1)
    count = serializers.IntegerField(min_value=0)


class CacheStoreCountsSerializer(serializers.Serializer):
    counts = serializers.DictField(child=serializers.IntegerField(min_value=0))


class CacheClientSerializer(serializers.Serializer):
    client_id = serializers.IntegerField(min_value=1)


class MatchAllTargetAgencySerializer(serializers.Serializer):
    agency_id = serializers.IntegerField(min_value=1)


class CacheWilayaSerializer(serializers.Serializer):
    wilaya_id = serializers.IntegerField(required=False, min_value=1)
    wilaya = serializers.CharField(required=False, allow_blank=True, max_length=128)

    def validate_wilaya(self, value: str) -> str:
        return validate_allowlist(value, LOCATION_PATTERN, "Wilaya")

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if not attrs.get("wilaya_id") and not attrs.get("wilaya"):
            raise serializers.ValidationError("wilaya_id or wilaya is required")
        return attrs


class SimulationStartSerializer(serializers.Serializer):
    mode = serializers.CharField(required=False, allow_blank=True, max_length=16)
    seed_fake = serializers.BooleanField(required=False)
    client_count = serializers.IntegerField(required=False, min_value=0)
    listing_count = serializers.IntegerField(required=False, min_value=0)
    demandes_per_client = serializers.IntegerField(required=False, min_value=0)
    offers_per_listing = serializers.IntegerField(required=False, min_value=0)


__all__ = [
    "CacheIdsSerializer",
    "CacheStoreCountSerializer",
    "CacheStoreCountsSerializer",
    "CacheClientSerializer",
    "MatchAllTargetAgencySerializer",
    "CacheWilayaSerializer",
    "SimulationStartSerializer",
]
