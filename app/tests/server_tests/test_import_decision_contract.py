from __future__ import annotations

import uuid
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    create_agency,
    create_manager_user,
    ensure_django,
)

ensure_django()

from server.api.views_import_execute import import_execute  # noqa: E402
from server.imports.models import ImportJob  # noqa: E402
from server.pg.schema import ensure_schema  # noqa: E402
from server.services.import_decision import build_import_decision  # noqa: E402
from server.services.import_job_queue import QueueClaimResult  # noqa: E402


def _detected_columns(columns: list[tuple[str, str, float]]) -> list[dict[str, object]]:
    return [
        {
            "index": index,
            "header": header,
            "detected_type": detected_type,
            "confidence": confidence,
            "sample_values": [],
        }
        for index, (header, detected_type, confidence) in enumerate(columns)
    ]


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


def _cleanup_agency(*, agency_id: int) -> None:
    ImportJob.objects.filter(agency_id=agency_id).delete()


def test_import_decision_marks_weak_same_side_listing_file_as_manual_mapping() -> None:
    decision = build_import_decision(
        final_inference={
            "bundle_mode": "single_entity",
            "topology_side_hint": "listing_side",
            "detected_entity": "listing",
            "confidence": 0.41,
        },
        detected_columns=_detected_columns(
            [
                ("owner", "name", 0.95),
                ("phone", "phone", 0.95),
                ("action", "action", 0.30),
                ("type", "type", 0.30),
                ("location", "location", 0.30),
                ("budget", "price", 0.30),
            ]
        ),
        column_mapping={"family_name": "owner", "phone": "phone"},
        detected_entity="listing",
    )

    assert decision.outcome == "manual_mapping"
    assert decision.manual_mapping_required is True
    assert decision.mapping_palette_mode == "recovery_union"
    assert "low_inference_confidence" in decision.reason_codes


def test_import_decision_allows_explicit_same_side_bundle_recovery_mapping() -> None:
    decision = build_import_decision(
        final_inference={
            "bundle_mode": "single_entity",
            "topology_side_hint": "listing_side",
            "detected_entity": "listing",
            "confidence": 0.41,
        },
        detected_columns=_detected_columns(
            [
                ("owner", "name", 0.95),
                ("phone", "phone", 0.95),
                ("action", "action", 0.30),
                ("type", "type", 0.30),
                ("location", "location", 0.30),
                ("budget", "price", 0.30),
            ]
        ),
        column_mapping={
            "family_name": "owner",
            "phone": "phone",
            "action": "action",
            "type": "type",
            "location": "location",
            "budget": "budget",
        },
        detected_entity="listing",
    )

    assert decision.outcome == "auto_import"
    assert decision.manual_mapping_required is False
    assert "low_inference_confidence" not in decision.reason_codes


def test_import_decision_marks_preview_review_rows_as_review() -> None:
    decision = build_import_decision(
        final_inference={
            "bundle_mode": "single_entity",
            "topology_side_hint": "client_side",
            "detected_entity": "client",
            "confidence": 0.88,
        },
        detected_columns=_detected_columns(
            [
                ("family_name", "name", 0.95),
                ("phone", "phone", 0.95),
            ]
        ),
        column_mapping={"family_name": "family_name", "phone": "phone"},
        detected_entity="client",
        preview_rows=[
            {
                "row_num": 1,
                "needs_review": True,
                "blocking_reasons": [],
            }
        ],
        recoverability_summary={"review_recoverable": 1},
        preview_attention_summary={"needs_attention": 1},
    )

    assert decision.outcome == "review"
    assert decision.review_required is True
    assert "preview_review_required" in decision.reason_codes


def test_import_execute_recomputes_decision_from_supplied_mapping(monkeypatch) -> None:
    ensure_schema()
    agency_id, _user_id, user = _make_user_and_agency("IMPDGN")
    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename="listing-recovery.csv",
            file_type="csv",
            source_path="fixture://listing-recovery",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="listing",
            detected_columns=_detected_columns(
                [
                    ("owner", "name", 0.95),
                    ("phone", "phone", 0.95),
                    ("action", "action", 0.30),
                    ("type", "type", 0.30),
                    ("location", "location", 0.30),
                    ("budget", "price", 0.30),
                ]
            ),
            column_mapping={"family_name": "owner", "phone": "phone"},
            inference_summary={
                "manual_mapping_required": True,
                "manual_mapping_reasons": ["Low-confidence file semantics."],
                "final_inference": {
                    "bundle_mode": "single_entity",
                    "topology_side_hint": "listing_side",
                    "detected_entity": "listing",
                    "confidence": 0.41,
                },
                "preview_recoverability_summary": {},
                "preview_attention_summary": {},
            },
            result_summary={"row_count": 1},
        )
        monkeypatch.setattr(
            "server.api.views_import_execute.admit_import_execute",
            lambda **_kwargs: SimpleNamespace(
                allowed=True,
                retry_after=0,
                degraded=False,
                execution_profile="green",
                queue_on_pressure=False,
            ),
        )
        monkeypatch.setattr(
            "server.api.views_import_execute.initialize_distributed_workflow",
            lambda **_kwargs: ({"params": {}}, False),
        )
        monkeypatch.setattr(
            "server.api.views_import_execute.claim_execution_or_queue",
            lambda *_args, **_kwargs: QueueClaimResult(
                status="queued",
                queue_position=1,
                agency_queue_depth=1,
            ),
        )

        request = APIRequestFactory().post(
            "/api/v1/import/execute/",
            {
                "session_id": str(job.id),
                "column_mapping": {
                    "family_name": "owner",
                    "phone": "phone",
                    "action": "action",
                    "type": "type",
                    "location": "location",
                    "budget": "budget",
                },
                "entity_type": "listing",
                "duplicate_strategy": "review",
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_execute(request)

        job.refresh_from_db()
        decision = dict((job.inference_summary or {}).get("import_decision", {}) or {})
        assert response.status_code == 202
        assert response.data["status"] == "queued"
        assert bool(decision.get("manual_mapping_required", True)) is False
        assert str(decision.get("outcome", "")) == "auto_import"
    finally:
        _cleanup_agency(agency_id=agency_id)
