"""
Custom location schemas.
"""

from __future__ import annotations

from rest_framework import serializers

from .request_schemas_common import LOCATION_PATTERN, validate_allowlist


class LocationCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=True, allow_blank=False)

    def validate_name(self, value: str) -> str:
        return validate_allowlist(value, LOCATION_PATTERN, "Location")


class LocationRenameSerializer(serializers.Serializer):
    old_name = serializers.CharField(max_length=255, required=True, allow_blank=False)
    new_name = serializers.CharField(max_length=255, required=True, allow_blank=False)

    def validate_old_name(self, value: str) -> str:
        return validate_allowlist(value, LOCATION_PATTERN, "Location")

    def validate_new_name(self, value: str) -> str:
        return validate_allowlist(value, LOCATION_PATTERN, "Location")


class LocationDeleteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=True, allow_blank=False)

    def validate_name(self, value: str) -> str:
        return validate_allowlist(value, LOCATION_PATTERN, "Location")


__all__ = [
    "LocationCreateSerializer",
    "LocationRenameSerializer",
    "LocationDeleteSerializer",
]
