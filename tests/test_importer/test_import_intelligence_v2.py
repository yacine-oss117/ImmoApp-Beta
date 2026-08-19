# ruff: noqa: E402

from __future__ import annotations

import uuid
from pathlib import Path

from openpyxl import Workbook

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    create_agency,
    create_manager_user,
    ensure_django,
)

ensure_django()

from server.imports.models import ImportJob
from server.pg.schema import ensure_schema
from server.services.import_column_semantics import profile_columns
from server.services.import_dead_letter import build_dead_letter_row, record_dead_letter_rows
from server.services.import_mapping_gate import evaluate_manual_mapping_gate
from server.services.import_price_dialect import build_price_dialect_profiles
from server.services.import_review_rescue import (
    allowed_reclassify_options,
    build_bulk_fix_groups,
    build_quick_fix_actions,
    expand_bulk_operations,
)
from server.services.import_sheet_intelligence import choose_dominant_sheet, profile_import_sheets


def test_profile_columns_detects_phone_from_value_distribution() -> None:
    profiles = profile_columns(
        headers=["A", "B"],
        sample_rows=[
            {"A": "0555 12 34 56", "B": "Alice"},
            {"A": "0660-98-77-66", "B": "Bob"},
            {"A": "+213 7 71 22 33 44", "B": "Celia"},
            {"A": "0770.11.22.33", "B": "Dounia"},
        ],
        agency_profile_hints={},
    )

    phone_profile = profiles[0]
    assert phone_profile["detected_type"] == "phone"
    assert float(phone_profile["confidence"]) >= 0.88
    assert float(phone_profile["semantic_signals"]["phone_ratio"]) >= 0.9


def test_profile_columns_prefers_phone_over_price_for_algerian_phone_digits() -> None:
    profiles = profile_columns(
        headers=["B"],
        sample_rows=[
            {"B": "0555001001"},
            {"B": "0555001002"},
            {"B": "0660112233"},
        ],
        agency_profile_hints={},
    )

    assert profiles[0]["detected_type"] == "phone"
    assert float(profiles[0]["semantic_signals"]["price_ratio"]) == 0.0


def test_profile_columns_detects_price_from_budget_like_values() -> None:
    profiles = profile_columns(
        headers=["Budget", "Notes"],
        sample_rows=[
            {"Budget": "12 000 000 DA", "Notes": "ok"},
            {"Budget": "14500000", "Notes": "ok"},
            {"Budget": "9.500.000 dzd", "Notes": "ok"},
            {"Budget": "18m", "Notes": "ok"},
        ],
        agency_profile_hints={},
    )

    price_profile = profiles[0]
    assert price_profile["detected_type"] == "price"
    assert float(price_profile["semantic_signals"]["price_ratio"]) >= 0.75


def test_profile_columns_detects_property_type_from_repeated_vocab() -> None:
    profiles = profile_columns(
        headers=["Col_3"],
        sample_rows=[
            {"Col_3": "Appartement"},
            {"Col_3": "appart"},
            {"Col_3": "APT"},
            {"Col_3": "apartment"},
        ],
        agency_profile_hints={},
    )

    assert profiles[0]["detected_type"] == "type"
    assert float(profiles[0]["semantic_signals"]["property_type_ratio"]) >= 0.75


def test_profile_import_sheets_prefers_bundle_sheet_over_notes_sheet(tmp_path: Path) -> None:
    workbook = Workbook()
    demandes_sheet = workbook.active
    demandes_sheet.title = "Demandes Mars"
    demandes_sheet.append(["A", "B", "C", "D", "E", "F", "G", "H", "I"])
    demandes_sheet.append(["Hasna", "0555001001", "", "", "", "", "", "", ""])
    demandes_sheet.append(["Karim", "0555001002", "", "", "", "", "", "", ""])
    demandes_sheet.append(
        ["", "", "achat", "Appartement", "Hydra", "12000000", "15000000", "70", "120"]
    )
    demandes_sheet.append(["", "", "location", "apart", "Ben Aknoun", "70000", "90000", "60", "95"])

    notes_sheet = workbook.create_sheet("Notes")
    notes_sheet.append(["A", "B"])
    notes_sheet.append(["appel client", "urgent"])
    notes_sheet.append(["visite demain", "confirmer"])

    path = tmp_path / "bundle-probe.xlsx"
    workbook.save(path)

    profiles = profile_import_sheets(path=path, file_type="excel", agency_profile_hints={})
    selected = choose_dominant_sheet(profiles)

    assert selected == "Demandes Mars"
    demandes_profile = next(
        profile for profile in profiles if str(profile.get("sheet_name", "")) == "Demandes Mars"
    )
    assert demandes_profile["dominant_bundle_mode"] == "same_side_bundle"
    assert demandes_profile["dominant_topology_side"] == "client_side"
    assert any(
        str(group.get("dominant_entity_type", "")) in {"client", "demande"}
        for group in list(demandes_profile.get("row_shape_groups", []))
    )


def test_mapping_gate_requires_manual_mapping_for_conflicting_sheet_profiles() -> None:
    required, reasons, metrics = evaluate_manual_mapping_gate(
        detected_columns=[
            {"header": "A", "detected_type": "phone", "confidence": 0.91},
            {"header": "B", "detected_type": "unknown", "confidence": 0.21},
        ],
        final_inference={"confidence": 0.82, "bundle_mode": "same_side_bundle"},
        column_types={"phone": "phone"},
        sheet_profiles=[
            {
                "sheet_name": "Demandes",
                "dominant_topology_side": "client_side",
                "dominant_bundle_mode": "same_side_bundle",
                "confidence": 0.81,
            },
            {
                "sheet_name": "Offres",
                "dominant_topology_side": "listing_side",
                "dominant_bundle_mode": "same_side_bundle",
                "confidence": 0.8,
            },
        ],
    )

    assert required is True
    assert any("workbook sheets conflict" in reason.lower() for reason in reasons)
    assert float(metrics["conflicting_sheet_profiles"]) == 1.0


def test_mapping_gate_allows_explicit_mapping_to_override_low_inference_confidence() -> None:
    required, reasons, metrics = evaluate_manual_mapping_gate(
        detected_columns=[
            {"header": "Nom du CLIENT", "detected_type": "unknown", "confidence": 0.21},
            {"header": "Portable / TEL", "detected_type": "phone", "confidence": 0.48},
            {"header": "Remarques / notes", "detected_type": "remarks", "confidence": 0.51},
        ],
        final_inference={
            "confidence": 0.34,
            "bundle_mode": "single_entity",
            "topology_side_hint": "client_side",
        },
        column_types={
            "family_name": "family_name",
            "phone": "phone",
            "remarks": "remarks",
            "status": "status",
        },
    )

    assert required is False
    assert reasons == []
    assert float(metrics["inference_confidence"]) < 0.55


def test_build_bulk_fix_groups_uses_normalized_payload_when_raw_data_has_source_headers() -> None:
    groups = build_bulk_fix_groups(
        [
            {
                "row": 3,
                "original": {"Commune": "Ben Ak"},
                "normalized_data": {"location": "Ben Ak"},
                "recovery_candidates": [
                    {
                        "field": "location",
                        "candidate_value": "16022",
                        "candidate_label": "Ben Aknoun",
                    }
                ],
            },
            {
                "row": 8,
                "original": {"Commune": "Ben Ak"},
                "normalized_data": {"location": "Ben Ak"},
                "recovery_candidates": [
                    {
                        "field": "location",
                        "candidate_value": "16022",
                        "candidate_label": "Ben Aknoun",
                    }
                ],
            },
        ]
    )

    assert groups == [
        {
            "group_key": "location:ben ak",
            "field": "location",
            "source_value": "Ben Ak",
            "occurrence_count": 2,
            "suggested_candidate_label": "Ben Aknoun",
            "suggested_candidate_value": "16022",
            "target_rows": [3, 8],
        }
    ]


def test_expand_bulk_operations_applies_replacement_to_target_rows() -> None:
    expanded = expand_bulk_operations(
        review_rows=[
            {"row": 3, "normalized_data": {"location": "Ben Ak", "type": "apartment"}},
            {"row": 8, "normalized_data": {"location": "Ben Ak", "type": "apartment"}},
        ],
        corrections={"8": {"type": "house"}},
        bulk_operations=[
            {
                "operation": "replace_value_in_import",
                "field": "location",
                "source_value": "Ben Ak",
                "replacement_value": "16022",
                "target_rows": [3, 8],
            }
        ],
    )

    assert expanded["3"]["location"] == "16022"
    assert expanded["8"]["location"] == "16022"
    assert expanded["8"]["type"] == "house"


def test_quick_fix_actions_and_reclassify_options_are_deterministic() -> None:
    actions = build_quick_fix_actions(
        {
            "recovery_candidates": [
                {
                    "field": "location",
                    "candidate_label": "Ben Aknoun",
                    "candidate_value": "16022",
                }
            ]
        }
    )

    assert actions == [
        {
            "field": "location",
            "label": "Use Ben Aknoun",
            "candidate_value": "16022",
        }
    ]
    assert allowed_reclassify_options(
        bundle_mode="same_side_bundle",
        topology_side="client_side",
        entity_type="client",
    ) == ["client", "demande"]


def test_price_dialect_profiles_flag_ambiguous_million_columns() -> None:
    profiles, summary = build_price_dialect_profiles(
        detected_columns=[
            {"header": "Budget", "detected_type": "price"},
            {"header": "Action", "detected_type": "action"},
        ],
        sample_rows=[
            {"Budget": "15000", "Action": "rent"},
            {"Budget": "1.5 M", "Action": "rent"},
            {"Budget": "2 M", "Action": "rent"},
        ],
        final_inference={"file_model_hint": "client_lead_sheet", "dominant_side": "client_side"},
        agency_id=0,
    )

    assert profiles[0]["header"] == "Budget"
    assert profiles[0]["dominant_dialect"] == "centime_millions"
    assert summary["dominant_dialect"] == "centime_millions"
    assert summary["ambiguous_price_row_count"] == 2


def test_price_dialect_profiles_resolve_explicit_dzd_headers() -> None:
    profiles, summary = build_price_dialect_profiles(
        detected_columns=[{"header": "Budget max/Prix (DZD)", "detected_type": "price"}],
        sample_rows=[
            {"Budget max/Prix (DZD)": "50000 DA"},
            {"Budget max/Prix (DZD)": "1.5 M"},
            {"Budget max/Prix (DZD)": "2 M"},
        ],
        final_inference={"file_model_hint": "client_lead_sheet", "dominant_side": "client_side"},
        agency_id=0,
    )

    assert profiles[0]["header"] == "Budget max/Prix (DZD)"
    assert profiles[0]["ambiguous_example_count"] == 0
    assert summary["ambiguous_price_row_count"] == 0
    assert summary["ambiguous_price_column_count"] == 0


def test_quick_fix_actions_include_price_dialect_choices() -> None:
    actions = build_quick_fix_actions(
        {
            "review_fields": [
                {
                    "field": "budget_max",
                    "original": "1.5 M",
                    "metadata": {
                        "interpretation_candidates": [
                            {
                                "normalized_dzd": 1_500_000,
                                "dialect": "dzd_millions",
                            },
                            {
                                "normalized_dzd": 15_000,
                                "dialect": "centime_millions",
                            },
                        ]
                    },
                }
            ]
        }
    )

    labels = {str(action["label"]) for action in actions}
    assert "Treat as DZD millions" in labels
    assert "Treat as local centime millions" in labels


def test_record_dead_letter_rows_summarizes_dispositions() -> None:
    ensure_schema()
    conn = admin_conn()
    suffix = uuid.uuid4().hex[:8]
    try:
        agency_id = create_agency(conn, f"UTDL{suffix.upper()}", "Unit Test Dead Letter")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"ut_dead_letter_manager_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()
    finally:
        conn.close()
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(id=user_id)
    job = ImportJob.objects.create(
        user=user,
        agency_id=agency_id,
        filename="dead-letter.csv",
        file_type="csv",
        source_path="fixture://dead-letter",
    )
    row = build_dead_letter_row(
        job_id=str(job.id),
        agency_id=agency_id,
        row_ordinal=4,
        disposition="human_skipped",
        phase="review",
        entity_type="client",
        raw_data={"phone": "0555001001"},
        normalized_data={"phone": "0555001001"},
        reason_codes=["review_skip"],
        reason_messages=["Skipped during review."],
    )

    summary = record_dead_letter_rows([row])

    assert summary == {
        "auto_skipped": 0,
        "human_skipped": 1,
        "blocking_discarded": 0,
    }
    ImportJob.objects.filter(id=job.id).delete()
    cleanup = admin_conn()
    try:
        cleanup.execute(
            "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
            (user_id,),
        )
        cleanup.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        cleanup.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        cleanup.commit()
    finally:
        cleanup.close()
