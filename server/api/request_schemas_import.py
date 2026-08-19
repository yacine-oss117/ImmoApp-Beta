"""
Import request schemas.
"""

from __future__ import annotations

from rest_framework import serializers

from core.importer.security import import_security_limits
from server.services.import_constants import (
    ALLOWED_DUPLICATE_STRATEGIES,
    ALLOWED_ENTITY_TYPES,
)
from server.services.storage_config import get_storage_config


class ImportPreviewSerializer(serializers.Serializer):
    session_id = serializers.CharField(required=True, allow_blank=False)
    entity_type = serializers.ChoiceField(required=False, choices=ALLOWED_ENTITY_TYPES)
    column_mapping = serializers.DictField(required=False)
    skip_rows = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=import_security_limits().skip_rows_max,
    )
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=import_security_limits().preview_limit_max,
    )

    def validate_column_mapping(self, value: dict[object, object]) -> dict[object, object]:
        if len(value) > import_security_limits().max_mapping_fields:
            raise serializers.ValidationError("column_mapping exceeds the allowed field count.")
        return value


class ImportExecuteSerializer(serializers.Serializer):
    session_id = serializers.CharField(required=True, allow_blank=False)
    column_mapping = serializers.DictField(required=True)
    entity_type = serializers.ChoiceField(required=False, choices=ALLOWED_ENTITY_TYPES)
    skip_rows = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=import_security_limits().skip_rows_max,
    )
    duplicate_strategy = serializers.ChoiceField(
        required=False,
        choices=ALLOWED_DUPLICATE_STRATEGIES,
    )
    skip_review_rows = serializers.BooleanField(required=False)
    corrections = serializers.DictField(required=False)

    def validate_column_mapping(self, value: dict[object, object]) -> dict[object, object]:
        if len(value) > import_security_limits().max_mapping_fields:
            raise serializers.ValidationError("column_mapping exceeds the allowed field count.")
        return value

    def validate_corrections(self, value: dict[object, object]) -> dict[object, object]:
        if len(value) > import_security_limits().max_correction_rows:
            raise serializers.ValidationError("corrections exceed the allowed row count.")
        return value


class ImportPresignSerializer(serializers.Serializer):
    filename = serializers.CharField(required=True, allow_blank=False)
    content_type = serializers.CharField(required=False, allow_blank=True)
    size_bytes = serializers.IntegerField(required=True, min_value=1)
    expires_seconds = serializers.IntegerField(required=False, min_value=60, max_value=86400)

    def validate_size_bytes(self, value: int) -> int:
        max_import_bytes = get_storage_config().max_import_bytes
        if value > max_import_bytes:
            raise serializers.ValidationError(
                f"size_bytes exceeds max import size ({max_import_bytes} bytes)"
            )
        return value


class ImportCompleteSerializer(serializers.Serializer):
    storage_id = serializers.UUIDField()
    filename = serializers.CharField(required=True, allow_blank=False)
    entity_type = serializers.ChoiceField(required=False, choices=ALLOWED_ENTITY_TYPES)


class ImportReviewSubmitSerializer(serializers.Serializer):
    corrections = serializers.DictField(required=False, default=dict)
    decisions = serializers.DictField(required=False, default=dict)
    item_decisions = serializers.DictField(required=False, default=dict)
    group_decisions = serializers.DictField(required=False, default=dict)
    bulk_operations = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        max_length=import_security_limits().max_decisions,
    )
    skip_rows = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list,
        max_length=import_security_limits().max_decisions,
    )
    skip_item_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list,
        max_length=import_security_limits().max_decisions,
    )

    def validate_corrections(self, value: dict[object, object]) -> dict[object, object]:
        if len(value) > import_security_limits().max_correction_rows:
            raise serializers.ValidationError("corrections exceed the allowed row count.")
        return value

    def validate_decisions(self, value: dict[object, object]) -> dict[object, object]:
        return self._validate_decision_dict(value, field_name="row")

    def validate_item_decisions(self, value: dict[object, object]) -> dict[object, object]:
        return self._validate_decision_dict(value, field_name="item")

    def validate_group_decisions(self, value: dict[object, object]) -> dict[object, object]:
        return self._validate_decision_dict(value, field_name="group")

    def _validate_decision_dict(
        self, value: dict[object, object], *, field_name: str
    ) -> dict[object, object]:
        if len(value) > import_security_limits().max_decisions:
            raise serializers.ValidationError("decisions exceed the allowed row count.")
        allowed_actions = {
            "create_new",
            "update_existing",
            "review_ambiguous",
            "skip",
            "create",
            "update",
            "review",
        }
        for row_key, entry in value.items():
            if not isinstance(entry, dict):
                raise serializers.ValidationError(
                    f"decision for {field_name} {row_key} must be an object"
                )
            action = str(entry.get("action", "") or "").strip().lower()
            if action and action not in allowed_actions:
                raise serializers.ValidationError(f"unsupported action for {field_name} {row_key}")
            row_version = entry.get("row_version")
            if row_version is not None and int(row_version) < 1:
                raise serializers.ValidationError(
                    f"row_version for {field_name} {row_key} must be >= 1"
                )
        return value

    def validate_bulk_operations(self, value: list[object]) -> list[object]:
        for entry in value:
            if not isinstance(entry, dict):
                raise serializers.ValidationError("bulk_operations entries must be objects.")
            operation = str(entry.get("operation", "") or "").strip().lower()
            if operation != "replace_value_in_import":
                raise serializers.ValidationError("unsupported bulk operation.")
            field_name = str(entry.get("field", "") or "").strip()
            if not field_name:
                raise serializers.ValidationError("bulk operation field is required.")
            target_rows = entry.get("target_rows", [])
            if not isinstance(target_rows, list) or not target_rows:
                raise serializers.ValidationError("bulk operation target_rows are required.")
        return value


__all__ = [
    "ImportPreviewSerializer",
    "ImportExecuteSerializer",
    "ImportPresignSerializer",
    "ImportCompleteSerializer",
    "ImportReviewSubmitSerializer",
]
