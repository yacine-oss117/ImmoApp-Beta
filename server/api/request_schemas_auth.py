"""Authentication lifecycle request schemas."""

from __future__ import annotations

from rest_framework import serializers


class PasswordForgotSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=255)


class PasswordResetSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=512)
    new_password = serializers.CharField(max_length=256, min_length=8)


class AccountActivationSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=512)
    password = serializers.CharField(max_length=256, min_length=8)


class StepUpAuthSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=256, min_length=1)
    mfa_code = serializers.CharField(max_length=16, required=False, allow_blank=True)


class TotpCodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=16, min_length=6)


class SessionRevokeAllSerializer(serializers.Serializer):
    keep_current = serializers.BooleanField(required=False, default=True)


__all__ = [
    "AccountActivationSerializer",
    "PasswordForgotSerializer",
    "PasswordResetSerializer",
    "SessionRevokeAllSerializer",
    "StepUpAuthSerializer",
    "TotpCodeSerializer",
]
