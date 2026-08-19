"""
User management request schemas.
"""

from __future__ import annotations

from rest_framework import serializers


class UserCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=256)
    role = serializers.ChoiceField(choices=["super_admin", "manager", "agent"], required=False)
    is_owner = serializers.BooleanField(required=False)
    manager_id = serializers.IntegerField(required=False, allow_null=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    can_import = serializers.BooleanField(required=False)
    can_hard_delete = serializers.BooleanField(required=False)
    agency_id = serializers.IntegerField(required=False, allow_null=True)


class UserUpdateSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=256, required=False)
    role = serializers.ChoiceField(choices=["super_admin", "manager", "agent"], required=False)
    is_owner = serializers.BooleanField(required=False)
    manager_id = serializers.IntegerField(required=False, allow_null=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    can_import = serializers.BooleanField(required=False)
    can_hard_delete = serializers.BooleanField(required=False)
    agency_id = serializers.IntegerField(required=False, allow_null=True)


__all__ = ["UserCreateSerializer", "UserUpdateSerializer"]
