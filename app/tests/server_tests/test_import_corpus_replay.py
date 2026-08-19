from __future__ import annotations

import csv
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from app.tests.server_tests._integration_auth_helpers import (
    admin_conn,
    create_agency,
    create_manager_user,
    ensure_django,
)

ensure_django()

from server.api.views_import_preview import import_preview  # noqa: E402
from server.imports.models import ImportJob  # noqa: E402
from server.pg.schema import ensure_schema  # noqa: E402

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "import_corpus"


def _load_fixtures(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [dict(item) for item in payload]
    return [dict(payload)]


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


def _write_fixture_csv(path: Path, headers: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})


def _assert_expected_subset(actual: object, expected: object) -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        for key, expected_value in expected.items():
            assert key in actual
            _assert_expected_subset(actual[key], expected_value)
        return
    if isinstance(expected, list):
        assert isinstance(actual, list)
        assert actual == expected
        return
    assert actual == expected


_CASES: list[tuple[Path, dict[str, Any]]] = [
    (fixture_path, fixture)
    for fixture_path in sorted(_FIXTURE_DIR.glob("*.json"))
    for fixture in _load_fixtures(fixture_path)
]
_CASE_IDS: list[str] = [
    f"{fixture_path.stem}:{fixture.get('name', fixture_path.stem)}"
    for fixture_path, fixture in _CASES
]


@pytest.mark.parametrize(
    ("fixture_path", "fixture"),
    _CASES,
    ids=_CASE_IDS,
)
def test_import_preview_corpus_replay(
    fixture_path: Path,
    fixture: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    assert len(_CASES) >= 20
    headers = [str(value) for value in fixture["headers"]]
    rows = list(fixture["rows"])
    job_fixture = dict(fixture["job"])
    preview_request = dict(fixture.get("preview_request") or {})
    expected = dict(fixture["expected"])
    expected_status_code = int(fixture.get("expected_status_code", 200) or 200)

    agency_id, user_id, user = _make_user_and_agency("IMPCRP")
    csv_path = tmp_path / str(fixture["filename"])
    _write_fixture_csv(csv_path, headers, rows)

    try:
        job = ImportJob.objects.create(
            user=user,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path=f"fixture://{fixture_path.stem}",
            status=str(job_fixture.get("status", ImportJob.Status.READY)),
            stage=str(job_fixture.get("stage", ImportJob.Stage.MAPPING)),
            detected_entity=str(job_fixture["detected_entity"]),
            detected_columns=list(job_fixture["detected_columns"]),
            column_mapping=dict(job_fixture["column_mapping"]),
            result_summary={"row_count": len(rows)},
            inference_summary=(
                dict(job_fixture["inference_summary"])
                if isinstance(job_fixture.get("inference_summary"), dict)
                else {"final_inference": dict(job_fixture["final_inference"])}
            ),
        )
        monkeypatch.setattr(
            "server.api.views_import_preview.download_to_temp",
            lambda *_args, **_kwargs: csv_path,
        )

        request = APIRequestFactory().post(
            "/api/v1/import/preview/",
            {
                "session_id": str(job.id),
                "entity_type": str(preview_request.get("entity_type", job.detected_entity)),
                "column_mapping": dict(job_fixture["column_mapping"]),
            },
            format="json",
        )
        force_authenticate(request, user=user)

        response = import_preview(request)

        assert response.status_code == expected_status_code
        _assert_expected_subset(dict(response.data), expected)
    finally:
        _cleanup_agency(agency_id=agency_id, user_id=user_id)
