from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.tests.server_tests._integration_auth_helpers import ensure_django

ensure_django()

from server.imports.models import ImportChunk  # noqa: E402
from server.services.import_distributed_execution import plan_chunk_phase  # noqa: E402
from server.services.import_plan_bundle_flow import plan_same_side_bundle_import  # noqa: E402
from server.services.import_types import ImportResult, PreparedImportArtifact  # noqa: E402


class _FakeSessionContext:
    def __init__(self, session: object) -> None:
        self._session = session

    def __enter__(self) -> object:
        return self._session

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        _ = (exc_type, exc, tb)
        return False


class _FakeUow:
    def __init__(self, session: object) -> None:
        self._session = session

    def session(self, **_kwargs: object) -> _FakeSessionContext:
        return _FakeSessionContext(self._session)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    return [dict(json.loads(line)) for line in text.splitlines()]


def test_bundle_planning_keeps_unresolved_child_rows_free_of_placeholder_parent_ids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_entries_path = tmp_path / "root.jsonl"
    child_entries_path = tmp_path / "child.jsonl"
    _write_jsonl(
        root_entries_path,
        [
            {
                "row": 1,
                "data": {"family_name": "Bundle Root", "phone": "0555001888"},
                "original": {"family_name": "Bundle Root", "phone": "0555001888"},
            }
        ],
    )
    _write_jsonl(
        child_entries_path,
        [
            {
                "row": 2,
                "data": {
                    "action": "buy",
                    "type": "apartment",
                    "wilaya": "16",
                    "budget_max": 1200000,
                    "surface_min": 80,
                    "remarks": "bundle-child",
                },
                "original": {
                    "action": "buy",
                    "type": "apartment",
                    "wilaya": "16",
                    "budget_max": 1200000,
                    "surface_min": 80,
                    "remarks": "bundle-child",
                },
                "root_anchor_keys": ["phone:0555001888"],
            }
        ],
    )

    artifact = PreparedImportArtifact(
        bundle_mode="same_side_bundle",
        total_rows=2,
        current_batch_size=10,
        chunks_total=1,
        spool_dir=tmp_path,
        root_entries_path=root_entries_path,
        child_entries_path=child_entries_path,
        root_entity="client",
        child_entity="demande",
        topology_side="client_side",
        root_row_count=1,
        child_row_count=1,
    )
    job = SimpleNamespace(
        id="job-bundle-placeholder", agency_id=7, detected_columns=[], column_mapping={}
    )

    monkeypatch.setattr(
        "server.services.import_plan_bundle_flow.get_uow",
        lambda: _FakeUow(object()),
    )
    monkeypatch.setattr(
        "server.services.import_plan_bundle_flow.load_agency_alias_memory",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_plan_bundle_flow.persist_job_progress",
        lambda **_kwargs: None,
    )

    planned_artifact = plan_same_side_bundle_import(
        job=job,
        user_id=11,
        duplicate_strategy="skip",
        skip_review_rows=False,
        review_rows=[],
        errors=[],
        result=ImportResult(success=False),
        artifact=artifact,
        apply_planning_recovery_fn=lambda **kwargs: dict(kwargs["row_data"]),
        blocked_duplicate_resolution_error_fn=lambda **_kwargs: {"row": 0, "errors": []},
        prefetch_root_match_cache_fn=lambda **_kwargs: None,
        prefetch_child_match_cache_fn=lambda **_kwargs: None,
        resolve_child_anchor_fn=lambda **_kwargs: 0,
        validate_row_fn=lambda row_data, _entity_type: (dict(row_data), []),
        resolve_existing_matches_fn=lambda **_kwargs: SimpleNamespace(
            candidate_matches=[],
            suggested_action="",
            suggested_existing_id=0,
        ),
    )

    planned_rows = _read_jsonl(planned_artifact.planned_child_entries_path)

    assert planned_rows == [
        {
            "row": 2,
            "data": {
                "action": "buy",
                "type": "apartment",
                "wilaya": "16",
                "budget_max": 1200000,
                "surface_min": 80,
                "remarks": "bundle-child",
                "created_by_id": 11,
            },
            "original": {
                "action": "buy",
                "type": "apartment",
                "wilaya": "16",
                "budget_max": 1200000,
                "surface_min": 80,
                "remarks": "bundle-child",
            },
            "anchor_id": 0,
            "anchor_key": "phone:0555001888",
        }
    ]


def test_distributed_child_planning_keeps_unresolved_rows_free_of_placeholder_parent_ids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepared_path = tmp_path / "prepared-child.jsonl"
    _write_jsonl(
        prepared_path,
        [
            {
                "row": 3,
                "data": {
                    "action": "buy",
                    "type": "apartment",
                    "wilaya": "16",
                    "budget_max": 1400000,
                    "surface_min": 90,
                    "remarks": "distributed-child",
                },
                "original": {
                    "action": "buy",
                    "type": "apartment",
                    "wilaya": "16",
                    "budget_max": 1400000,
                    "surface_min": 90,
                    "remarks": "distributed-child",
                },
                "root_anchor_keys": ["phone:0555002888"],
            }
        ],
    )

    captured: dict[str, list[dict[str, Any]]] = {}
    phase = SimpleNamespace(
        id=31,
        lease_token="lease-plan-child",
        chunk=SimpleNamespace(
            id=41,
            chunk_role=ImportChunk.Role.CHILD,
            entity_type="demande",
            job=SimpleNamespace(id="job-distributed-plan", agency_id=9),
        ),
    )

    monkeypatch.setattr(
        "server.services.import_distributed_execution.manifest_for_chunk",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.load_manifest_to_temp",
        lambda _manifest: prepared_path,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.get_uow",
        lambda: _FakeUow(object()),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.workflow_payload",
        lambda _job: {
            "topology_side": "client_side",
            "params": {"duplicate_strategy": "skip", "skip_review_rows": False},
        },
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._planned_root_plan_index",
        lambda _job: {
            "existing_anchor_map": {},
            "planned_root_anchor_keys": ["phone:0555002888"],
        },
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._require_phase_lease",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.is_phase_attempt_current",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.run_with_phase_attempt_fence",
        lambda **kwargs: kwargs["fn"](),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._is_cancel_requested",
        lambda _job: False,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.prefetch_root_match_cache",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.prefetch_child_match_cache",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.resolve_child_anchor",
        lambda **_kwargs: 0,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.validate_row",
        lambda row_data, _entity_type: (dict(row_data), []),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.persist_file_manifest",
        lambda **kwargs: captured.setdefault("planned", _read_jsonl(Path(kwargs["path"]))),
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution.persist_jsonl_manifest",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "server.services.import_distributed_execution._cleanup_temp_path",
        lambda _path: None,
    )

    result = plan_chunk_phase(phase=phase, user_id=13)

    assert result["planned_count"] == 1
    assert captured["planned"] == [
        {
            "row": 3,
            "data": {
                "action": "buy",
                "type": "apartment",
                "wilaya": "16",
                "budget_max": 1400000,
                "surface_min": 90,
                "remarks": "distributed-child",
                "created_by_id": 13,
            },
            "original": {
                "action": "buy",
                "type": "apartment",
                "wilaya": "16",
                "budget_max": 1400000,
                "surface_min": 90,
                "remarks": "distributed-child",
            },
            "anchor_id": 0,
            "anchor_key": "phone:0555002888",
        }
    ]
