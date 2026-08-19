"""
Demande + Offer request schemas.
"""

from __future__ import annotations

from rest_framework import serializers

from .request_schemas_common import (
    LOCATION_PATTERN,
    SHORT_TEXT_PATTERN,
    TAG_PATTERN,
    validate_allowlist,
    validate_printable_text,
    validate_url_format,
)


class DemandePayloadSerializer(serializers.Serializer):
    type = serializers.CharField(required=False, allow_blank=True)
    type_id = serializers.IntegerField(required=True, min_value=1)
    action = serializers.CharField(required=False, allow_blank=True)
    action_id = serializers.IntegerField(required=True, min_value=1)
    wilaya = serializers.CharField(required=False, allow_blank=True)
    wilaya_id = serializers.IntegerField(required=True, min_value=1)
    locations = serializers.CharField(required=False, allow_blank=True)
    beds_min = serializers.IntegerField(required=False, min_value=0)
    surface_min = serializers.FloatField(required=False, min_value=0.0)
    surface_max = serializers.FloatField(required=False, min_value=0.0)
    budget_min = serializers.FloatField(required=False, min_value=0.0)
    budget_max = serializers.FloatField(required=False, min_value=0.0)
    furnished = serializers.CharField(required=False, allow_blank=True)
    floor_min = serializers.IntegerField(required=False, min_value=0)
    floor_max = serializers.IntegerField(required=False, min_value=0)
    elevator = serializers.BooleanField(required=False)
    accessibility_required = serializers.BooleanField(required=False)
    tags = serializers.CharField(required=False, allow_blank=True)
    remarks = serializers.CharField(required=False, allow_blank=True)
    row_version = serializers.IntegerField(required=False, min_value=1)

    def validate_type(self, value: str) -> str:
        """Validate type for security threats."""
        return validate_allowlist(value, SHORT_TEXT_PATTERN, "Type")

    def validate_action(self, value: str) -> str:
        """Validate action for security threats."""
        return validate_allowlist(value, SHORT_TEXT_PATTERN, "Action")

    def validate_wilaya(self, value: str) -> str:
        """Validate wilaya for security threats."""
        return validate_allowlist(value, LOCATION_PATTERN, "Wilaya")

    def validate_locations(self, value: str) -> str:
        """Validate locations with allow-list."""
        return validate_allowlist(value, LOCATION_PATTERN, "Locations")

    def validate_tags(self, value: str) -> str:
        """Validate tags with allow-list."""
        return validate_allowlist(value, TAG_PATTERN, "Tags")

    def validate_remarks(self, value: str) -> str:
        """Validate remarks for printable content."""
        return validate_printable_text(value, "Remarks")

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        bmin = attrs.get("budget_min")
        bmax = attrs.get("budget_max")
        smin = attrs.get("surface_min")
        smax = attrs.get("surface_max")
        if isinstance(bmin, int | float) and isinstance(bmax, int | float) and bmin > bmax:
            raise serializers.ValidationError({"budget_max": "budget_max must be >= budget_min"})
        if isinstance(smin, int | float) and isinstance(smax, int | float) and smin > smax:
            raise serializers.ValidationError({"surface_max": "surface_max must be >= surface_min"})
        return attrs


class OfferPayloadSerializer(serializers.Serializer):
    type = serializers.CharField(required=False, allow_blank=True)
    type_id = serializers.IntegerField(required=True, min_value=1)
    action = serializers.CharField(required=False, allow_blank=True)
    action_id = serializers.IntegerField(required=True, min_value=1)
    wilaya = serializers.CharField(required=False, allow_blank=True)
    wilaya_id = serializers.IntegerField(required=True, min_value=1)
    location = serializers.CharField(required=True, allow_blank=False)
    beds = serializers.IntegerField(required=True, min_value=0)
    surface = serializers.FloatField(required=True, min_value=0.0)
    budget = serializers.FloatField(required=True, min_value=0.0)
    price_negotiable = serializers.BooleanField(required=False, default=False)
    price_flex_pct = serializers.FloatField(required=False, min_value=0.0, max_value=100.0)
    furnished = serializers.CharField(required=False, allow_blank=True)
    floor = serializers.IntegerField(required=True, min_value=0)
    elevator = serializers.BooleanField(required=False, default=False)
    accessibility_supported = serializers.BooleanField(required=False, default=False)
    link = serializers.CharField(required=False, allow_blank=True)
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    remarks = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField(required=False, allow_blank=True)
    row_version = serializers.IntegerField(required=False, min_value=1)

    def validate_type(self, value: str) -> str:
        """Validate type for security threats."""
        return validate_allowlist(value, SHORT_TEXT_PATTERN, "Type")

    def validate_action(self, value: str) -> str:
        """Validate action for security threats."""
        return validate_allowlist(value, SHORT_TEXT_PATTERN, "Action")

    def validate_wilaya(self, value: str) -> str:
        """Validate wilaya for security threats."""
        return validate_allowlist(value, LOCATION_PATTERN, "Wilaya")

    def validate_location(self, value: str) -> str:
        """Validate location with allow-list."""
        return validate_allowlist(value, LOCATION_PATTERN, "Location")

    def validate_link(self, value: str) -> str:
        """Validate link URL format."""
        if value and not validate_url_format(value):
            raise serializers.ValidationError("Invalid URL format")
        return value

    def validate_remarks(self, value: str) -> str:
        """Validate remarks for printable content."""
        return validate_printable_text(value, "Remarks")

    def validate_status(self, value: str) -> str:
        """Validate offer status for security threats."""
        return validate_allowlist(value, SHORT_TEXT_PATTERN, "Status")

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        return attrs


__all__ = ["DemandePayloadSerializer", "OfferPayloadSerializer"]
