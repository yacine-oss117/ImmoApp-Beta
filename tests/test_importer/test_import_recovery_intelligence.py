from __future__ import annotations

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from core.importer.normalize_pipeline import NormalizedRow
from server.services.import_agency_memory import AgencyAliasEntry, AgencyAliasMemory
from server.services.import_mapping_gate import evaluate_manual_mapping_gate
from server.services.import_recovery import apply_row_recovery
from server.services.import_types import ALIAS_DOMAIN_LOCATION


def test_offer_location_context_recovers_wilaya_for_known_commune() -> None:
    normalized = NormalizedRow(
        data={
            "listing_id": 11,
            "action": "sell",
            "type": "apartment",
            "location": "Hydra",
            "budget": 15000000,
            "surface": 95,
            "beds": 3,
            "floor": 2,
        }
    )

    recovered = apply_row_recovery(
        normalized=normalized,
        raw_row={"location": "Hydra"},
        entity_type="offer",
        column_types={"location": "location"},
        memory=None,
    )

    assert recovered.data["wilaya"] == 16
    assert recovered.recoverability_class == "auto_recoverable"
    assert any(str(item.get("field", "")) == "wilaya" for item in recovered.recovered_fields)


def test_demande_locations_spanning_multiple_wilayas_becomes_blocking() -> None:
    normalized = NormalizedRow(
        data={
            "client_id": 7,
            "action": "buy",
            "type": "apartment",
            "budget_min": 10000000,
            "budget_max": 15000000,
            "surface_min": 70,
            "surface_max": 120,
            "beds_min": 2,
        }
    )

    recovered = apply_row_recovery(
        normalized=normalized,
        raw_row={"locations": "Hydra, Oran"},
        entity_type="demande",
        column_types={"locations": "location"},
        memory=None,
    )

    assert recovered.recoverability_class == "blocking"
    assert any("multiple wilayas" in str(reason).lower() for reason in recovered.blocking_reasons)


def test_shadow_agency_alias_is_suggestion_only() -> None:
    memory = AgencyAliasMemory(
        agency_id=1,
        version="1",
        shadow={
            ALIAS_DOMAIN_LOCATION: {
                "ben ak": AgencyAliasEntry(
                    agency_id=1,
                    domain=ALIAS_DOMAIN_LOCATION,
                    source_value_original="Ben Ak",
                    source_value_normalized="ben ak",
                    canonical_key="16022",
                    canonical_label="Ben Aknoun",
                    state="shadow",
                    confirm_count=2,
                    reject_count=0,
                    distinct_job_count=1,
                    metadata={"wilaya_code": 16},
                )
            }
        },
    )
    normalized = NormalizedRow(
        data={
            "listing_id": 11,
            "action": "sell",
            "type": "apartment",
            "location": "Ben Ak",
            "budget": 15000000,
            "surface": 95,
            "beds": 3,
            "floor": 2,
        }
    )

    recovered = apply_row_recovery(
        normalized=normalized,
        raw_row={"location": "Ben Ak"},
        entity_type="offer",
        column_types={"location": "location"},
        memory=memory,
    )

    assert recovered.data["location"] == "Ben Ak"
    assert recovered.recoverability_class == "review_recoverable"
    assert any(
        str(item.get("candidate_label", "")) == "Ben Aknoun"
        for item in recovered.recovery_candidates
    )


def test_mapping_gate_requires_manual_mapping_for_chaotic_shape() -> None:
    required, reasons, metrics = evaluate_manual_mapping_gate(
        detected_columns=[
            {"header": "A", "detected_type": "unknown", "confidence": 0.2},
            {"header": "B", "detected_type": "unknown", "confidence": 0.1},
            {"header": "C", "detected_type": "phone", "confidence": 0.3},
        ],
        final_inference={"confidence": 0.4, "bundle_mode": "single_entity"},
        column_types={"family_name": "unknown", "phone": "phone", "wilaya": "unknown"},
    )

    assert required is True
    assert reasons
    assert float(metrics["inference_confidence"]) < 0.55
