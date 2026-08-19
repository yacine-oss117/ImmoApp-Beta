from __future__ import annotations

import uuid

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    create_agency,
    create_manager_user,
    ensure_django,
)

ensure_django()

from django.contrib.auth import get_user_model  # noqa: E402

from server.imports.models import ImportAgencyAlias, ImportCorrectionSignal, ImportJob  # noqa: E402
from server.pg.schema import ensure_schema  # noqa: E402
from server.services.import_agency_memory import load_agency_alias_memory  # noqa: E402
from server.services.import_learning import record_learning_signals  # noqa: E402


def _make_user_and_agency(prefix: str) -> tuple[int, int, object]:
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"{prefix}{uuid.uuid4().hex[:6]}", f"{prefix} Agency")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"{prefix.lower()}_{uuid.uuid4().hex[:8]}",
            password="StrongTestPass_123!",
        )
        conn.commit()
    finally:
        conn.close()
    user = get_user_model().objects.get(id=user_id)
    return agency_id, user_id, user


def _cleanup_agency(*, agency_id: int, user_id: int) -> None:
    ImportCorrectionSignal.objects.filter(agency_id=agency_id).delete()
    ImportAgencyAlias.objects.filter(agency_id=agency_id).delete()
    ImportJob.objects.filter(agency_id=agency_id).delete()
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


def test_review_learning_promotes_repeated_agency_alias_without_cross_agency_leakage() -> None:
    ensure_schema()
    agency_a, user_a_id, user_a = _make_user_and_agency("IMPLA")
    agency_b, user_b_id, user_b = _make_user_and_agency("IMPLB")
    try:
        job1 = ImportJob.objects.create(
            user=user_a,
            agency_id=agency_a,
            filename="learn-1.csv",
            file_type="csv",
            source_path="fixture://learn-1",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
        )
        job2 = ImportJob.objects.create(
            user=user_a,
            agency_id=agency_a,
            filename="learn-2.csv",
            file_type="csv",
            source_path="fixture://learn-2",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
        )

        summary1 = record_learning_signals(
            agency_id=agency_a,
            job_id=str(job1.id),
            actor_id=user_a_id,
            applied_rows=[
                {
                    "action": "create",
                    "entity_type": "offer",
                    "row_num": 1,
                    "correction_payload": {"location": "16022"},
                    "validated_row": {"location": "16022"},
                    "review_entry": {"normalized_data": {"location": "Ben Ak"}},
                },
                {
                    "action": "create",
                    "entity_type": "offer",
                    "row_num": 2,
                    "correction_payload": {"location": "16022"},
                    "validated_row": {"location": "16022"},
                    "review_entry": {"normalized_data": {"location": "Ben Ak"}},
                },
            ],
        )
        summary2 = record_learning_signals(
            agency_id=agency_a,
            job_id=str(job2.id),
            actor_id=user_a_id,
            applied_rows=[
                {
                    "action": "create",
                    "entity_type": "offer",
                    "row_num": 1,
                    "correction_payload": {"location": "16022"},
                    "validated_row": {"location": "16022"},
                    "review_entry": {"normalized_data": {"location": "Ben Ak"}},
                }
            ],
        )

        alias = ImportAgencyAlias.objects.get(
            agency_id=agency_a,
            domain="location",
            source_value_normalized="ben ak",
        )
        memory_a = load_agency_alias_memory(agency_a, domains=["location"])
        memory_b = load_agency_alias_memory(agency_b, domains=["location"])

        assert summary1["signals_recorded"] == 2
        assert summary2["signals_recorded"] == 1
        assert alias.state == ImportAgencyAlias.State.TRUSTED
        assert alias.confirm_count == 3
        assert alias.distinct_job_count >= 2
        assert memory_a.trusted["location"]["ben ak"].canonical_key == "16022"
        assert "location" not in memory_b.trusted or "ben ak" not in memory_b.trusted.get(
            "location", {}
        )
    finally:
        _cleanup_agency(agency_id=agency_a, user_id=user_a_id)
        _cleanup_agency(agency_id=agency_b, user_id=user_b_id)


def test_review_learning_promotes_price_dialect_per_agency_only() -> None:
    ensure_schema()
    agency_a, user_a_id, user_a = _make_user_and_agency("IMPPA")
    agency_b, user_b_id, _user_b = _make_user_and_agency("IMPPB")
    try:
        job1 = ImportJob.objects.create(
            user=user_a,
            agency_id=agency_a,
            filename="price-learn-1.csv",
            file_type="csv",
            source_path="fixture://price-learn-1",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
        )
        job2 = ImportJob.objects.create(
            user=user_a,
            agency_id=agency_a,
            filename="price-learn-2.csv",
            file_type="csv",
            source_path="fixture://price-learn-2",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
        )
        review_entry = {
            "normalized_data": {"budget_max": None, "action": "rent"},
            "review_fields": [
                {
                    "field": "budget_max",
                    "original": "1.5 M",
                    "metadata": {
                        "source_header": "Budget",
                        "interpretation_candidates": [
                            {
                                "normalized_dzd": 1_500_000,
                                "dialect": "dzd_millions",
                                "expression_kind": "dzd_millions",
                                "confidence": 0.74,
                                "reason_codes": ["ambiguous_million_token"],
                                "selected_by_context": False,
                            },
                            {
                                "normalized_dzd": 15_000,
                                "dialect": "centime_millions",
                                "expression_kind": "centime_millions",
                                "confidence": 0.74,
                                "reason_codes": ["ambiguous_million_token"],
                                "selected_by_context": False,
                            },
                        ],
                    },
                }
            ],
        }

        summary1 = record_learning_signals(
            agency_id=agency_a,
            job_id=str(job1.id),
            actor_id=user_a_id,
            applied_rows=[
                {
                    "action": "create",
                    "entity_type": "demande",
                    "row_num": 1,
                    "correction_payload": {"budget_max": 15_000},
                    "validated_row": {"budget_max": 15_000},
                    "review_entry": review_entry,
                },
                {
                    "action": "create",
                    "entity_type": "demande",
                    "row_num": 2,
                    "correction_payload": {"budget_max": 15_000},
                    "validated_row": {"budget_max": 15_000},
                    "review_entry": review_entry,
                },
            ],
        )
        summary2 = record_learning_signals(
            agency_id=agency_a,
            job_id=str(job2.id),
            actor_id=user_a_id,
            applied_rows=[
                {
                    "action": "create",
                    "entity_type": "demande",
                    "row_num": 1,
                    "correction_payload": {"budget_max": 15_000},
                    "validated_row": {"budget_max": 15_000},
                    "review_entry": review_entry,
                }
            ],
        )

        alias = ImportAgencyAlias.objects.get(
            agency_id=agency_a,
            domain="price",
            source_value_normalized="1.5m",
        )
        memory_a = load_agency_alias_memory(agency_a, domains=["price"])
        memory_b = load_agency_alias_memory(agency_b, domains=["price"])

        assert summary1["signals_recorded"] == 2
        assert summary2["signals_recorded"] == 1
        assert alias.state == ImportAgencyAlias.State.TRUSTED
        assert alias.confirm_count == 3
        assert alias.metadata["dialect"] == "centime_millions"
        assert memory_a.trusted["price"]["1.5m"].metadata["dialect"] == "centime_millions"
        assert "price" not in memory_b.trusted or "1.5m" not in memory_b.trusted.get("price", {})
    finally:
        _cleanup_agency(agency_id=agency_a, user_id=user_a_id)
        _cleanup_agency(agency_id=agency_b, user_id=user_b_id)
