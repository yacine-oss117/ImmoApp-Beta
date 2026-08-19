"""
User settings schemas.
"""

from __future__ import annotations

from rest_framework import serializers

from .request_schemas_common import validate_printable_text


class UserSettingsSerializer(serializers.Serializer):
    timezone = serializers.CharField(required=False, allow_blank=True, max_length=64)
    locale = serializers.CharField(required=False, allow_blank=True, max_length=32)

    def validate_timezone(self, value: str) -> str:
        return validate_printable_text(value, "Timezone")

    def validate_locale(self, value: str) -> str:
        return validate_printable_text(value, "Locale")


__all__ = ["UserSettingsSerializer"]
