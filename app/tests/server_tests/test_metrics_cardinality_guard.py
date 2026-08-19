import pytest

from core.observability.metrics_guard import MetricsCardinalityError, validate_metric_attributes


def test_forbidden_labels_rejected():
    with pytest.raises(MetricsCardinalityError):
        validate_metric_attributes({"user_id": 123, "outcome": "ok"})


def test_unknown_labels_rejected():
    with pytest.raises(MetricsCardinalityError):
        validate_metric_attributes({"new_label": "oops"})


def test_allowed_labels_ok():
    validate_metric_attributes({"outcome": "ok", "entity_type": "offers"})


def test_mode_label_is_allowlisted():
    validate_metric_attributes({"mode": "direct", "outcome": "ok", "kind": "run"})


def test_match_runtime_profile_labels_are_allowlisted():
    validate_metric_attributes({"profile": "green", "reason": "green_recovered"})
