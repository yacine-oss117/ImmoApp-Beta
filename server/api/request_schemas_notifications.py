"""
Notification schemas.
"""

from __future__ import annotations

from rest_framework import serializers


class NotificationsMarkSerializer(serializers.Serializer):
    all = serializers.BooleanField(required=False)
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
    )


__all__ = ["NotificationsMarkSerializer"]
