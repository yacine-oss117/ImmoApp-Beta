"""
Template + agency settings schemas.
"""

from __future__ import annotations

from rest_framework import serializers

from .request_schemas_common import (
    NAME_PATTERN,
    SHORT_TEXT_PATTERN,
    validate_allowlist,
    validate_printable_text,
    validate_template_text,
)


class TemplatePayloadSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=True, allow_blank=False)
    template = serializers.CharField(required=True, allow_blank=False)

    def validate_name(self, value: str) -> str:
        return validate_allowlist(value, NAME_PATTERN, "Template name")

    def validate_template(self, value: str) -> str:
        return validate_template_text(value, "Template content")


class AgencySettingSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=128, required=True, allow_blank=False)
    value = serializers.CharField(required=False, allow_blank=True)

    def validate_key(self, value: str) -> str:
        return validate_allowlist(value, NAME_PATTERN, "Key")

    def validate_value(self, value: str) -> str:
        return validate_printable_text(value, "Value")


class AgencySerialSerializer(serializers.Serializer):
    prefix = serializers.CharField(max_length=16, required=False, allow_blank=True)

    def validate_prefix(self, value: str) -> str:
        return validate_allowlist(value, SHORT_TEXT_PATTERN, "Prefix")


__all__ = [
    "TemplatePayloadSerializer",
    "AgencySettingSerializer",
    "AgencySerialSerializer",
]
