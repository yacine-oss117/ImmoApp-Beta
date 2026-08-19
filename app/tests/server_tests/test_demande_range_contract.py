from __future__ import annotations

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from core.data.demande_repo_write_create import _prepare_demande_values  # noqa: E402
from server.services.demandes import _enforce_strict_demande_fields  # noqa: E402
from server.services.import_rows import validate_row  # noqa: E402


def test_validate_row_allows_partial_demande_ranges_before_anchor_assignment() -> None:
    validated, errors = validate_row(
        {
            "action": "buy",
            "type": "apartment",
            "wilaya": "16",
            "budget_max": 1500000.0,
            "surface_min": 80.0,
            "beds_min": 3,
        },
        "demande",
    )

    assert errors == []
    assert validated["budget_max"] == 1500000.0
    assert validated["surface_min"] == 80.0
    assert validated["beds_min"] == 3
    assert validated["floor_min"] == 0
    assert validated["floor_max"] == 100


def test_enforce_strict_demande_fields_allows_partial_ranges_after_anchor_assignment() -> None:
    _enforce_strict_demande_fields(
        {
            "client_id": 42,
            "type_id": 1,
            "action_id": 1,
            "wilaya_id": 16,
            "budget_max": 1500000.0,
            "surface_min": 80.0,
        }
    )


def test_prepare_demande_values_materializes_partial_ranges_for_storage() -> None:
    prepared = _prepare_demande_values(
        {
            "client_id": 42,
            "type": "apartment",
            "type_id": 1,
            "action": "buy",
            "action_id": 1,
            "wilaya": "16",
            "wilaya_id": 16,
            "budget_max": 1500000.0,
            "surface_min": 80.0,
        }
    )

    assert prepared["budget_min"] == 0.0
    assert prepared["budget_max"] == 1500000.0
    assert prepared["surface_min"] == 80.0
    assert prepared["surface_max"] == 80.0
    assert prepared["beds_min"] == 0
