"""
Response payload serializers for API contract stability.
"""

from __future__ import annotations

from rest_framework import serializers


class ClientResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    family_name = serializers.CharField()
    phone = serializers.CharField()
    remarks = serializers.CharField(allow_null=True)
    tags = serializers.CharField(allow_null=True)
    is_vip = serializers.BooleanField()
    status = serializers.CharField()
    created_at = serializers.CharField()
    updated_at = serializers.CharField()
    created_loc = serializers.CharField(allow_null=True)
    row_version = serializers.IntegerField()
    deleted_at = serializers.CharField(allow_null=True)


class ListingResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    family_name = serializers.CharField()
    phone = serializers.CharField()
    remarks = serializers.CharField(allow_null=True)
    is_vip = serializers.BooleanField()
    status = serializers.CharField()
    created_at = serializers.CharField()
    updated_at = serializers.CharField()
    created_loc = serializers.CharField(allow_null=True)
    row_version = serializers.IntegerField()
    deleted_at = serializers.CharField(allow_null=True)


class DemandeResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    client_id = serializers.IntegerField()
    created_at = serializers.CharField()
    updated_at = serializers.CharField()
    row_version = serializers.IntegerField()
    deleted_at = serializers.CharField(allow_null=True)
    # Match specific domain fields
    type = serializers.CharField(allow_null=True)
    type_id = serializers.IntegerField(allow_null=True)
    action = serializers.CharField(allow_null=True)
    action_id = serializers.IntegerField(allow_null=True)
    wilaya = serializers.CharField(allow_null=True)
    wilaya_id = serializers.IntegerField(allow_null=True)
    locations = serializers.CharField(allow_null=True)
    beds_min = serializers.IntegerField(allow_null=True)
    surface_min = serializers.FloatField(allow_null=True)
    surface_max = serializers.FloatField(allow_null=True)
    budget_min = serializers.FloatField(allow_null=True)
    budget_max = serializers.FloatField(allow_null=True)
    furnished = serializers.CharField(allow_null=True)
    floor_min = serializers.IntegerField(allow_null=True)
    floor_max = serializers.IntegerField(allow_null=True)
    elevator = serializers.BooleanField(allow_null=True)
    accessibility_required = serializers.BooleanField(allow_null=True)
    tags = serializers.CharField(allow_null=True)
    remarks = serializers.CharField(allow_null=True)


class OfferResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    listing_id = serializers.IntegerField()
    created_at = serializers.CharField()
    updated_at = serializers.CharField()
    row_version = serializers.IntegerField()
    deleted_at = serializers.CharField(allow_null=True)
    type = serializers.CharField(allow_null=True)
    type_id = serializers.IntegerField(allow_null=True)
    action = serializers.CharField(allow_null=True)
    action_id = serializers.IntegerField(allow_null=True)
    wilaya = serializers.CharField(allow_null=True)
    wilaya_id = serializers.IntegerField(allow_null=True)
    location = serializers.CharField(allow_null=True)
    latitude = serializers.FloatField(allow_null=True)
    longitude = serializers.FloatField(allow_null=True)
    beds = serializers.IntegerField(allow_null=True)
    surface = serializers.FloatField(allow_null=True)
    budget = serializers.FloatField(allow_null=True)
    status = serializers.CharField(allow_null=True)
    price_negotiable = serializers.BooleanField(allow_null=True)
    price_flex_pct = serializers.FloatField(allow_null=True)
    furnished = serializers.CharField(allow_null=True)
    floor = serializers.IntegerField(allow_null=True)
    elevator = serializers.BooleanField(allow_null=True)
    accessibility_supported = serializers.BooleanField(allow_null=True)
    link = serializers.CharField(allow_null=True)
    remarks = serializers.CharField(allow_null=True)


class OfferPhotoResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    offer_id = serializers.IntegerField()
    storage_id = serializers.UUIDField()
    position = serializers.IntegerField()
    created_at = serializers.CharField()
    updated_at = serializers.CharField(allow_null=True)
    deleted_at = serializers.CharField(allow_null=True)
    delete_origin = serializers.CharField(allow_null=True, required=False)
    delete_parent_scope = serializers.CharField(allow_null=True, required=False)
    delete_parent_id = serializers.IntegerField(allow_null=True, required=False)
    row_version = serializers.IntegerField()


class UserResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.CharField(allow_null=True)
    first_name = serializers.CharField(allow_null=True)
    last_name = serializers.CharField(allow_null=True)
    role = serializers.CharField()
    is_owner = serializers.BooleanField()
    manager_id = serializers.IntegerField(allow_null=True)
    agency_id = serializers.IntegerField(allow_null=True)
    is_active = serializers.BooleanField()
    can_import = serializers.BooleanField()
    can_hard_delete = serializers.BooleanField()
    last_login = serializers.CharField(allow_null=True)
    date_joined = serializers.CharField(allow_null=True)


class VisitResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    client_id = serializers.IntegerField()
    listing_id = serializers.IntegerField()
    scheduled_date = serializers.CharField()
    scheduled_time = serializers.CharField()
    status = serializers.CharField()
    notes = serializers.CharField(allow_null=True)
    created_at = serializers.CharField()
    updated_at = serializers.CharField()
    deleted_at = serializers.CharField(allow_null=True)
    row_version = serializers.IntegerField()
    client_name = serializers.CharField(allow_null=True)
    listing_location = serializers.CharField(allow_null=True)


class ContractResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    client_id = serializers.IntegerField()
    listing_id = serializers.IntegerField()
    contract_type = serializers.CharField()
    status = serializers.CharField()
    start_date = serializers.CharField()
    end_date = serializers.CharField()
    amount = serializers.FloatField()
    deposit = serializers.FloatField()
    terms = serializers.CharField(allow_null=True)
    notes = serializers.CharField(allow_null=True)
    created_at = serializers.CharField()
    updated_at = serializers.CharField()
    deleted_at = serializers.CharField(allow_null=True)
    row_version = serializers.IntegerField()
    client_name = serializers.CharField(allow_null=True)
    listing_location = serializers.CharField(allow_null=True)


class AuditResponseSerializer(serializers.Serializer):
    id = serializers.CharField()
    ts = serializers.CharField()
    actor = serializers.CharField(allow_null=True)
    action = serializers.CharField()
    table_name = serializers.CharField()
    record_id = serializers.CharField(allow_null=True)


class AuthSecurityEventResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    agency_id = serializers.IntegerField(allow_null=True)
    user_id = serializers.IntegerField(allow_null=True)
    event_type = serializers.CharField()
    outcome = serializers.CharField()
    identifier = serializers.CharField(allow_null=True)
    reason_code = serializers.CharField(allow_null=True)
    source_ip = serializers.CharField(allow_null=True)
    user_agent = serializers.CharField(allow_null=True)
    request_id = serializers.CharField(allow_null=True)
    details = serializers.JSONField(allow_null=True)
    created_at = serializers.CharField()


class OfferMatchResponseSerializer(serializers.Serializer):
    listing_id = serializers.IntegerField()
    score = serializers.FloatField()
    offer = OfferResponseSerializer()


class MatchResultResponseSerializer(serializers.Serializer):
    demande_id = serializers.IntegerField()
    demande_summary = serializers.CharField()
    total_count = serializers.IntegerField()
    matches = OfferMatchResponseSerializer(many=True)


class ClientMatchResultResponseSerializer(serializers.Serializer):
    client_id = serializers.IntegerField()
    total_unique_offers = serializers.IntegerField()
    demande_results = MatchResultResponseSerializer(many=True)


class ContractArticleResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    contract_id = serializers.IntegerField()
    article_number = serializers.IntegerField()
    title = serializers.CharField(allow_null=True)
    content = serializers.CharField()
    is_standard = serializers.IntegerField()
    is_required = serializers.IntegerField()
    created_at = serializers.CharField()
    updated_at = serializers.CharField()
    deleted_at = serializers.CharField(allow_null=True)
    row_version = serializers.IntegerField()


class CustomLocationResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    agency_id = serializers.IntegerField()
    created_at = serializers.CharField()
    updated_at = serializers.CharField(allow_null=True)
    deleted_at = serializers.CharField(allow_null=True)
    row_version = serializers.IntegerField()


class TemplateResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    template = serializers.CharField()
    is_default = serializers.IntegerField()
    created_at = serializers.CharField()
    updated_at = serializers.CharField()
    deleted_at = serializers.CharField(allow_null=True)
    row_version = serializers.IntegerField()


class AgencySettingResponseSerializer(serializers.Serializer):
    agency_id = serializers.IntegerField()
    key = serializers.CharField()
    value = serializers.CharField(allow_null=True)
    updated_at = serializers.CharField()
    deleted_at = serializers.CharField(allow_null=True)
    row_version = serializers.IntegerField()
