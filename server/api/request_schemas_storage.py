"""
Storage request schemas.
"""

from __future__ import annotations

from rest_framework import serializers


class StoragePresignSerializer(serializers.Serializer):
    storage_id = serializers.UUIDField()
    expires_seconds = serializers.IntegerField(required=False, min_value=60, max_value=86400)
    filename = serializers.CharField(required=False, allow_blank=True)


class StoragePresignUploadSerializer(serializers.Serializer):
    purpose = serializers.CharField(required=True, allow_blank=False)
    filename = serializers.CharField(required=True, allow_blank=False)
    content_type = serializers.CharField(required=False, allow_blank=True)
    size_bytes = serializers.IntegerField(required=True, min_value=1)
    expires_seconds = serializers.IntegerField(required=False, min_value=60, max_value=86400)


class StorageCompleteUploadSerializer(serializers.Serializer):
    storage_id = serializers.UUIDField()


class StorageDeleteSerializer(serializers.Serializer):
    storage_id = serializers.UUIDField()


class OfferPhotoCreateSerializer(serializers.Serializer):
    storage_id = serializers.UUIDField()
    position = serializers.IntegerField(required=False, min_value=0)


__all__ = [
    "StoragePresignSerializer",
    "StoragePresignUploadSerializer",
    "StorageCompleteUploadSerializer",
    "StorageDeleteSerializer",
    "OfferPhotoCreateSerializer",
]
