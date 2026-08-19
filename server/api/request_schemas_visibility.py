"""
Visibility/ACL schemas.
"""

from __future__ import annotations

from rest_framework import serializers


class RecordVisibilitySerializer(serializers.Serializer):
    visibility = serializers.ChoiceField(choices=["agency", "restricted"], required=True)
    allowed_user_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
    )
    row_version = serializers.IntegerField(required=True, min_value=1)


__all__ = ["RecordVisibilitySerializer"]
