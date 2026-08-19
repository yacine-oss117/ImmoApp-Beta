from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class MetricsLabelPolicy:
    """
    Cardinality guard:
    - Allow only small, stable label sets.
    - Forbid IDs and unbounded strings that can explode TSDB cardinality.
    """

    allowed_labels: frozenset[str]
    forbidden_labels: frozenset[str]


DEFAULT_POLICY = MetricsLabelPolicy(
    allowed_labels=frozenset(
        {
            "policy_id",
            "route_name",
            "task_type",
            "status_class",
            "error_code",
            "outcome",
            "phase",
            "entity_type",
            "row_outcome",
            "kind",
            "mode",
            "profile",
            "cache_name",
            "queue",
            "reason",
            "event",
            "terminal_reason",
            "wait_state",
            "stalled_reason",
            "mapping_palette_mode",
            "file_model_hint",
            "dominant_side",
            "manual_mapping_required",
            "result_zero_change",
            "cancel_requested",
            "repair_attempted",
            "requeued_after_lease_expiry",
            "projection_conflict_count",
            "row_outlier_review_count",
        }
    ),
    forbidden_labels=frozenset(
        {
            "user_id",
            "actor_id",
            "resource_id",
            "client_id",
            "demande_id",
            "offer_id",
            "listing_id",
            "agency_id",
            "device_id",
            "idempotency_key",
            "token",
            "authorization",
            "path",
            "url",
            "raw_path",
            "query",
        }
    ),
)


class MetricsCardinalityError(ValueError):
    pass


def validate_metric_attributes(
    attributes: Mapping[str, object] | None,
    *,
    policy: MetricsLabelPolicy = DEFAULT_POLICY,
) -> None:
    if not attributes:
        return

    keys = set(attributes.keys())

    forbidden_hit = keys.intersection(policy.forbidden_labels)
    if forbidden_hit:
        raise MetricsCardinalityError(f"Forbidden metric labels used: {sorted(forbidden_hit)}")

    unknown = keys.difference(policy.allowed_labels)
    if unknown:
        raise MetricsCardinalityError(
            f"Unknown metric labels used (not allowlisted): {sorted(unknown)}"
        )


def validate_label_names(
    label_names: Iterable[str],
    *,
    policy: MetricsLabelPolicy = DEFAULT_POLICY,
) -> None:
    keys = set(label_names)
    forbidden_hit = keys.intersection(policy.forbidden_labels)
    if forbidden_hit:
        raise MetricsCardinalityError(f"Forbidden metric labels declared: {sorted(forbidden_hit)}")

    unknown = keys.difference(policy.allowed_labels)
    if unknown:
        raise MetricsCardinalityError(
            f"Unknown metric labels declared (not allowlisted): {sorted(unknown)}"
        )
