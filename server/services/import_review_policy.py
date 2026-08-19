"""Policy helpers for smart import review decisions."""

from __future__ import annotations

from dataclasses import dataclass

CREATE_NEW = "create_new"
UPDATE_EXISTING = "update_existing"
REVIEW_AMBIGUOUS = "review_ambiguous"
SKIP = "skip"

DECISION_OPTIONS = [CREATE_NEW, UPDATE_EXISTING, REVIEW_AMBIGUOUS, SKIP]

_ENTITY_FIELDS: dict[str, tuple[list[str], list[str]]] = {
    "client": (
        ["family_name", "phone", "remarks", "tags", "is_vip", "status"],
        ["id", "agency_id", "created_at", "updated_at", "row_version", "deleted_at"],
    ),
    "listing": (
        ["family_name", "phone", "remarks", "is_vip", "status"],
        ["id", "agency_id", "created_at", "updated_at", "row_version", "deleted_at"],
    ),
    "demande": (
        [
            "type",
            "type_id",
            "action",
            "action_id",
            "wilaya",
            "wilaya_id",
            "locations",
            "beds_min",
            "surface_min",
            "surface_max",
            "budget_min",
            "budget_max",
            "furnished",
            "floor_min",
            "floor_max",
            "elevator",
            "accessibility_required",
            "tags",
            "remarks",
        ],
        ["id", "agency_id", "client_id", "created_at", "updated_at", "row_version", "deleted_at"],
    ),
    "offer": (
        [
            "type",
            "type_id",
            "action",
            "action_id",
            "wilaya",
            "wilaya_id",
            "location",
            "beds",
            "surface",
            "budget",
            "furnished",
            "floor",
            "elevator",
            "accessibility_supported",
            "price_negotiable",
            "price_flex_pct",
            "link",
            "latitude",
            "longitude",
            "remarks",
            "status",
        ],
        ["id", "agency_id", "listing_id", "created_at", "updated_at", "row_version", "deleted_at"],
    ),
}


@dataclass(frozen=True)
class ReviewDecisionPolicy:
    entity_type: str
    create_threshold: float
    update_threshold: float
    mutable_fields: list[str]
    immutable_fields: list[str]


_POLICIES: dict[str, ReviewDecisionPolicy] = {
    "client": ReviewDecisionPolicy(
        entity_type="client",
        create_threshold=0.60,
        update_threshold=0.90,
        mutable_fields=list(_ENTITY_FIELDS["client"][0]),
        immutable_fields=list(_ENTITY_FIELDS["client"][1]),
    ),
    "listing": ReviewDecisionPolicy(
        entity_type="listing",
        create_threshold=0.60,
        update_threshold=0.90,
        mutable_fields=list(_ENTITY_FIELDS["listing"][0]),
        immutable_fields=list(_ENTITY_FIELDS["listing"][1]),
    ),
    "demande": ReviewDecisionPolicy(
        entity_type="demande",
        create_threshold=0.65,
        update_threshold=0.93,
        mutable_fields=list(_ENTITY_FIELDS["demande"][0]),
        immutable_fields=list(_ENTITY_FIELDS["demande"][1]),
    ),
    "offer": ReviewDecisionPolicy(
        entity_type="offer",
        create_threshold=0.65,
        update_threshold=0.93,
        mutable_fields=list(_ENTITY_FIELDS["offer"][0]),
        immutable_fields=list(_ENTITY_FIELDS["offer"][1]),
    ),
}


def decision_policy_for_entity(entity_type: str) -> ReviewDecisionPolicy:
    key = str(entity_type or "").strip().lower()
    return _POLICIES.get(
        key,
        ReviewDecisionPolicy(
            entity_type=key or "unknown",
            create_threshold=0.60,
            update_threshold=0.90,
            mutable_fields=[],
            immutable_fields=["id", "agency_id", "row_version"],
        ),
    )


def mutable_fields_for_entity(entity_type: str) -> list[str]:
    return list(decision_policy_for_entity(entity_type).mutable_fields)


def immutable_fields_for_entity(entity_type: str) -> list[str]:
    return list(decision_policy_for_entity(entity_type).immutable_fields)
