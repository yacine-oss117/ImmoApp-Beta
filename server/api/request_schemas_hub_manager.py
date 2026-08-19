"""Request schemas for Hub Manager owner authorization."""

from __future__ import annotations

from rest_framework import serializers

from core.contracts.hub_manager_authorization import PROTECTED_ACTIONS

_SHA256_RE = r"^[0-9a-f]{64}$"


class HubManagerAuthorizationIssueSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=sorted(PROTECTED_ACTIONS))
    hub_id = serializers.CharField(max_length=128)
    hub_display_name = serializers.CharField(max_length=200, allow_blank=True)
    hub_identity_sha256 = serializers.RegexField(_SHA256_RE)
    hub_state_manifest_sha256 = serializers.RegexField(_SHA256_RE)
    hub_state_install_lineage = serializers.CharField(max_length=256)


class HubManagerAuthorizationConsumeSerializer(serializers.Serializer):
    evidence_nonce = serializers.CharField(min_length=32, max_length=128)
    action = serializers.ChoiceField(choices=sorted(PROTECTED_ACTIONS))
    hub_id = serializers.CharField(max_length=128)


__all__ = [
    "HubManagerAuthorizationConsumeSerializer",
    "HubManagerAuthorizationIssueSerializer",
]
