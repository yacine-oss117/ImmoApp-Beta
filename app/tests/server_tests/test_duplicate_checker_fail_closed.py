from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from server.api.tasks_import_failures import friendly_import_failure_message  # noqa: E402
from server.services.duplicate_checker import (  # noqa: E402
    DatabaseDuplicateChecker,
    DuplicateCheckUnavailableError,
)
from server.services.import_execution_state import friendly_import_error_message  # noqa: E402
from server.services.import_plan_single_flow import plan_single_entity_import  # noqa: E402
from server.services.import_types import (  # noqa: E402
    ImportResult,
    PreparedImportArtifact,
    ReviewRowBuffer,
)


class _ExplodingSession:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def execute(self, _query: str, _params: object = None) -> object:
        raise self._exc


class _FakeSessionContext:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def __enter__(self) -> _ExplodingSession:
        return _ExplodingSession(self._exc)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        _ = (exc_type, exc, tb)
        return False


class _FakeUow:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def session(self, **_kwargs: object) -> _FakeSessionContext:
        return _FakeSessionContext(self._exc)


def test_lookup_phones_raises_duplicate_check_unavailable_on_query_failure() -> None:
    checker = DatabaseDuplicateChecker()

    with pytest.raises(DuplicateCheckUnavailableError):
        checker._lookup_phones(
            ["0555123456"],
            "client",
            session=_ExplodingSession(psycopg.OperationalError("db offline")),
            agency_id=7,
        )


def test_filter_batch_does_not_fail_open_when_duplicate_check_fails() -> None:
    checker = DatabaseDuplicateChecker()

    with pytest.raises(DuplicateCheckUnavailableError):
        checker.filter_batch(
            [{"phone": "0555123456", "family_name": "Failure Path"}],
            "client",
            _ExplodingSession(psycopg.OperationalError("db offline")),
            agency_id=7,
        )


def test_lookup_phones_does_not_normalize_programming_errors() -> None:
    checker = DatabaseDuplicateChecker()

    with pytest.raises(psycopg.ProgrammingError):
        checker._lookup_phones(
            ["0555123456"],
            "client",
            session=_ExplodingSession(psycopg.ProgrammingError("bad query shape")),
            agency_id=7,
        )


def test_plan_single_entity_import_propagates_duplicate_check_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared_entries_path = tmp_path / "prepared.jsonl"
    prepared_entries_path.write_text(
        json.dumps({"row": 1, "data": {"phone": "0555123456", "family_name": "Blocked"}}) + "\n",
        encoding="utf-8",
    )
    artifact = PreparedImportArtifact(
        bundle_mode="single_entity",
        total_rows=1,
        current_batch_size=100,
        chunks_total=1,
        spool_dir=tmp_path,
        prepared_entries_path=prepared_entries_path,
        entity_type="client",
    )
    job = SimpleNamespace(id="job-duplicate-failure", agency_id=7)
    monkeypatch.setattr(
        "server.services.import_plan_single_flow.get_uow",
        lambda: _FakeUow(psycopg.OperationalError("db offline")),
    )
    monkeypatch.setattr(
        "server.services.import_plan_single_flow.persist_job_progress",
        lambda **_kwargs: None,
    )

    with pytest.raises(DuplicateCheckUnavailableError):
        plan_single_entity_import(
            job=job,
            entity_type="client",
            duplicate_strategy="review",
            skip_review_rows=False,
            review_rows=ReviewRowBuffer(),
            errors=[],
            result=ImportResult(success=False),
            artifact=artifact,
        )


def test_duplicate_check_failure_uses_explicit_retryable_import_message() -> None:
    exc = DuplicateCheckUnavailableError("Duplicate verification is temporarily unavailable.")

    assert (
        friendly_import_error_message(exc)
        == "We couldn't verify duplicates right now. Please retry this import."
    )
    assert (
        friendly_import_failure_message(exc)
        == "We couldn't verify duplicates right now. Please retry this import."
    )
