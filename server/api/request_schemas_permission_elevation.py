"""Request schemas for temporary privilege elevation workflow."""

from __future__ import annotations

from rest_framework import serializers


class PrivilegeRequestCreateSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1)
    permission = serializers.ChoiceField(choices=["can_import", "can_hard_delete"])
    reason = serializers.CharField(required=False, allow_blank=True, max_length=512)


class PrivilegeDecisionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=256)
    duration_minutes = serializers.IntegerField(required=False, min_value=5, max_value=10080)


class PrivilegeListQuerySerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=False, min_value=1)
    status = serializers.ChoiceField(
        required=False,
        choices=["pending", "approved", "denied", "revoked", "expired"],
    )


__all__ = [
    "PrivilegeDecisionSerializer",
    "PrivilegeListQuerySerializer",
    "PrivilegeRequestCreateSerializer",
]
