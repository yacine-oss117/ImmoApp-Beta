from __future__ import annotations

from server.services.import_type_inference import infer_file_type, infer_row_entity


def test_infer_file_type_detects_client_side_same_side_bundle() -> None:
    result = infer_file_type(
        headers=["family_name", "phone", "action", "budget_min", "budget_max", "locations"],
        sample_rows=[
            {"family_name": "Benali", "phone": "0555123456"},
            {
                "family_name": "Benali",
                "phone": "0555123456",
                "action": "buy",
                "budget_min": 5000000,
                "budget_max": 7000000,
                "locations": "Hydra, El Biar",
            },
        ],
        ui_hint=None,
    )

    final_inference = result["final_inference"]
    assert final_inference["bundle_mode"] == "same_side_bundle"
    assert final_inference["topology_side_hint"] == "client_side"
    assert final_inference["entity_type_hint"] is None
    assert final_inference["detected_entity"] == "client"
    assert final_inference["ui_hint_used"] is False


def test_infer_file_type_detects_client_bundle_when_each_row_contains_root_and_demande() -> None:
    result = infer_file_type(
        headers=["family_name", "phone", "action", "budget_min", "budget_max", "locations"],
        sample_rows=[
            {
                "family_name": "Benali",
                "phone": "0555123456",
                "action": "buy",
                "budget_min": 5000000,
                "budget_max": 7000000,
                "locations": "Hydra, El Biar",
            },
            {
                "family_name": "Boulahbel",
                "phone": "0555765432",
                "action": "buy",
                "budget_min": 3000000,
                "budget_max": 4500000,
                "locations": "Cheraga",
            },
        ],
        ui_hint=None,
    )

    final_inference = result["final_inference"]
    assert final_inference["bundle_mode"] == "same_side_bundle"
    assert final_inference["topology_side_hint"] == "client_side"
    assert final_inference["detected_entity"] == "client"


def test_infer_file_type_detects_listing_bundle_when_each_row_contains_root_and_offer() -> None:
    result = infer_file_type(
        headers=["family_name", "phone", "action", "budget", "surface", "location"],
        sample_rows=[
            {
                "family_name": "Owner A",
                "phone": "0666123456",
                "action": "sell",
                "budget": 15000000,
                "surface": 120,
                "location": "Ben Aknoun",
            },
            {
                "family_name": "Owner B",
                "phone": "0666765432",
                "action": "sell",
                "budget": 22000000,
                "surface": 180,
                "location": "Hydra",
            },
        ],
        ui_hint=None,
    )

    final_inference = result["final_inference"]
    assert final_inference["bundle_mode"] == "same_side_bundle"
    assert final_inference["topology_side_hint"] == "listing_side"
    assert final_inference["detected_entity"] == "listing"


def test_infer_file_type_blocks_mixed_cross_side_files() -> None:
    result = infer_file_type(
        headers=["family_name", "phone", "action", "budget_min", "budget", "location"],
        sample_rows=[
            {"family_name": "Buyer", "action": "buy", "budget_min": 3000000},
            {"family_name": "Seller", "action": "sell", "budget": 8000000, "location": "Hydra"},
        ],
        ui_hint="client",
    )

    final_inference = result["final_inference"]
    assert final_inference["bundle_mode"] == "mixed_blocked"
    assert final_inference["topology_side_hint"] == "mixed"
    assert final_inference["detected_entity"] is None
    assert final_inference["entity_type_hint"] is None


def test_infer_file_type_uses_ui_hint_only_as_tie_breaker() -> None:
    result = infer_file_type(
        headers=["family_name", "phone"],
        sample_rows=[{"family_name": "Tie", "phone": "0555123456"}],
        ui_hint="listing",
    )

    final_inference = result["final_inference"]
    assert final_inference["detected_entity"] == "listing"
    assert final_inference["ui_hint_used"] is True
    assert "ui hint" in " ".join(final_inference["reasons"]).lower()


def test_infer_file_type_keeps_pure_demande_file_single_entity_despite_generic_notes() -> None:
    result = infer_file_type(
        headers=[
            "client_id",
            "action",
            "type",
            "wilaya",
            "locations",
            "budget_min",
            "budget_max",
            "remarks",
        ],
        sample_rows=[
            {
                "client_id": 101,
                "action": "buy",
                "type": "apartment",
                "wilaya": "16",
                "locations": "Hydra",
                "budget_min": 4000000,
                "budget_max": 6500000,
                "remarks": "normal demande note",
            }
        ],
        ui_hint="client",
    )

    final_inference = result["final_inference"]
    assert final_inference["bundle_mode"] == "single_entity"
    assert final_inference["topology_side_hint"] == "client_side"
    assert final_inference["entity_type_hint"] == "demande"
    assert final_inference["detected_entity"] == "demande"


def test_infer_file_type_keeps_pure_offer_file_single_entity_despite_generic_notes() -> None:
    result = infer_file_type(
        headers=[
            "listing_id",
            "action",
            "type",
            "wilaya",
            "location",
            "budget",
            "surface",
            "remarks",
        ],
        sample_rows=[
            {
                "listing_id": 202,
                "action": "sell",
                "type": "apartment",
                "wilaya": "16",
                "location": "Ben Aknoun",
                "budget": 15000000,
                "surface": 110,
                "remarks": "normal offer note",
            }
        ],
        ui_hint="listing",
    )

    final_inference = result["final_inference"]
    assert final_inference["bundle_mode"] == "single_entity"
    assert final_inference["topology_side_hint"] == "listing_side"
    assert final_inference["entity_type_hint"] == "offer"
    assert final_inference["detected_entity"] == "offer"


def test_infer_row_entity_splits_root_and_child_inside_same_side_bundle() -> None:
    root_row = infer_row_entity(
        {"family_name": "Benali", "phone": "0555123456"},
        bundle_mode="same_side_bundle",
        topology_side_hint="client_side",
    )
    child_row = infer_row_entity(
        {"action": "buy", "budget_min": 4000000, "budget_max": 6000000, "locations": "Hydra"},
        bundle_mode="same_side_bundle",
        topology_side_hint="client_side",
    )

    assert root_row.entity_type == "client"
    assert root_row.topology_side == "client_side"
    assert child_row.entity_type == "demande"
    assert child_row.topology_side == "client_side"


def test_infer_file_type_uses_non_lossy_semantic_evidence_for_client_lead_sheets() -> None:
    result = infer_file_type(
        headers=["name", "phone", "action", "price", "surface"],
        sample_rows=[
            {
                "cells": [
                    {
                        "header": "Nom complet / Client",
                        "detected_type": "name",
                        "detected_role": "root_identity",
                        "side_prior": "client_root",
                        "value": "Nadia",
                        "confidence": 0.95,
                    },
                    {
                        "header": "N° Téléphone",
                        "detected_type": "phone",
                        "detected_role": "root_identity",
                        "side_prior": "client_root",
                        "value": "0555000002",
                        "confidence": 0.95,
                    },
                    {
                        "header": "Action (Vente/Loc)",
                        "detected_type": "action",
                        "detected_role": "child_action",
                        "side_prior": "shared_child",
                        "value": "Achat",
                        "confidence": 0.92,
                    },
                    {
                        "header": "Budget max/Prix (DZD)",
                        "detected_type": "price",
                        "detected_role": "child_budget_max",
                        "side_prior": "client_root",
                        "value": "1 milliard 500",
                        "confidence": 0.9,
                    },
                    {
                        "header": "Surface (m2)",
                        "detected_type": "surface",
                        "detected_role": "child_surface",
                        "side_prior": "shared_child",
                        "value": "80-120",
                        "confidence": 0.88,
                    },
                ]
            }
        ],
        ui_hint=None,
    )

    final_inference = result["final_inference"]
    assert final_inference["file_model_hint"] == "client_lead_sheet"
    assert final_inference["dominant_side"] == "client_side"
    assert final_inference["bundle_mode"] == "same_side_bundle"
    assert final_inference["detected_entity"] == "client"
    assert final_inference["row_mixed_review_count"] == 0


def test_infer_file_type_marks_mixed_when_opposite_side_outliers_dominate() -> None:
    result = infer_file_type(
        headers=["name", "phone", "action", "budget"],
        sample_rows=[
            {
                "cells": [
                    {
                        "header": "Client",
                        "detected_type": "name",
                        "detected_role": "root_identity",
                        "side_prior": "client_root",
                        "value": "Buyer",
                        "confidence": 0.95,
                    },
                    {
                        "header": "Action",
                        "detected_type": "action",
                        "detected_role": "child_action",
                        "side_prior": "shared_child",
                        "value": "Achat",
                        "confidence": 0.9,
                    },
                ]
            },
            {
                "cells": [
                    {
                        "header": "Owner Name",
                        "detected_type": "name",
                        "detected_role": "root_identity",
                        "side_prior": "listing_root",
                        "value": "Seller",
                        "confidence": 0.95,
                    },
                    {
                        "header": "Budget",
                        "detected_type": "price",
                        "detected_role": "child_price_scalar",
                        "side_prior": "listing_root",
                        "value": "15000000",
                        "confidence": 0.9,
                    },
                    {
                        "header": "Action",
                        "detected_type": "action",
                        "detected_role": "child_action",
                        "side_prior": "shared_child",
                        "value": "Vente",
                        "confidence": 0.9,
                    },
                ]
            },
        ],
        ui_hint=None,
    )

    final_inference = result["final_inference"]
    assert final_inference["bundle_mode"] == "mixed_blocked"
    assert final_inference["dominant_side"] == "mixed"
    assert final_inference["file_model_hint"] == "mixed"
