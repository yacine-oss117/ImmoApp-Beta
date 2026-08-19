"""Request serializers for diagnostics key enrollment APIs."""

from __future__ import annotations

from rest_framework import serializers


class DiagnosticsEnrollmentTokenSerializer(serializers.Serializer):
    device_id = serializers.CharField(required=False, max_length=128, allow_blank=False)
    expires_seconds = serializers.IntegerField(required=False, min_value=60, max_value=86400)


class DiagnosticsKeyRegisterSerializer(serializers.Serializer):
    device_id = serializers.CharField(required=True, max_length=128, allow_blank=False)
    signature_key_id = serializers.CharField(required=True, max_length=128, allow_blank=False)
    public_key = serializers.CharField(required=True, allow_blank=False)
    enrollment_token = serializers.CharField(required=False, allow_blank=False)
    admin_approved = serializers.BooleanField(required=False, default=False)


class DiagnosticsKeyRotateSerializer(serializers.Serializer):
    device_id = serializers.CharField(required=True, max_length=128, allow_blank=False)
    signature_key_id = serializers.CharField(required=True, max_length=128, allow_blank=False)
    public_key = serializers.CharField(required=True, allow_blank=False)


class DiagnosticsKeyRevokeSerializer(serializers.Serializer):
    device_id = serializers.CharField(required=True, max_length=128, allow_blank=False)
    signature_key_id = serializers.CharField(required=False, max_length=128, allow_blank=False)


class DiagnosticsVerifySerializer(serializers.Serializer):
    device_id = serializers.CharField(required=True, max_length=128, allow_blank=False)
    signature_key_id = serializers.CharField(required=True, max_length=128, allow_blank=False)
    payload = serializers.JSONField(required=True)
    signature = serializers.CharField(required=True, allow_blank=False)
    payload_version = serializers.CharField(required=False, max_length=32, allow_blank=False)
    algorithm = serializers.CharField(required=False, max_length=64, allow_blank=False)


__all__ = [
    "DiagnosticsEnrollmentTokenSerializer",
    "DiagnosticsKeyRegisterSerializer",
    "DiagnosticsKeyRevokeSerializer",
    "DiagnosticsKeyRotateSerializer",
    "DiagnosticsVerifySerializer",
]
