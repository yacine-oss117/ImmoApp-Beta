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

from server.imports.models import (  # noqa: E402
    ImportAgencyAlias,
    ImportAgencyProfile,
    ImportCorrectionSignal,
    ImportDeadLetterRow,
    ImportJob,
)
from server.pg.schema import ensure_schema  # noqa: E402
from server.services.import_agency_profile import (  # noqa: E402
    load_agency_profile_hints,
    refresh_agency_profile,
)
from server.services.import_learning import record_learning_signals  # noqa: E402
from server.services.import_service import ImportService  # noqa: E402


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
    ImportDeadLetterRow.objects.filter(agency_id=agency_id).delete()
    ImportAgencyProfile.objects.filter(agency_id=agency_id).delete()
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


def test_review_skip_creates_dead_letter_row() -> None:
    ensure_schema()
    agency_id, user_id, user = _make_user_and_agency("IMPDL")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="review.csv",
            file_type="csv",
            source_path="fixture://review",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.REVIEW,
        )
        service = ImportService(user)

        result = service.apply_review_resolutions(
            job_id=str(job.id),
            entity_type="client",
            review_rows=[
                {
                    "row": 1,
                    "data": {"family_name": "Client Example", "phone": "0555001001"},
                    "original": {"Nom": "Client Example", "Telephone": "0555001001"},
                    "entity_type": "client",
                    "topology_side": "client_side",
                    "blocking_reasons": ["Unknown location"],
                    "recoverability_class": "blocking",
                }
            ],
            corrections={},
            decisions={},
            skip_rows=[1],
        )

        dead_letters = list(
            ImportDeadLetterRow.objects.filter(job_id=str(job.id)).values(
                "row_ordinal",
                "disposition",
                "phase",
                "recoverability_class",
            )
        )
        assert result["dead_letter_summary"] == {
            "auto_skipped": 0,
            "human_skipped": 0,
            "blocking_discarded": 1,
        }
        assert dead_letters == [
            {
                "row_ordinal": 1,
                "disposition": "blocking_discarded",
                "phase": "review",
                "recoverability_class": "blocking",
            }
        ]
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)


def test_refresh_agency_profile_builds_tenant_scoped_hints() -> None:
    ensure_schema()
    agency_a, user_a_id, user_a = _make_user_and_agency("IMPPA")
    agency_b, user_b_id, user_b = _make_user_and_agency("IMPPB")
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

        record_learning_signals(
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
        record_learning_signals(
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

        profile_a = refresh_agency_profile(
            agency_id=agency_a,
            bundle_shape_hint="client_side_bundle",
            preferred_language="fr",
            missing_fields=["wilaya", "wilaya"],
        )
        hints_a = load_agency_profile_hints(agency_a)
        hints_b = load_agency_profile_hints(agency_b)

        assert profile_a["preferred_language"] == "fr"
        assert profile_a["bundle_shape_hint"] == "client_side_bundle"
        assert hints_a["default_wilaya"] == "16"
        assert hints_a["bundle_shape_hint"] == "client_side_bundle"
        assert hints_a["preferred_language"] == "fr"
        assert hints_a["location_abbreviations"]["ben ak"] == "Ben Aknoun"
        assert hints_a["common_missing_fields"] == ["wilaya"]
        assert hints_b == {}
    finally:
        _cleanup_agency(agency_id=agency_a, user_id=user_a_id)
        _cleanup_agency(agency_id=agency_b, user_id=user_b_id)
