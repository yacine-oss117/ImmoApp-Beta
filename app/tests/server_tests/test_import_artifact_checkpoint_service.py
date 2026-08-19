from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from app.tests.server_tests._integration_auth_helpers import ensure_django

pytest.importorskip("psycopg", reason="import checkpoint tests require server runtime")

ensure_django()

from server.services.import_artifact_checkpoint import (  # noqa: E402
    build_planned_artifact_fingerprint,
    clear_planned_artifact_checkpoint,
    load_planned_artifact_checkpoint,
    persist_planned_artifact_checkpoint,
)
from server.services.import_types import PreparedImportArtifact, ReviewRowBuffer  # noqa: E402


@dataclass
class _FakeJob:
    @dataclass
    class _User:
        role: str = "manager"

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_id: int = 41
    user: _User = field(default_factory=_User)
    source_path: str = "source-storage-id"
    column_mapping: dict[str, str] = field(
        default_factory=lambda: {"family_name": "Nom", "phone": "Telephone"}
    )
    inference_summary: dict[str, object] = field(
        default_factory=lambda: {"final_inference": {"bundle_mode": "single_entity"}}
    )
    result_summary: dict[str, object] = field(default_factory=dict)
    progress_detail: dict[str, object] = field(default_factory=dict)
    review_rows: list[dict[str, object]] = field(default_factory=list)
    save_calls: int = 0

    def save(self, update_fields: list[str] | None = None) -> None:
        _ = update_fields
        self.save_calls += 1


def test_planned_artifact_fingerprint_is_stable_for_equivalent_inputs() -> None:
    job = _FakeJob()
    fingerprint_a = build_planned_artifact_fingerprint(
        job=cast(Any, job),
        entity_type="client",
        duplicate_strategy="review",
        skip_rows=1,
        skip_review_rows=False,
        corrections={
            "2": {"phone": "0555000000", "family_name": "Alpha"},
            "1": {"family_name": "Beta"},
        },
    )
    fingerprint_b = build_planned_artifact_fingerprint(
        job=cast(Any, job),
        entity_type="client",
        duplicate_strategy="review",
        skip_rows=1,
        skip_review_rows=False,
        corrections={
            "1": {"family_name": "Beta"},
            "2": {"family_name": "Alpha", "phone": "0555000000"},
        },
    )
    assert fingerprint_a == fingerprint_b


def test_planned_artifact_checkpoint_roundtrip_restores_planned_files(tmp_path: Path) -> None:
    job = _FakeJob()
    planned_entries_path = tmp_path / "planned_entries.jsonl"
    planned_entries_path.write_text(
        '{"row":1,"data":{"family_name":"Alpha"}}\n',
        encoding="utf-8",
    )
    artifact = PreparedImportArtifact(
        bundle_mode="single_entity",
        total_rows=1,
        current_batch_size=250,
        chunks_total=1,
        spool_dir=tmp_path,
        planned_entries_path=planned_entries_path,
        entity_type="client",
    )
    review_rows = ReviewRowBuffer()
    review_rows.append(
        {
            "row": 7,
            "remarks": ["Needs review"],
            "candidate_matches": [
                {
                    "field_diff": {
                        "changed_mutable": [
                            {"field": "budget_max", "existing": Decimal("1200000.00")}
                        ]
                    }
                }
            ],
        }
    )
    review_rows.overflow_count = 3
    stored_objects: dict[str, bytes] = {}
    deleted_ids: list[str] = []

    def _store_fileobj(
        *,
        fileobj: Any,
        filename: str,
        content_type: str | None,
        purpose: str,
        user_id: int | None,
        role: str | None,
        created_ip: str | None,
    ) -> str:
        assert user_id == 41
        assert role == "manager"
        _ = (filename, content_type, purpose, created_ip)
        storage_id = f"storage-{len(stored_objects) + 1}"
        stored_objects[storage_id] = fileobj.read()
        return storage_id

    def _download_to_temp(storage_id: str, *, suffix: str | None = None) -> Path:
        target = tmp_path / f"{storage_id}{suffix or ''}"
        target.write_bytes(stored_objects[storage_id])
        return target

    def _mark_storage_deleted(*, storage_id: str) -> int:
        deleted_ids.append(storage_id)
        return 1

    fingerprint = build_planned_artifact_fingerprint(
        job=cast(Any, job),
        entity_type="client",
        duplicate_strategy="review",
        skip_rows=0,
        skip_review_rows=False,
        corrections=None,
    )
    persist_planned_artifact_checkpoint(
        job=cast(Any, job),
        artifact=artifact,
        fingerprint=fingerprint,
        review_rows=review_rows,
        errors=[{"row": 5, "errors": ["bad row"]}],
        skipped_count=4,
        error_count=1,
        store_fileobj_fn=_store_fileobj,
    )

    restored = load_planned_artifact_checkpoint(
        job=cast(Any, job),
        fingerprint=fingerprint,
        download_to_temp_fn=_download_to_temp,
    )

    assert restored is not None
    assert restored.artifact.planned_entries_path is not None
    assert restored.artifact.planned_entries_path.read_text(encoding="utf-8") == (
        planned_entries_path.read_text(encoding="utf-8")
    )
    assert restored.artifact.entity_type == "client"
    assert restored.skipped_count == 4
    assert restored.error_count == 1
    assert restored.review_overflow_count == 3
    assert list(restored.review_rows) == [
        {
            "row": 7,
            "remarks": ["Needs review"],
            "candidate_matches": [
                {"field_diff": {"changed_mutable": [{"field": "budget_max", "existing": 1200000}]}}
            ],
        }
    ]
    assert restored.errors == [{"row": 5, "errors": ["bad row"]}]
    assert job.progress_detail["resume_available"] is True

    clear_planned_artifact_checkpoint(
        job=cast(Any, job),
        mark_storage_deleted_fn=_mark_storage_deleted,
    )

    assert deleted_ids == ["storage-1", "storage-2"]
    assert "planned_artifact_checkpoint" not in job.result_summary
    assert "resume_available" not in job.progress_detail


def test_planned_artifact_checkpoint_skips_zero_byte_artifacts(tmp_path: Path) -> None:
    job = _FakeJob()
    empty_root_path = tmp_path / "planned_root_entries.jsonl"
    empty_root_path.write_text("", encoding="utf-8")
    child_entries_path = tmp_path / "planned_child_entries.jsonl"
    child_entries_path.write_text('{"row":2,"data":{"client_id":1}}\n', encoding="utf-8")
    artifact = PreparedImportArtifact(
        bundle_mode="same_side_bundle",
        total_rows=1,
        current_batch_size=250,
        chunks_total=1,
        spool_dir=tmp_path,
        planned_root_entries_path=empty_root_path,
        planned_child_entries_path=child_entries_path,
        root_entity="client",
        child_entity="demande",
    )
    stored_filenames: list[str] = []

    def _store_fileobj(
        *,
        fileobj: Any,
        filename: str,
        content_type: str | None,
        purpose: str,
        user_id: int | None,
        role: str | None,
        created_ip: str | None,
    ) -> str:
        _ = (fileobj.read(), content_type, purpose, user_id, role, created_ip)
        stored_filenames.append(filename)
        return f"storage-{len(stored_filenames)}"

    fingerprint = build_planned_artifact_fingerprint(
        job=cast(Any, job),
        entity_type="client",
        duplicate_strategy="allow_all",
        skip_rows=0,
        skip_review_rows=False,
        corrections=None,
    )
    persist_planned_artifact_checkpoint(
        job=cast(Any, job),
        artifact=artifact,
        fingerprint=fingerprint,
        review_rows=ReviewRowBuffer(),
        errors=[],
        skipped_count=0,
        error_count=0,
        store_fileobj_fn=_store_fileobj,
    )

    assert stored_filenames == [f"import-job-{job.id}-planned_child_entries_path.jsonl"]


def test_planned_artifact_checkpoint_restores_child_entries_and_review_rows_independently(
    tmp_path: Path,
) -> None:
    job = _FakeJob()
    planned_root_path = tmp_path / "planned_root_entries.jsonl"
    planned_root_path.write_text('{"row":1,"data":{"family_name":"Root"}}\n', encoding="utf-8")
    planned_child_path = tmp_path / "planned_child_entries.jsonl"
    planned_child_path.write_text(
        '{"row":2,"data":{"client_id":1,"remarks":"child"}}\n', encoding="utf-8"
    )
    artifact = PreparedImportArtifact(
        bundle_mode="same_side_bundle",
        total_rows=2,
        current_batch_size=250,
        chunks_total=1,
        spool_dir=tmp_path,
        planned_root_entries_path=planned_root_path,
        planned_child_entries_path=planned_child_path,
        root_entity="client",
        child_entity="demande",
    )
    review_rows = ReviewRowBuffer()
    review_rows.append(
        {
            "row": 9,
            "entity_type": "client",
            "remarks": ["Needs duplicate review"],
        }
    )
    stored_objects: dict[str, bytes] = {}

    def _store_fileobj(
        *,
        fileobj: Any,
        filename: str,
        content_type: str | None,
        purpose: str,
        user_id: int | None,
        role: str | None,
        created_ip: str | None,
    ) -> str:
        _ = (filename, content_type, purpose, user_id, role, created_ip)
        storage_id = f"storage-{len(stored_objects) + 1}"
        stored_objects[storage_id] = fileobj.read()
        return storage_id

    def _download_to_temp(storage_id: str, *, suffix: str | None = None) -> Path:
        target = tmp_path / f"{storage_id}{suffix or ''}"
        target.write_bytes(stored_objects[storage_id])
        return target

    fingerprint = build_planned_artifact_fingerprint(
        job=cast(Any, job),
        entity_type="client",
        duplicate_strategy="review",
        skip_rows=0,
        skip_review_rows=False,
        corrections=None,
    )
    persist_planned_artifact_checkpoint(
        job=cast(Any, job),
        artifact=artifact,
        fingerprint=fingerprint,
        review_rows=review_rows,
        errors=[],
        skipped_count=0,
        error_count=0,
        store_fileobj_fn=_store_fileobj,
    )

    restored = load_planned_artifact_checkpoint(
        job=cast(Any, job),
        fingerprint=fingerprint,
        download_to_temp_fn=_download_to_temp,
    )

    assert restored is not None
    assert restored.artifact.planned_child_entries_path is not None
    assert restored.artifact.planned_child_entries_path.read_text(encoding="utf-8") == (
        planned_child_path.read_text(encoding="utf-8")
    )
    assert list(restored.review_rows) == [
        {
            "row": 9,
            "entity_type": "client",
            "remarks": ["Needs duplicate review"],
        }
    ]
