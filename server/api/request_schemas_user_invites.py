"""User invitation request schemas."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers


class UserInviteCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=["manager", "agent"], required=True)
    is_owner = serializers.BooleanField(required=False)
    manager_id = serializers.IntegerField(required=False, allow_null=True)
    email = serializers.EmailField(required=True)
    invite_name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    expires_seconds = serializers.IntegerField(required=False, min_value=900, max_value=604800)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if bool(attrs.get("is_owner")):
            raise serializers.ValidationError({"is_owner": ["Invites cannot grant owner access."]})
        role = str(attrs.get("role") or "").strip()
        manager_id = attrs.get("manager_id")
        if role == "agent" and manager_id is None:
            raise serializers.ValidationError(
                {"manager_id": ["manager_id is required for agents."]}
            )
        if role == "manager" and manager_id is not None:
            raise serializers.ValidationError(
                {"manager_id": ["manager_id must be empty for managers."]}
            )
        return attrs


class UserInviteResendSerializer(serializers.Serializer):
    expires_seconds = serializers.IntegerField(required=False, min_value=900, max_value=604800)


__all__ = [
    "UserInviteCreateSerializer",
    "UserInviteResendSerializer",
]
