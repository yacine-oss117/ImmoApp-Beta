"""Request schemas for compliance export/delete endpoints."""

from __future__ import annotations

from rest_framework import serializers


class ComplianceJobRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=512)


__all__ = ["ComplianceJobRequestSerializer"]
