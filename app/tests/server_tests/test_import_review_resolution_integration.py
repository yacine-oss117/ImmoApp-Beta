from __future__ import annotations

import csv
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

pytest.importorskip("psycopg", reason="import integration tests require Postgres")

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    create_agency,
    create_manager_user,
    ensure_django,
)

ensure_django()

from django.contrib.auth import get_user_model  # noqa: E402

from core.importer.detection.column_detector import ColumnDetector  # noqa: E402
from server.api.views_import_review import import_review_submit  # noqa: E402
from server.imports.models import ImportJob, ImportReviewItem  # noqa: E402
from server.pg.schema import ensure_schema  # noqa: E402
from server.pg.uow import use_security_context  # noqa: E402
from server.services import clients as clients_service  # noqa: E402
from server.services import import_executor  # noqa: E402
from server.services.import_review_submit_service import run_review_submit_task  # noqa: E402
from server.services.import_service import ImportService  # noqa: E402


def _write_client_csv(*, path: Path, phone: str, family_name: str, remarks: str) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["family_name", "phone", "remarks"])
        writer.writerow([family_name, phone, remarks])
    return path


def _detected_columns(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        headers = next(csv.reader(handle), [])
    detector = ColumnDetector()
    detected: list[dict[str, object]] = []
    for idx, header in enumerate(headers):
        result = detector.detect_column_type(str(header), sample_values=[])
        detected.append(
            {
                "index": idx,
                "header": str(header),
                "detected_type": result.detected_type,
                "confidence": result.confidence,
                "sample_values": [],
            }
        )
    return detected


def _make_job(
    *,
    user_id: int,
    agency_id: int,
    csv_path: Path,
    entity_type: str = "client",
) -> ImportJob:
    detected_columns = _detected_columns(csv_path)
    mapping = {
        "family_name": "family_name",
        "phone": "phone",
        "remarks": "remarks",
    }
    return ImportJob.objects.create(
        user_id=user_id,
        agency_id=agency_id,
        filename=csv_path.name,
        file_type="csv",
        source_path="fixture://import-review",
        status=ImportJob.Status.READY,
        stage=ImportJob.Stage.EXECUTION,
        detected_entity=entity_type,
        detected_columns=detected_columns,
        column_mapping=mapping,
        result_summary={"row_count": 1},
    )


def _run_import_job(
    *,
    monkeypatch: pytest.MonkeyPatch,
    csv_path: Path,
    job: ImportJob,
    agency_id: int,
    user_id: int,
) -> import_executor.ImportResult:
    monkeypatch.setattr(
        import_executor,
        "download_to_temp",
        lambda _source_path, suffix=None: csv_path,
    )

    import server.api.notifications as notifications

    monkeypatch.setattr(notifications, "notify_only", lambda **_kwargs: None)
    monkeypatch.setattr(notifications, "record_and_notify", lambda **_kwargs: None)

    with use_security_context(agency_id=agency_id, is_superuser=False):
        return import_executor.execute_import(
            job=job,
            user_id=user_id,
            duplicate_strategy="review",
        )


def _insert_existing_client(
    *, conn: object, agency_id: int, family_name: str, phone: str, remarks: str
) -> int:
    row = conn.execute(
        """
        INSERT INTO clients (family_name, phone, agency_id, status, remarks, created_at, updated_at)
        VALUES (%s, %s, %s, 'active', %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (family_name, phone, agency_id, remarks),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def test_client_import_review_candidates_are_scoped_to_the_same_agency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    phone = "0555123456"

    agency_a = 0
    agency_b = 0
    user_a = 0
    client_a = 0
    client_b = 0
    conn = admin_conn()
    try:
        agency_a = create_agency(conn, f"IMPRV_A_{suffix}", f"Import Review A {suffix}")
        agency_b = create_agency(conn, f"IMPRV_B_{suffix}", f"Import Review B {suffix}")
        user_a = create_manager_user(
            conn,
            agency_id=agency_a,
            username=f"imp_review_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()

        client_a = _insert_existing_client(
            conn=conn,
            agency_id=agency_a,
            family_name=f"Agency A Existing {suffix}",
            phone=phone,
            remarks="agency-a",
        )
        client_b = _insert_existing_client(
            conn=conn,
            agency_id=agency_b,
            family_name=f"Agency B Existing {suffix}",
            phone=phone,
            remarks="agency-b",
        )
        conn.commit()

        csv_path = _write_client_csv(
            path=tmp_path / f"client_review_{suffix}.csv",
            phone=phone,
            family_name="Updated Import",
            remarks="from-import",
        )
        job = _make_job(user_id=user_a, agency_id=agency_a, csv_path=csv_path)

        result = _run_import_job(
            monkeypatch=monkeypatch,
            csv_path=csv_path,
            job=job,
            agency_id=agency_a,
            user_id=user_a,
        )
        job.refresh_from_db()

        assert result.success is True
        assert job.stage == ImportJob.Stage.REVIEW
        assert len(job.review_rows or []) == 1
        review_row = dict((job.review_rows or [])[0])
        candidates = list(review_row.get("candidate_matches", []) or [])
        assert len(candidates) == 1
        assert int(candidates[0]["id"]) == client_a
        assert int(candidates[0]["id"]) != client_b
        assert int(candidates[0]["row_version"]) > 0
    finally:
        if agency_a:
            conn.execute(
                "DELETE FROM match_rebuild_state WHERE agency_id IN (%s, %s)",
                (agency_a, agency_b or -1),
            )
            conn.execute(
                "DELETE FROM imports_importrowaudit WHERE agency_id IN (%s, %s)",
                (agency_a, agency_b or -1),
            )
            conn.execute(
                "DELETE FROM imports_importjob WHERE agency_id IN (%s, %s)",
                (agency_a, agency_b or -1),
            )
        if client_a:
            conn.execute("DELETE FROM clients WHERE id = %s", (client_a,))
        if client_b:
            conn.execute("DELETE FROM clients WHERE id = %s", (client_b,))
        if user_a:
            conn.execute(
                "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
                (user_a,),
            )
            conn.execute("DELETE FROM accounts_user WHERE id = %s", (user_a,))
        if agency_a:
            conn.execute(
                "DELETE FROM audit_logs WHERE agency_id IN (%s, %s)",
                (agency_a, agency_b or -1),
            )
            conn.execute(
                "DELETE FROM accounts_agency WHERE id IN (%s, %s)",
                (agency_a, agency_b or -1),
            )
        conn.commit()
        conn.close()


def test_client_import_review_suggests_update_for_high_confidence_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    phone = "0555010101"

    agency_id = 0
    user_id = 0
    client_id = 0
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"IMPHC_{suffix}", f"Import High Confidence {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"imp_hc_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()

        client_id = _insert_existing_client(
            conn=conn,
            agency_id=agency_id,
            family_name="Hasna Amrani",
            phone=phone,
            remarks="existing",
        )
        conn.commit()

        csv_path = _write_client_csv(
            path=tmp_path / f"client_review_hc_{suffix}.csv",
            phone=phone,
            family_name="Hasna Amrani",
            remarks="from-import",
        )
        job = _make_job(user_id=user_id, agency_id=agency_id, csv_path=csv_path)

        result = _run_import_job(
            monkeypatch=monkeypatch,
            csv_path=csv_path,
            job=job,
            agency_id=agency_id,
            user_id=user_id,
        )
        job.refresh_from_db()

        assert result.success is True
        review_row = dict((job.review_rows or [])[0])
        assert review_row.get("suggested_action") == "update_existing"
        assert int(review_row.get("suggested_existing_id", 0) or 0) == client_id
        assert float(review_row.get("suggested_confidence", 0.0) or 0.0) >= 0.9
        metadata = dict(review_row.get("metadata", {}) or {})
        assert "suggested_reasons" not in review_row
        assert "same name" in list(metadata.get("suggested_reasons", []) or [])
        candidate = dict((review_row.get("candidate_matches", []) or [])[0])
        assert candidate.get("remarks") == "existing"
        field_diffs = list(candidate.get("field_diffs", []) or [])
        assert any(
            str(diff.get("field", "") or "") == "remarks"
            and str(diff.get("incoming", "") or "") == "from-import"
            and str(diff.get("existing", "") or "") == "existing"
            for diff in field_diffs
        )
    finally:
        if agency_id:
            conn.execute("DELETE FROM match_rebuild_state WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM imports_importrowaudit WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM imports_importjob WHERE agency_id = %s", (agency_id,))
        if client_id:
            conn.execute("DELETE FROM clients WHERE id = %s", (client_id,))
        if user_id:
            conn.execute(
                "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
                (user_id,),
            )
            conn.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        if agency_id:
            conn.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        conn.commit()
        conn.close()


def test_listing_import_review_candidates_are_scoped_to_the_same_agency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    phone = "0666010203"

    agency_a = 0
    agency_b = 0
    user_a = 0
    listing_a = 0
    listing_b = 0
    conn = admin_conn()
    try:
        agency_a = create_agency(conn, f"IMPLA_{suffix}", f"Import Listing A {suffix}")
        agency_b = create_agency(conn, f"IMPLB_{suffix}", f"Import Listing B {suffix}")
        user_a = create_manager_user(
            conn,
            agency_id=agency_a,
            username=f"imp_listing_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()

        row_a = conn.execute(
            """
            INSERT INTO listings (family_name, phone, agency_id, status, remarks, created_at, updated_at)
            VALUES (%s, %s, %s, 'available', %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            ("Agence Centrale", phone, agency_a, "agency-a"),
        ).fetchone()
        assert row_a is not None
        listing_a = int(row_a["id"])
        row_b = conn.execute(
            """
            INSERT INTO listings (family_name, phone, agency_id, status, remarks, created_at, updated_at)
            VALUES (%s, %s, %s, 'available', %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            ("Agence Littorale", phone, agency_b, "agency-b"),
        ).fetchone()
        assert row_b is not None
        listing_b = int(row_b["id"])
        conn.commit()

        csv_path = _write_client_csv(
            path=tmp_path / f"listing_review_{suffix}.csv",
            phone=phone,
            family_name="Agence Centrale",
            remarks="from-import",
        )
        job = _make_job(
            user_id=user_a,
            agency_id=agency_a,
            csv_path=csv_path,
            entity_type="listing",
        )

        result = _run_import_job(
            monkeypatch=monkeypatch,
            csv_path=csv_path,
            job=job,
            agency_id=agency_a,
            user_id=user_a,
        )
        job.refresh_from_db()

        assert result.success is True
        review_row = dict((job.review_rows or [])[0])
        candidates = list(review_row.get("candidate_matches", []) or [])
        assert len(candidates) == 1
        assert int(candidates[0]["id"]) == listing_a
        assert int(candidates[0]["id"]) != listing_b
        assert review_row.get("suggested_action") == "update_existing"
    finally:
        if agency_a:
            conn.execute(
                "DELETE FROM match_rebuild_state WHERE agency_id IN (%s, %s)",
                (agency_a, agency_b or -1),
            )
        if agency_a:
            conn.execute(
                "DELETE FROM imports_importrowaudit WHERE agency_id IN (%s, %s)",
                (agency_a, agency_b or -1),
            )
            conn.execute(
                "DELETE FROM imports_importjob WHERE agency_id IN (%s, %s)",
                (agency_a, agency_b or -1),
            )
        if listing_a:
            conn.execute("DELETE FROM listings WHERE id = %s", (listing_a,))
        if listing_b:
            conn.execute("DELETE FROM listings WHERE id = %s", (listing_b,))
        if user_a:
            conn.execute(
                "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
                (user_a,),
            )
            conn.execute("DELETE FROM accounts_user WHERE id = %s", (user_a,))
        if agency_a:
            conn.execute(
                "DELETE FROM audit_logs WHERE agency_id IN (%s, %s)",
                (agency_a, agency_b or -1),
            )
            conn.execute(
                "DELETE FROM accounts_agency WHERE id IN (%s, %s)",
                (agency_a, agency_b or -1),
            )
        conn.commit()
        conn.close()


def test_apply_review_resolution_rejects_cross_agency_update_and_accepts_same_agency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    phone = "0555987654"

    agency_a = 0
    agency_b = 0
    user_a = 0
    client_a = 0
    client_b = 0
    conn = admin_conn()
    try:
        agency_a = create_agency(conn, f"IMPRU_A_{suffix}", f"Import Resolve A {suffix}")
        agency_b = create_agency(conn, f"IMPRU_B_{suffix}", f"Import Resolve B {suffix}")
        user_a = create_manager_user(
            conn,
            agency_id=agency_a,
            username=f"imp_resolve_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()

        client_a = _insert_existing_client(
            conn=conn,
            agency_id=agency_a,
            family_name=f"Agency A Existing {suffix}",
            phone=phone,
            remarks="agency-a-original",
        )
        client_b = _insert_existing_client(
            conn=conn,
            agency_id=agency_b,
            family_name=f"Agency B Existing {suffix}",
            phone=phone,
            remarks="agency-b-original",
        )
        conn.commit()

        csv_path = _write_client_csv(
            path=tmp_path / f"client_resolve_{suffix}.csv",
            phone=phone,
            family_name="Resolved Import",
            remarks="updated-from-review",
        )
        job = _make_job(user_id=user_a, agency_id=agency_a, csv_path=csv_path)
        _run_import_job(
            monkeypatch=monkeypatch,
            csv_path=csv_path,
            job=job,
            agency_id=agency_a,
            user_id=user_a,
        )
        job.refresh_from_db()
        review_rows = list(job.review_rows or [])
        assert len(review_rows) == 1
        review_row = dict(review_rows[0])
        candidate = dict((review_row.get("candidate_matches", []) or [])[0])

        user = get_user_model().objects.get(id=user_a)
        service = ImportService(user)

        with use_security_context(agency_id=agency_a, is_superuser=False):
            cross_result = service.apply_review_resolutions(
                entity_type="client",
                review_rows=review_rows,
                corrections={},
                decisions={
                    str(review_row["row"]): {
                        "action": "update",
                        "existing_id": client_b,
                        "row_version": candidate["row_version"],
                    }
                },
                skip_rows=[],
            )
            assert cross_result["created_count"] == 0
            assert cross_result["updated_count"] == 0
            assert len(cross_result["still_review"]) == 1

            good_result = service.apply_review_resolutions(
                entity_type="client",
                review_rows=review_rows,
                corrections={},
                decisions={
                    str(review_row["row"]): {
                        "action": "update",
                        "existing_id": client_a,
                        "row_version": candidate["row_version"],
                    }
                },
                skip_rows=[],
            )
            assert good_result["created_count"] == 0
            assert good_result["updated_count"] == 1
            assert good_result["still_review"] == []

        with use_security_context(agency_id=agency_a, is_superuser=False):
            updated_a = clients_service.get_client_by_id(client_a)
        with use_security_context(agency_id=agency_b, is_superuser=False):
            untouched_b = clients_service.get_client_by_id(client_b)
        assert updated_a is not None
        assert untouched_b is not None
        assert updated_a.remarks == "updated-from-review"
        assert updated_a.family_name == "Resolved Import"
        assert untouched_b.remarks == "agency-b-original"
    finally:
        if agency_a:
            conn.execute(
                "DELETE FROM match_rebuild_state WHERE agency_id IN (%s, %s)",
                (agency_a, agency_b or -1),
            )
            conn.execute(
                "DELETE FROM imports_importrowaudit WHERE agency_id IN (%s, %s)",
                (agency_a, agency_b or -1),
            )
            conn.execute(
                "DELETE FROM imports_importjob WHERE agency_id IN (%s, %s)",
                (agency_a, agency_b or -1),
            )
        if client_a:
            conn.execute("DELETE FROM clients WHERE id = %s", (client_a,))
        if client_b:
            conn.execute("DELETE FROM clients WHERE id = %s", (client_b,))
        if user_a:
            conn.execute(
                "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
                (user_a,),
            )
            conn.execute("DELETE FROM accounts_user WHERE id = %s", (user_a,))
        if agency_a:
            conn.execute(
                "DELETE FROM audit_logs WHERE agency_id IN (%s, %s)",
                (agency_a, agency_b or -1),
            )
            conn.execute(
                "DELETE FROM accounts_agency WHERE id IN (%s, %s)",
                (agency_a, agency_b or -1),
            )
        conn.commit()
        conn.close()


def test_import_review_submit_persists_audit_history_and_returns_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    phone = "0555777000"

    agency_id = 0
    user_id = 0
    client_id = 0
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"IMPRH_{suffix}", f"Import Review History {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"imp_hist_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()

        client_id = _insert_existing_client(
            conn=conn,
            agency_id=agency_id,
            family_name="Review Existing",
            phone=phone,
            remarks="existing",
        )
        conn.commit()

        csv_path = _write_client_csv(
            path=tmp_path / f"client_review_history_{suffix}.csv",
            phone=phone,
            family_name="Review Existing",
            remarks="from-import",
        )
        job = _make_job(user_id=user_id, agency_id=agency_id, csv_path=csv_path)
        _run_import_job(
            monkeypatch=monkeypatch,
            csv_path=csv_path,
            job=job,
            agency_id=agency_id,
            user_id=user_id,
        )
        job.refresh_from_db()

        review_row = dict((job.review_rows or [])[0])
        user = get_user_model().objects.get(id=user_id)
        request = APIRequestFactory().post(
            f"/api/v1/import/{job.id}/review/submit/",
            {
                "corrections": {},
                "decisions": {str(review_row["row"]): {"action": "review"}},
                "skip_rows": [],
            },
            format="json",
        )
        force_authenticate(request, user=user)
        monkeypatch.setattr(
            "server.api.views_import_review.enqueue_import_task",
            lambda _task, **_kwargs: SimpleNamespace(id="review-submit-task-history"),
        )
        monkeypatch.setattr(
            "server.api.views_import_review.register_task", lambda *args, **kwargs: None
        )

        response = import_review_submit(request, str(job.id))
        run_review_submit_task(
            session_id=str(job.id),
            actor_user_id=user_id,
            agency_id=agency_id,
            correlation_id="",
        )

        assert response.status_code == 202
        job.refresh_from_db()
        summary = dict(job.result_summary or {})
        assert dict(summary.get("decision_summary", {}) or {}) == {
            "create_new": 0,
            "review_ambiguous": 1,
            "skip": 0,
            "update_existing": 0,
        }
        assert int(summary.get("review_history_count", 0) or 0) == 1
        history = list(summary.get("review_history", []) or [])
        assert len(history) == 1
        assert history[0]["action"] == "review"
        assert history[0]["suggested_action"] == "update_existing"
        assert int(history[0]["suggested_existing_id"] or 0) == client_id

        saved_summary = dict(job.result_summary or {})
        saved_history = list(saved_summary.get("review_history", []) or [])
        assert len(saved_history) == 1
        assert saved_history[0]["action"] == "review"
        still_review = list(job.review_rows or [])
        assert len(still_review) == 1
        assert still_review[0]["suggested_action"] == "update_existing"
    finally:
        if agency_id:
            conn.execute("DELETE FROM match_rebuild_state WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM imports_importrowaudit WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM imports_importjob WHERE agency_id = %s", (agency_id,))
        if client_id:
            conn.execute("DELETE FROM clients WHERE id = %s", (client_id,))
        if user_id:
            conn.execute(
                "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
                (user_id,),
            )
            conn.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        if agency_id:
            conn.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        conn.commit()
        conn.close()


def test_import_review_submit_applies_item_level_corrections_before_async_finalize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    corrected_name = "ReviewFixedAlpha"
    phone = "0555888111"

    agency_id = 0
    user_id = 0
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"IMPRC_{suffix}", f"Import Review Corrected {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"imp_corr_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()

        csv_path = _write_client_csv(
            path=tmp_path / f"client_review_corrected_{suffix}.csv",
            phone=phone,
            family_name=f"{corrected_name}123",
            remarks="needs-review",
        )
        job = _make_job(user_id=user_id, agency_id=agency_id, csv_path=csv_path)
        _run_import_job(
            monkeypatch=monkeypatch,
            csv_path=csv_path,
            job=job,
            agency_id=agency_id,
            user_id=user_id,
        )
        job.refresh_from_db()

        assert job.stage == ImportJob.Stage.REVIEW
        review_item = ImportReviewItem.objects.filter(job=job).first()
        assert review_item is not None
        user = get_user_model().objects.get(id=user_id)
        request = APIRequestFactory().post(
            f"/api/v1/import/{job.id}/review/submit/",
            {
                "item_decisions": {
                    str(int(review_item.id)): {
                        "action": "create_new",
                        "entity_type": "client",
                        "corrections": {
                            "family_name": corrected_name,
                            "phone": phone,
                        },
                    }
                },
                "group_decisions": {},
                "skip_item_ids": [],
                "bulk_operations": [],
            },
            format="json",
        )
        force_authenticate(request, user=user)
        monkeypatch.setattr(
            "server.api.views_import_review.enqueue_import_task",
            lambda _task, **_kwargs: SimpleNamespace(id="review-submit-task-corrected"),
        )
        monkeypatch.setattr(
            "server.api.views_import_review.register_task", lambda *args, **kwargs: None
        )

        response = import_review_submit(request, str(job.id))
        assert response.status_code == 202

        with use_security_context(agency_id=agency_id, is_superuser=False):
            task_result = run_review_submit_task(
                session_id=str(job.id),
                actor_user_id=user_id,
                agency_id=agency_id,
                correlation_id="review-corrections",
                task_id=str(response.data["task_id"]),
            )

        job.refresh_from_db()
        summary = dict(job.result_summary or {})
        with use_security_context(agency_id=agency_id, is_superuser=False):
            persisted_clients = list(
                clients_service.fetch_clients(
                    limit=20,
                    offset=0,
                    search="",
                    status=None,
                    include_deleted=True,
                )
            )
        persisted_client = next(
            (
                client
                for client in persisted_clients
                if str(getattr(client, "family_name", "") or "") == corrected_name
                and str(getattr(client, "phone", "") or "") == phone
            ),
            None,
        )

        assert task_result["status"] == ImportJob.Status.COMPLETED
        assert job.status == ImportJob.Status.COMPLETED
        assert job.stage == ImportJob.Stage.EXECUTION
        assert list(job.review_rows or []) == []
        assert int(summary.get("created_count", 0) or 0) == 1
        assert persisted_client is not None
        assert str(getattr(persisted_client, "family_name", "") or "") == corrected_name
        assert str(getattr(persisted_client, "phone", "") or "") == phone
    finally:
        if agency_id:
            conn.execute("DELETE FROM match_rebuild_state WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM imports_importrowaudit WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM imports_importjob WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
        if user_id:
            conn.execute(
                "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
                (user_id,),
            )
            conn.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        if agency_id:
            conn.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        conn.commit()
        conn.close()


def test_import_review_submit_applies_group_decision_with_item_level_corrections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    corrected_name = "ReviewGroupedAlpha"
    phone = "0555888222"

    agency_id = 0
    user_id = 0
    conn = admin_conn()
    try:
        agency_id = create_agency(conn, f"IMPRG_{suffix}", f"Import Review Grouped {suffix}")
        user_id = create_manager_user(
            conn,
            agency_id=agency_id,
            username=f"imp_group_{suffix}",
            password="StrongTestPass_123!",
        )
        conn.commit()

        csv_path = _write_client_csv(
            path=tmp_path / f"client_review_grouped_{suffix}.csv",
            phone=phone,
            family_name=f"{corrected_name}123",
            remarks="needs-review",
        )
        job = _make_job(user_id=user_id, agency_id=agency_id, csv_path=csv_path)
        _run_import_job(
            monkeypatch=monkeypatch,
            csv_path=csv_path,
            job=job,
            agency_id=agency_id,
            user_id=user_id,
        )
        job.refresh_from_db()

        assert job.stage == ImportJob.Stage.REVIEW
        review_item = ImportReviewItem.objects.select_related("group").filter(job=job).first()
        assert review_item is not None
        user = get_user_model().objects.get(id=user_id)
        request = APIRequestFactory().post(
            f"/api/v1/import/{job.id}/review/submit/",
            {
                "item_decisions": {
                    str(int(review_item.id)): {
                        "corrections": {
                            "family_name": corrected_name,
                            "phone": phone,
                        }
                    }
                },
                "group_decisions": {
                    str(review_item.group.group_key): {
                        "action": "create_new",
                        "entity_type": "client",
                    }
                },
                "skip_item_ids": [],
                "bulk_operations": [],
            },
            format="json",
        )
        force_authenticate(request, user=user)
        monkeypatch.setattr(
            "server.api.views_import_review.enqueue_import_task",
            lambda _task, **_kwargs: SimpleNamespace(id="review-submit-task-grouped"),
        )
        monkeypatch.setattr(
            "server.api.views_import_review.register_task", lambda *args, **kwargs: None
        )

        response = import_review_submit(request, str(job.id))
        assert response.status_code == 202

        with use_security_context(agency_id=agency_id, is_superuser=False):
            task_result = run_review_submit_task(
                session_id=str(job.id),
                actor_user_id=user_id,
                agency_id=agency_id,
                correlation_id="review-group-corrections",
                task_id=str(response.data["task_id"]),
            )

        job.refresh_from_db()
        summary = dict(job.result_summary or {})
        with use_security_context(agency_id=agency_id, is_superuser=False):
            persisted_clients = list(
                clients_service.fetch_clients(
                    limit=20,
                    offset=0,
                    search="",
                    status=None,
                    include_deleted=True,
                )
            )
        persisted_client = next(
            (
                client
                for client in persisted_clients
                if str(getattr(client, "family_name", "") or "") == corrected_name
                and str(getattr(client, "phone", "") or "") == phone
            ),
            None,
        )

        assert task_result["status"] == ImportJob.Status.COMPLETED
        assert job.status == ImportJob.Status.COMPLETED
        assert job.stage == ImportJob.Stage.EXECUTION
        assert list(job.review_rows or []) == []
        assert int(summary.get("created_count", 0) or 0) == 1
        assert persisted_client is not None
    finally:
        if agency_id:
            conn.execute("DELETE FROM match_rebuild_state WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM imports_importrowaudit WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM imports_importjob WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
        if user_id:
            conn.execute(
                "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
                (user_id,),
            )
            conn.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        if agency_id:
            conn.execute("DELETE FROM audit_logs WHERE agency_id = %s", (agency_id,))
            conn.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        conn.commit()
        conn.close()
