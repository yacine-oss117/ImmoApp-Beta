"""
Client + Listing request schemas.
"""

from __future__ import annotations

from rest_framework import serializers

from .request_schemas_common import (
    NAME_PATTERN,
    TAG_PATTERN,
    validate_allowlist,
    validate_phone_format,
    validate_printable_text,
)


class ClientPayloadSerializer(serializers.Serializer):
    family_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=64, required=False, allow_blank=True)
    remarks = serializers.CharField(required=False, allow_blank=True)
    tags = serializers.CharField(required=False, allow_blank=True)
    is_vip = serializers.BooleanField(required=False)
    status = serializers.ChoiceField(
        choices=["active", "archived_rented", "archived_sold"],
        required=False,
        allow_blank=True,
    )
    row_version = serializers.IntegerField(required=False, min_value=1)
    created_at = serializers.CharField(required=False, allow_blank=True)
    updated_at = serializers.CharField(required=False, allow_blank=True)
    created_loc = serializers.CharField(required=False, allow_blank=True)

    def validate_family_name(self, value: str) -> str:
        """Validate family name for security threats."""
        return validate_allowlist(value, NAME_PATTERN, "Family name")

    def validate_phone(self, value: str) -> str:
        """Validate phone number format."""
        if value and not validate_phone_format(value):
            raise serializers.ValidationError("Invalid phone number format")
        return value

    def validate_remarks(self, value: str) -> str:
        """Validate remarks for printable content."""
        return validate_printable_text(value, "Remarks")

    def validate_tags(self, value: str) -> str:
        """Validate tags with allow-list."""
        return validate_allowlist(value, TAG_PATTERN, "Tags")


class ListingPayloadSerializer(serializers.Serializer):
    family_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=64, required=False, allow_blank=True)
    remarks = serializers.CharField(required=False, allow_blank=True)
    is_vip = serializers.BooleanField(required=False)
    status = serializers.ChoiceField(
        choices=["available", "rented", "sold"],
        required=False,
        allow_blank=True,
    )
    row_version = serializers.IntegerField(required=False, min_value=1)
    created_at = serializers.CharField(required=False, allow_blank=True)
    updated_at = serializers.CharField(required=False, allow_blank=True)
    created_loc = serializers.CharField(required=False, allow_blank=True)

    def validate_family_name(self, value: str) -> str:
        """Validate family name for security threats."""
        return validate_allowlist(value, NAME_PATTERN, "Family name")

    def validate_phone(self, value: str) -> str:
        """Validate phone number format."""
        if value and not validate_phone_format(value):
            raise serializers.ValidationError("Invalid phone number format")
        return value

    def validate_remarks(self, value: str) -> str:
        """Validate remarks for printable content."""
        return validate_printable_text(value, "Remarks")


__all__ = ["ClientPayloadSerializer", "ListingPayloadSerializer"]
