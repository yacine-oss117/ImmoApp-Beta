"""Request schemas for registration and onboarding flows."""

from __future__ import annotations

import re

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

_E164_PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")
_CODE_8_RE = re.compile(r"^[A-Z0-9]{8}$")
_CODE_6_RE = re.compile(r"^[A-Z0-9]{6}$")


class RegistrationRequestSerializer(serializers.Serializer):
    agency_name = serializers.CharField(max_length=255)
    legal_name = serializers.CharField(max_length=255)
    registry_number = serializers.CharField(max_length=128)
    agency_address = serializers.CharField(max_length=500)
    agency_city = serializers.CharField(max_length=128)
    agency_postal_code = serializers.CharField(max_length=32)
    owner_first_name = serializers.CharField(max_length=100)
    owner_last_name = serializers.CharField(max_length=100)
    owner_email = serializers.EmailField(max_length=254)
    owner_phone = serializers.CharField(max_length=64)
    terms_accepted = serializers.BooleanField()

    def validate_owner_phone(self, value: str) -> str:
        phone = str(value or "").strip()
        if not _E164_PHONE_RE.fullmatch(phone):
            raise serializers.ValidationError("Phone must be in E.164 format.")
        return phone

    def validate_terms_accepted(self, value: bool) -> bool:
        if value is not True:
            raise serializers.ValidationError("Terms must be accepted.")
        return value


class ActivationSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    activation_code = serializers.CharField(max_length=8, min_length=8)
    password = serializers.CharField(max_length=256, min_length=8)
    password_confirm = serializers.CharField(max_length=256, min_length=8)

    def validate_activation_code(self, value: str) -> str:
        code = str(value or "").strip().upper()
        if not _CODE_8_RE.fullmatch(code):
            raise serializers.ValidationError("Activation code must be 8 uppercase characters.")
        return code

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        password = str(attrs.get("password") or "")
        password_confirm = str(attrs.get("password_confirm") or "")
        if password != password_confirm:
            raise serializers.ValidationError({"password_confirm": ["Passwords do not match."]})
        validate_password(password)
        return attrs


class AcceptInviteSerializer(serializers.Serializer):
    invite_code = serializers.CharField(max_length=6, min_length=6)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=256, min_length=8)
    password_confirm = serializers.CharField(max_length=256, min_length=8)

    def validate_invite_code(self, value: str) -> str:
        code = str(value or "").strip().upper()
        if not _CODE_6_RE.fullmatch(code):
            raise serializers.ValidationError("Invite code must be 6 uppercase characters.")
        return code

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        password = str(attrs.get("password") or "")
        password_confirm = str(attrs.get("password_confirm") or "")
        if password != password_confirm:
            raise serializers.ValidationError({"password_confirm": ["Passwords do not match."]})
        validate_password(password)
        return attrs


__all__ = [
    "AcceptInviteSerializer",
    "ActivationSerializer",
    "RegistrationRequestSerializer",
]
