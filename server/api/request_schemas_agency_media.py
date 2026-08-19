"""
Agency media upload schemas.
"""

from __future__ import annotations

from rest_framework import serializers

from .request_schemas_common import validate_printable_text


class AgencyMediaSerializer(serializers.Serializer):
    kind = serializers.CharField(max_length=64, required=True, allow_blank=False)
    filename = serializers.CharField(max_length=255, required=True, allow_blank=False)
    content_b64 = serializers.CharField(required=True, allow_blank=False)

    def validate_kind(self, value: str) -> str:
        return validate_printable_text(value, "Kind")

    def validate_filename(self, value: str) -> str:
        return validate_printable_text(value, "Filename")


class AgencyMediaPresignSerializer(serializers.Serializer):
    kind = serializers.CharField(max_length=64, required=True, allow_blank=False)
    filename = serializers.CharField(max_length=255, required=True, allow_blank=False)
    content_type = serializers.CharField(required=False, allow_blank=True)
    size_bytes = serializers.IntegerField(required=True, min_value=1)
    expires_seconds = serializers.IntegerField(required=False, min_value=60, max_value=86400)

    def validate_kind(self, value: str) -> str:
        return validate_printable_text(value, "Kind")

    def validate_filename(self, value: str) -> str:
        return validate_printable_text(value, "Filename")


class AgencyMediaCompleteSerializer(serializers.Serializer):
    kind = serializers.CharField(max_length=64, required=True, allow_blank=False)
    storage_id = serializers.UUIDField()

    def validate_kind(self, value: str) -> str:
        return validate_printable_text(value, "Kind")


__all__ = [
    "AgencyMediaSerializer",
    "AgencyMediaPresignSerializer",
    "AgencyMediaCompleteSerializer",
]
