"""
CRM schemas (contracts, articles, visits).
"""

from __future__ import annotations

from rest_framework import serializers

from .request_schemas_common import (
    SHORT_TEXT_PATTERN,
    validate_allowlist,
    validate_printable_text,
)


class ContractPayloadSerializer(serializers.Serializer):
    client_id = serializers.IntegerField(required=True, min_value=1)
    listing_id = serializers.IntegerField(required=True, min_value=1)
    contract_type = serializers.CharField(required=True, allow_blank=False)
    status = serializers.CharField(required=False, allow_blank=True)
    start_date = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    end_date = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    amount = serializers.FloatField(required=False, min_value=0)
    deposit = serializers.FloatField(required=False, min_value=0)
    terms = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    row_version = serializers.IntegerField(required=False, min_value=1)

    def validate_contract_type(self, value: str) -> str:
        return validate_allowlist(value, SHORT_TEXT_PATTERN, "Contract type")

    def validate_status(self, value: str) -> str:
        return validate_allowlist(value, SHORT_TEXT_PATTERN, "Status")

    def validate_terms(self, value: str) -> str:
        return validate_printable_text(value, "Terms")

    def validate_notes(self, value: str) -> str:
        return validate_printable_text(value, "Notes")


class ContractCancelSerializer(serializers.Serializer):
    restore_status = serializers.BooleanField(required=False)


class ContractArticleSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True)
    content = serializers.CharField(required=True, allow_blank=False)
    article_number = serializers.IntegerField(required=True, min_value=1)
    is_standard = serializers.BooleanField(required=False)
    is_required = serializers.BooleanField(required=False)

    def validate_title(self, value: str) -> str:
        return validate_printable_text(value, "Title")

    def validate_content(self, value: str) -> str:
        return validate_printable_text(value, "Content")


class ContractArticleUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True)
    content = serializers.CharField(required=False, allow_blank=True)
    row_version = serializers.IntegerField(required=False, min_value=1)

    def validate_title(self, value: str) -> str:
        return validate_printable_text(value, "Title")

    def validate_content(self, value: str) -> str:
        return validate_printable_text(value, "Content")


class CopyClausesSerializer(serializers.Serializer):
    context = serializers.DictField()


class VisitPayloadSerializer(serializers.Serializer):
    client_id = serializers.IntegerField(required=True, min_value=1)
    listing_id = serializers.IntegerField(required=True, min_value=1)
    scheduled_date = serializers.CharField(required=True, allow_blank=False)
    scheduled_time = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_status(self, value: str) -> str:
        return validate_allowlist(value, SHORT_TEXT_PATTERN, "Status")

    def validate_notes(self, value: str) -> str:
        return validate_printable_text(value, "Notes")


class VisitUpdateSerializer(serializers.Serializer):
    status = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    row_version = serializers.IntegerField(required=False, min_value=1)

    def validate_status(self, value: str) -> str:
        return validate_allowlist(value, SHORT_TEXT_PATTERN, "Status")

    def validate_notes(self, value: str) -> str:
        return validate_printable_text(value, "Notes")


__all__ = [
    "ContractPayloadSerializer",
    "ContractCancelSerializer",
    "ContractArticleSerializer",
    "ContractArticleUpdateSerializer",
    "CopyClausesSerializer",
    "VisitPayloadSerializer",
    "VisitUpdateSerializer",
]
