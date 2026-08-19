from __future__ import annotations

import csv
import itertools
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

pytest.importorskip("psycopg", reason="distributed importer tests require Postgres")

from app.tests.server_tests._integration_auth_helpers import (  # noqa: E402
    admin_conn,
    create_agency,
    create_manager_user,
    ensure_django,
)

ensure_django()

from core.importer.detection.column_detector import ColumnDetector  # noqa: E402
from server.api import tasks_import  # noqa: E402
from server.imports.models import (  # noqa: E402
    ImportArtifactManifest,
    ImportChunk,
    ImportChunkPhase,
    ImportJob,
)
from server.pg.schema import ensure_schema  # noqa: E402
from server.pg.uow import get_uow, use_security_context  # noqa: E402
from server.services.import_chunk_workflow import (  # noqa: E402
    advance_workflow,
    job_manifest,
    load_jsonl_manifest_rows,
    workflow_payload,
)

_IMPORT_WORKFLOW_MIGRATION = "0009_import_fk_cascade_contract"
_import_tables_ready = False


def _ensure_import_tables() -> None:
    global _import_tables_ready
    if _import_tables_ready:
        return
    try:
        call_command(
            "migrate",
            "imports",
            _IMPORT_WORKFLOW_MIGRATION,
            verbosity=0,
            interactive=False,
        )
        _import_tables_ready = True
        return
    except Exception:
        pass

    conn = admin_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS imports_importchunk (
                id BIGSERIAL PRIMARY KEY,
                job_id UUID NOT NULL REFERENCES imports_importjob(id) ON DELETE CASCADE,
                agency_id BIGINT NOT NULL REFERENCES accounts_agency(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL,
                chunk_role VARCHAR(20) NOT NULL,
                entity_type VARCHAR(50) NOT NULL DEFAULT '',
                row_start INTEGER NOT NULL DEFAULT 0,
                row_end INTEGER NOT NULL DEFAULT 0,
                row_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_import_chunk_job_ord_role "
            "ON imports_importchunk(job_id, ordinal, chunk_role)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_imp_chunk_job_role "
            "ON imports_importchunk(job_id, chunk_role)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_imp_chunk_agency_created "
            "ON imports_importchunk(agency_id, created_at)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS imports_importchunkphase (
                id BIGSERIAL PRIMARY KEY,
                chunk_id BIGINT NOT NULL REFERENCES imports_importchunk(id) ON DELETE CASCADE,
                phase VARCHAR(20) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                task_id VARCHAR(255) NOT NULL DEFAULT '',
                lease_token VARCHAR(64) NOT NULL DEFAULT '',
                heartbeat_at TIMESTAMPTZ NULL,
                lease_expires_at TIMESTAMPTZ NULL,
                started_at TIMESTAMPTZ NULL,
                finished_at TIMESTAMPTZ NULL,
                error_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                metrics_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_import_chunk_phase "
            "ON imports_importchunkphase(chunk_id, phase)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_imp_chunk_phase_status "
            "ON imports_importchunkphase(status, phase)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_imp_cphase_chunk_stat "
            "ON imports_importchunkphase(chunk_id, status)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS imports_importartifactmanifest (
                id BIGSERIAL PRIMARY KEY,
                job_id UUID NOT NULL REFERENCES imports_importjob(id) ON DELETE CASCADE,
                agency_id BIGINT NOT NULL REFERENCES accounts_agency(id) ON DELETE CASCADE,
                chunk_id BIGINT NULL REFERENCES imports_importchunk(id) ON DELETE CASCADE,
                phase VARCHAR(20) NOT NULL,
                artifact_kind VARCHAR(50) NOT NULL,
                storage_id VARCHAR(255) NOT NULL,
                checksum VARCHAR(64) NOT NULL DEFAULT '',
                row_count INTEGER NOT NULL DEFAULT 0,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS imports_importworkflowstate (
                id BIGSERIAL PRIMARY KEY,
                job_id UUID NOT NULL UNIQUE REFERENCES imports_importjob(id) ON DELETE CASCADE,
                run_id VARCHAR(64) NOT NULL DEFAULT '',
                status VARCHAR(20) NOT NULL DEFAULT '',
                fingerprint VARCHAR(128) NOT NULL DEFAULT '',
                cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
                prepare_completed BOOLEAN NOT NULL DEFAULT FALSE,
                finalize_queued BOOLEAN NOT NULL DEFAULT FALSE,
                finalized BOOLEAN NOT NULL DEFAULT FALSE,
                queue_position INTEGER NOT NULL DEFAULT 0,
                queued_at TIMESTAMPTZ NULL,
                execution_profile VARCHAR(20) NOT NULL DEFAULT '',
                admission_mode VARCHAR(20) NOT NULL DEFAULT '',
                pressure_reason VARCHAR(64) NOT NULL DEFAULT '',
                bundle_mode VARCHAR(32) NOT NULL DEFAULT '',
                topology_side VARCHAR(32) NOT NULL DEFAULT '',
                params JSONB NOT NULL DEFAULT '{}'::jsonb,
                prepare_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
                load_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                root_plan_index_ready BOOLEAN NOT NULL DEFAULT FALSE,
                root_plan_index_manifest_id BIGINT NOT NULL DEFAULT 0,
                root_plan_index_checksum VARCHAR(64) NOT NULL DEFAULT '',
                root_plan_index_key_count INTEGER NOT NULL DEFAULT 0,
                root_load_anchor_map_ready BOOLEAN NOT NULL DEFAULT FALSE,
                root_load_anchor_map_manifest_id BIGINT NOT NULL DEFAULT 0,
                root_load_anchor_map_checksum VARCHAR(64) NOT NULL DEFAULT '',
                root_load_anchor_map_key_count INTEGER NOT NULL DEFAULT 0,
                started_at TIMESTAMPTZ NULL,
                finished_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_imp_art_job_phase "
            "ON imports_importartifactmanifest(job_id, phase)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_imp_art_chunk_kind "
            "ON imports_importartifactmanifest(chunk_id, artifact_kind)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_imp_art_agency_created "
            "ON imports_importartifactmanifest(agency_id, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_imp_wf_status_queue "
            "ON imports_importworkflowstate(status, queued_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_imp_wf_exec_profile "
            "ON imports_importworkflowstate(execution_profile)"
        )
        conn.commit()
        recorder = MigrationRecorder(connection)
        recorder.record_applied("imports", _IMPORT_WORKFLOW_MIGRATION)
        _import_tables_ready = True
    finally:
        conn.close()


def _detected_columns(headers: list[str]) -> list[dict[str, object]]:
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


def _write_same_side_bundle_csv(path: Path) -> Path:
    headers = [
        "family_name",
        "phone",
        "status",
        "action",
        "type",
        "wilaya",
        "locations",
        "budget_min",
        "budget_max",
        "surface_min",
        "surface_max",
        "beds_min",
        "remarks",
    ]
    rows = [
        ["Bundle Client A", "0555001001", "active", "", "", "", "", "", "", "", "", "", "CLIENT_A"],
        [
            "Bundle Client A",
            "0555001001",
            "",
            "buy",
            "apartment",
            "16",
            "Hydra",
            "1200000",
            "2400000",
            "60",
            "130",
            "2",
            "DEM_A_OK",
        ],
        ["Bundle Client B", "0555001002", "active", "", "", "", "", "", "", "", "", "", "CLIENT_B"],
        [
            "Bundle Client B",
            "0555001002",
            "",
            "buy",
            "apartment",
            "16",
            "Ben Aknoun",
            "",
            "2400000",
            "70",
            "150",
            "3",
            "DEM_B_REVIEW_BUDGET",
        ],
        [
            "Bundle Client A",
            "0555001001",
            "active",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "CLIENT_A_DUP",
        ],
        [
            "Bundle Client C",
            "0555001003",
            "",
            "buy",
            "apartment",
            "16",
            "Unknown-Sector-XYZ",
            "1500000",
            "2600000",
            "70",
            "150",
            "2",
            "DEM_C_REVIEW_LOC",
        ],
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def _write_child_only_csv(
    *,
    path: Path,
    entity_type: str,
    anchor_ids: list[int],
) -> Path:
    if entity_type == "demande":
        headers = [
            "client_id",
            "action",
            "type",
            "wilaya",
            "locations",
            "budget_min",
            "budget_max",
            "surface_min",
            "surface_max",
            "beds_min",
            "remarks",
        ]
        rows = []
        for idx in range(6):
            anchor_id = anchor_ids[idx % len(anchor_ids)]
            rows.append(
                [
                    anchor_id,
                    "buy",
                    "apartment",
                    "16",
                    "Hydra" if idx != 4 else "Unknown Sector X",
                    "1200000" if idx != 3 else "",
                    "2400000",
                    "60",
                    "130",
                    "2",
                    f"DEM_CHILD_{idx}",
                ]
            )
    else:
        headers = [
            "listing_id",
            "action",
            "type",
            "wilaya",
            "location",
            "budget",
            "surface",
            "beds",
            "floor",
            "remarks",
        ]
        rows = []
        for idx in range(6):
            anchor_id = anchor_ids[idx % len(anchor_ids)]
            rows.append(
                [
                    anchor_id,
                    "sell",
                    "apartment",
                    "16",
                    "Ben Aknoun" if idx != 4 else "Unknown District X",
                    "15000000" if idx != 3 else "",
                    "110",
                    "3",
                    "2",
                    f"OFF_CHILD_{idx}",
                ]
            )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def _insert_anchor_roots(
    *,
    conn: object,
    agency_id: int,
    entity_type: str,
    count: int,
    suffix: str,
) -> list[int]:
    inserted: list[int] = []
    for idx in range(count):
        digits = f"{idx + 1:04d}{suffix[:4]}"
        if entity_type == "demande":
            row = conn.execute(
                """
                INSERT INTO clients (agency_id, family_name, phone, status, created_at, updated_at)
                VALUES (%s, %s, %s, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
                """,
                (agency_id, f"Demand Client {suffix}-{idx}", f"0555{digits}"),
            ).fetchone()
        else:
            row = conn.execute(
                """
                INSERT INTO listings (agency_id, family_name, phone, status, created_at, updated_at)
                VALUES (%s, %s, %s, 'available', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
                """,
                (agency_id, f"Offer Listing {suffix}-{idx}", f"0666{digits}"),
            ).fetchone()
        assert row is not None
        inserted.append(int(row["id"]))
    return inserted


def _install_in_memory_artifact_store(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import server.services.import_chunk_workflow as workflow_mod
    import server.services.import_distributed_execution as distributed_mod

    store: dict[str, bytes] = {}
    counter = itertools.count(1)

    def _persist_bytes_manifest(
        *,
        job: ImportJob,
        phase: str,
        artifact_kind: str,
        payload: bytes,
        chunk: ImportChunk | None,
        row_count: int,
        metadata: dict[str, object] | None,
    ) -> ImportArtifactManifest | None:
        if not payload:
            return None
        storage_id = f"mem-artifact-{next(counter)}"
        store[storage_id] = payload
        ImportArtifactManifest.objects.filter(
            job=job,
            chunk=chunk,
            phase=phase,
            artifact_kind=artifact_kind,
        ).delete()
        return ImportArtifactManifest.objects.create(
            job=job,
            agency_id=int(job.agency_id),
            chunk=chunk,
            phase=phase,
            artifact_kind=artifact_kind,
            storage_id=storage_id,
            checksum="",
            row_count=int(row_count),
            metadata=dict(metadata or {}),
        )

    def _persist_file_manifest(
        *,
        job: ImportJob,
        phase: str,
        artifact_kind: str,
        path: Path,
        chunk: ImportChunk | None = None,
        row_count: int = 0,
        metadata: dict[str, object] | None = None,
        **_: object,
    ) -> ImportArtifactManifest | None:
        if not path.exists() or path.stat().st_size <= 0:
            return None
        return _persist_bytes_manifest(
            job=job,
            phase=phase,
            artifact_kind=artifact_kind,
            payload=path.read_bytes(),
            chunk=chunk,
            row_count=row_count,
            metadata=metadata,
        )

    def _persist_jsonl_manifest(
        *,
        job: ImportJob,
        phase: str,
        artifact_kind: str,
        rows: list[dict[str, object]],
        chunk: ImportChunk | None = None,
        metadata: dict[str, object] | None = None,
        **_: object,
    ) -> ImportArtifactManifest | None:
        payload = b"".join(
            (json.dumps(dict(row), ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
            for row in rows
        )
        return _persist_bytes_manifest(
            job=job,
            phase=phase,
            artifact_kind=artifact_kind,
            payload=payload,
            chunk=chunk,
            row_count=len(rows),
            metadata=metadata,
        )

    def _load_manifest_to_temp(
        manifest: ImportArtifactManifest,
        *,
        suffix: str | None = ".jsonl",
        **_: object,
    ) -> Path:
        target = tmp_path / f"{manifest.storage_id}{suffix or ''}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(store[str(manifest.storage_id)])
        return target

    monkeypatch.setattr(workflow_mod, "persist_file_manifest", _persist_file_manifest)
    monkeypatch.setattr(
        workflow_mod,
        "persist_json_manifest",
        lambda **kwargs: _persist_bytes_manifest(
            job=kwargs["job"],
            phase=str(kwargs["phase"]),
            artifact_kind=str(kwargs["artifact_kind"]),
            payload=json.dumps(
                dict(kwargs.get("payload") or {}),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            chunk=kwargs.get("chunk"),
            row_count=int((kwargs.get("metadata") or {}).get("row_count", 0) or 0),
            metadata=dict(kwargs.get("metadata") or {}),
        ),
    )
    monkeypatch.setattr(workflow_mod, "persist_jsonl_manifest", _persist_jsonl_manifest)
    monkeypatch.setattr(workflow_mod, "load_manifest_to_temp", _load_manifest_to_temp)
    monkeypatch.setattr(distributed_mod, "persist_file_manifest", _persist_file_manifest)
    monkeypatch.setattr(distributed_mod, "persist_jsonl_manifest", _persist_jsonl_manifest)
    monkeypatch.setattr(distributed_mod, "load_manifest_to_temp", _load_manifest_to_temp)


def _install_inline_task_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    task_counter = itertools.count(1)

    def _inline(task: object, **kwargs: object) -> SimpleNamespace:
        task.run(**kwargs)
        return SimpleNamespace(id=f"sync-{next(task_counter)}")

    monkeypatch.setattr(
        tasks_import,
        "enqueue_import_task",
        lambda task, **kwargs: _inline(task, **kwargs),
    )


def test_advance_workflow_same_side_bundle_transitions_root_then_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    _install_in_memory_artifact_store(monkeypatch=monkeypatch, tmp_path=tmp_path)
    suffix = uuid.uuid4().hex[:8]
    conn = admin_conn()
    agency_id = create_agency(conn, f"IMPDW{suffix}", f"Import DW {suffix}")
    user_id = create_manager_user(
        conn,
        agency_id=agency_id,
        username=f"imp_dw_{suffix}",
        password="StrongTestPass_123!",
    )
    conn.commit()
    conn.close()

    try:
        job = ImportJob.objects.create(
            user_id=user_id,
            agency_id=agency_id,
            filename="bundle.csv",
            file_type="csv",
            source_path="fixture://bundle",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            result_summary={
                "row_count": 6,
                "workflow": {
                    "prepare_completed": True,
                    "bundle_mode": "same_side_bundle",
                    "root_plan_index_ready": False,
                    "root_load_anchor_map_ready": False,
                    "finalize_queued": False,
                    "prepare_counts": {"review_count": 0, "error_count": 0},
                },
            },
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                }
            },
        )
        root_chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.ROOT,
            entity_type="client",
            row_start=1,
            row_end=2,
            row_count=2,
        )
        child_chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.CHILD,
            entity_type="demande",
            row_start=3,
            row_end=4,
            row_count=2,
        )
        root_plan = ImportChunkPhase.objects.create(
            chunk=root_chunk,
            phase=ImportChunkPhase.Phase.PLAN,
            status=ImportChunkPhase.Status.PENDING,
        )
        child_plan = ImportChunkPhase.objects.create(
            chunk=child_chunk,
            phase=ImportChunkPhase.Phase.PLAN,
            status=ImportChunkPhase.Status.BLOCKED,
        )
        root_load = ImportChunkPhase.objects.create(
            chunk=root_chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.BLOCKED,
        )
        child_load = ImportChunkPhase.objects.create(
            chunk=child_chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.BLOCKED,
        )

        dispatch = advance_workflow(str(job.id))
        assert dispatch.plan_phase_ids == [root_plan.id]
        child_plan.refresh_from_db()
        root_load.refresh_from_db()
        assert child_plan.status == ImportChunkPhase.Status.BLOCKED
        assert root_load.status == ImportChunkPhase.Status.BLOCKED

        root_plan.status = ImportChunkPhase.Status.COMPLETED
        root_plan.metrics_payload = {
            "existing_anchor_map": {"phone:0555001001": 44},
            "planned_root_anchor_keys": ["phone:0555001001", "name:bundle client a"],
        }
        root_plan.save(update_fields=["status", "metrics_payload"])

        dispatch = advance_workflow(str(job.id))
        assert child_plan.id in dispatch.plan_phase_ids
        assert root_load.id in dispatch.load_phase_ids
        child_plan.refresh_from_db()
        root_load.refresh_from_db()
        job.refresh_from_db()
        assert child_plan.status == ImportChunkPhase.Status.QUEUED
        assert root_load.status == ImportChunkPhase.Status.QUEUED
        assert workflow_payload(job)["root_plan_index_ready"] is True

        child_plan.status = ImportChunkPhase.Status.COMPLETED
        child_plan.save(update_fields=["status"])
        root_load.status = ImportChunkPhase.Status.COMPLETED
        root_load.metrics_payload = {"created_anchor_map": {"phone:0555001001": 101}}
        root_load.save(update_fields=["status", "metrics_payload"])

        dispatch = advance_workflow(str(job.id))
        assert child_load.id in dispatch.load_phase_ids
        child_load.refresh_from_db()
        job.refresh_from_db()
        assert child_load.status == ImportChunkPhase.Status.QUEUED
        assert workflow_payload(job)["root_load_anchor_map_ready"] is True

        child_load.status = ImportChunkPhase.Status.COMPLETED
        child_load.save(update_fields=["status"])
        dispatch = advance_workflow(str(job.id))
        assert dispatch.finalize_job is True
    finally:
        ImportJob.objects.filter(agency_id=agency_id).delete()
        cleanup = admin_conn()
        cleanup.execute(
            "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
            (user_id,),
        )
        cleanup.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        cleanup.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        cleanup.commit()
        cleanup.close()


def test_advance_workflow_same_side_bundle_without_root_chunks_unblocks_child_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    _install_in_memory_artifact_store(monkeypatch=monkeypatch, tmp_path=tmp_path)
    suffix = uuid.uuid4().hex[:8]
    conn = admin_conn()
    agency_id = create_agency(conn, f"IMPDZ{suffix}", f"Import DZ {suffix}")
    user_id = create_manager_user(
        conn,
        agency_id=agency_id,
        username=f"imp_dz_{suffix}",
        password="StrongTestPass_123!",
    )
    conn.commit()
    conn.close()

    try:
        job = ImportJob.objects.create(
            user_id=user_id,
            agency_id=agency_id,
            filename="child-only-bundle.csv",
            file_type="csv",
            source_path="fixture://child-only-bundle",
            status=ImportJob.Status.RUNNING,
            stage=ImportJob.Stage.EXECUTION,
            detected_entity="client",
            result_summary={
                "row_count": 3,
                "workflow": {
                    "prepare_completed": True,
                    "bundle_mode": "same_side_bundle",
                    "root_plan_index_ready": False,
                    "root_load_anchor_map_ready": False,
                    "finalize_queued": False,
                    "prepare_counts": {"review_count": 0, "error_count": 0},
                },
            },
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                }
            },
        )
        child_chunk = ImportChunk.objects.create(
            job=job,
            agency_id=agency_id,
            ordinal=1,
            chunk_role=ImportChunk.Role.CHILD,
            entity_type="demande",
            row_start=1,
            row_end=3,
            row_count=3,
        )
        child_plan = ImportChunkPhase.objects.create(
            chunk=child_chunk,
            phase=ImportChunkPhase.Phase.PLAN,
            status=ImportChunkPhase.Status.BLOCKED,
        )
        child_load = ImportChunkPhase.objects.create(
            chunk=child_chunk,
            phase=ImportChunkPhase.Phase.LOAD,
            status=ImportChunkPhase.Status.BLOCKED,
        )

        dispatch = advance_workflow(str(job.id))
        child_plan.refresh_from_db()
        child_load.refresh_from_db()
        job.refresh_from_db()
        workflow = workflow_payload(job)
        assert child_plan.id in dispatch.plan_phase_ids
        assert child_plan.status == ImportChunkPhase.Status.QUEUED
        assert child_load.status == ImportChunkPhase.Status.BLOCKED
        assert workflow["root_plan_index_ready"] is True
        assert int(workflow["root_plan_index_manifest_id"]) == 0
        root_plan_manifest = job_manifest(
            job=job,
            phase=ImportArtifactManifest.Phase.PLAN,
            artifact_kind="root_plan_index",
        )
        assert root_plan_manifest is None

        child_plan.status = ImportChunkPhase.Status.COMPLETED
        child_plan.save(update_fields=["status"])
        dispatch = advance_workflow(str(job.id))
        child_load.refresh_from_db()
        job.refresh_from_db()
        workflow = workflow_payload(job)
        assert child_load.id in dispatch.load_phase_ids
        assert child_load.status == ImportChunkPhase.Status.QUEUED
        assert workflow["root_load_anchor_map_ready"] is True
        assert int(workflow["root_load_anchor_map_manifest_id"]) == 0
        root_load_manifest = job_manifest(
            job=job,
            phase=ImportArtifactManifest.Phase.LOAD,
            artifact_kind="root_load_anchor_map",
        )
        assert root_load_manifest is None
    finally:
        ImportJob.objects.filter(agency_id=agency_id).delete()
        cleanup = admin_conn()
        cleanup.execute(
            "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
            (user_id,),
        )
        cleanup.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        cleanup.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        cleanup.commit()
        cleanup.close()


def test_distributed_import_task_chain_handles_medium_chaotic_same_side_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    suffix = uuid.uuid4().hex[:8]
    csv_path = _write_same_side_bundle_csv(tmp_path / f"bundle_{suffix}.csv")
    headers = next(csv.reader(csv_path.open("r", encoding="utf-8", newline="")))
    detected_columns = _detected_columns([str(header) for header in headers])
    mapping = {str(header): str(header) for header in headers if header}

    conn = admin_conn()
    agency_id = create_agency(conn, f"IMPDF{suffix}", f"Import DF {suffix}")
    user_id = create_manager_user(
        conn,
        agency_id=agency_id,
        username=f"imp_df_{suffix}",
        password="StrongTestPass_123!",
    )
    conn.commit()
    conn.close()

    _install_in_memory_artifact_store(monkeypatch=monkeypatch, tmp_path=tmp_path)
    _install_inline_task_dispatch(monkeypatch)
    monkeypatch.setattr(tasks_import, "download_to_temp", lambda *_args, **_kwargs: csv_path)
    monkeypatch.setattr(tasks_import, "emit_import_notification", lambda **_kwargs: None)
    import server.services.import_finalize_service as finalize_service

    monkeypatch.setattr(finalize_service, "emit_import_notification", lambda **_kwargs: None)

    job = None
    try:
        job = ImportJob.objects.create(
            user_id=user_id,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://bundle-distributed",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=detected_columns,
            column_mapping=mapping,
            result_summary={"row_count": 6},
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                }
            },
        )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            result = tasks_import.import_execute_task.run(
                session_id=str(job.id),
                user_id=user_id,
                agency_id=agency_id,
                entity_type="client",
                column_mapping=mapping,
                skip_rows=0,
                duplicate_strategy="review",
                skip_review_rows=False,
                corrections=None,
                execution_cost=1,
                schema=None,
                correlation_id="test-distributed-import",
            )

        job.refresh_from_db()
        phase_snapshot = [
            (
                phase.chunk.chunk_role,
                phase.phase,
                phase.status,
                dict(phase.metrics_payload or {}),
            )
            for phase in ImportChunkPhase.objects.filter(chunk__job=job)
            .select_related("chunk")
            .order_by("chunk__chunk_role", "chunk__ordinal", "phase")
        ]
        chunk_snapshot = [
            (
                chunk.chunk_role,
                chunk.entity_type,
                chunk.ordinal,
                chunk.row_count,
            )
            for chunk in ImportChunk.objects.filter(job=job).order_by("chunk_role", "ordinal", "id")
        ]
        manifest_snapshot = [
            (
                manifest.chunk.chunk_role if manifest.chunk_id else "job",
                manifest.phase,
                manifest.artifact_kind,
                manifest.row_count,
            )
            for manifest in ImportArtifactManifest.objects.filter(job=job)
            .select_related("chunk")
            .order_by("chunk__chunk_role", "chunk__ordinal", "phase", "artifact_kind", "id")
        ]
        prepare_review_manifest = job_manifest(
            job=job,
            phase=ImportArtifactManifest.Phase.PREPARE,
            artifact_kind="review_rows",
        )
        prepare_review_rows = (
            load_jsonl_manifest_rows(prepare_review_manifest)
            if prepare_review_manifest is not None
            else []
        )
        prepare_review_snapshot = [
            {
                "row": row.get("row"),
                "entity_type": row.get("entity_type"),
                "remarks": row.get("remarks"),
                "review_fields": [
                    {
                        "field": field.get("field"),
                        "remark": field.get("remark"),
                    }
                    for field in row.get("review_fields", [])
                ],
            }
            for row in prepare_review_rows
        ]
        assert result["session_id"] == str(job.id)
        assert job.status in {ImportJob.Status.READY, ImportJob.Status.COMPLETED}, (
            job.status,
            workflow_payload(job),
            chunk_snapshot,
            phase_snapshot,
            manifest_snapshot,
            prepare_review_snapshot,
        )
        duplicate_routed_to_review = any(
            "Duplicate phone" in " ".join(row.get("remarks", []))
            or "Duplicate root key in this file" in " ".join(row.get("remarks", []))
            for row in job.review_rows or []
        )
        duplicate_routed_to_dead_letter = (
            int(
                ((job.result_summary or {}).get("dead_letter_summary", {}) or {}).get(
                    "auto_skipped", 0
                )
                or 0
            )
            > 0
            or int(
                ((job.result_summary or {}).get("dead_letter_summary", {}) or {}).get(
                    "blocking_discarded", 0
                )
                or 0
            )
            > 0
        )
        if job.status == ImportJob.Status.READY:
            assert job.stage == ImportJob.Stage.REVIEW, (
                job.stage,
                workflow_payload(job),
                chunk_snapshot,
                phase_snapshot,
                manifest_snapshot,
                prepare_review_snapshot,
            )
            assert len(job.review_rows or []) >= 2
        else:
            assert job.stage == ImportJob.Stage.EXECUTION, (
                job.stage,
                workflow_payload(job),
                chunk_snapshot,
                phase_snapshot,
                manifest_snapshot,
                prepare_review_snapshot,
            )
            assert list(job.review_rows or []) == []
        assert duplicate_routed_to_review or duplicate_routed_to_dead_letter
        if job.review_rows:
            assert any(
                "Unable to resolve a same-agency parent anchor." in " ".join(row.get("remarks", []))
                or "validation" in {field.get("field") for field in row.get("review_fields", [])}
                for row in job.review_rows or []
            )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().session(actor="test_distributed_import_verify") as session:
                client_count_row = session.execute(
                    "SELECT COUNT(*) AS c FROM clients WHERE agency_id = %s AND deleted_at IS NULL",
                    (agency_id,),
                ).fetchone()
                demande_count_row = session.execute(
                    "SELECT COUNT(*) AS c FROM demandes WHERE agency_id = %s AND deleted_at IS NULL",
                    (agency_id,),
                ).fetchone()
        assert client_count_row is not None and int(client_count_row["c"]) >= 2, (
            dict(client_count_row or {}),
            workflow_payload(job),
            [
                (
                    phase.chunk.chunk_role,
                    phase.phase,
                    phase.status,
                    dict(phase.metrics_payload or {}),
                )
                for phase in ImportChunkPhase.objects.filter(chunk__job=job)
                .select_related("chunk")
                .order_by("chunk__chunk_role", "chunk__ordinal", "phase")
            ],
            list(job.review_rows or []),
        )
        assert demande_count_row is not None and int(demande_count_row["c"]) >= 1, (
            dict(demande_count_row or {}),
            workflow_payload(job),
            [
                (
                    phase.chunk.chunk_role,
                    phase.phase,
                    phase.status,
                    dict(phase.metrics_payload or {}),
                )
                for phase in ImportChunkPhase.objects.filter(chunk__job=job)
                .select_related("chunk")
                .order_by("chunk__chunk_role", "chunk__ordinal", "phase")
            ],
            list(job.review_rows or []),
        )

        workflow = workflow_payload(job)
        assert workflow["prepare_completed"] is True
        assert workflow["root_plan_index_ready"] is True
        assert workflow["root_load_anchor_map_ready"] is True
        assert "root_plan_index" not in workflow
        assert "root_load_anchor_map" not in workflow
        assert int(workflow.get("root_plan_index_manifest_id", 0) or 0) > 0
        assert int(workflow.get("root_load_anchor_map_manifest_id", 0) or 0) > 0
        assert workflow["finalized"] is True
    finally:
        cleanup = admin_conn()
        cleanup.execute("DELETE FROM match_rebuild_state WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM demandes WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM imports_importjob WHERE agency_id = %s", (agency_id,))
        cleanup.execute(
            "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
            (user_id,),
        )
        cleanup.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        cleanup.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        cleanup.commit()
        cleanup.close()


def test_distributed_same_side_bundle_blocks_duplicate_root_when_review_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    suffix = uuid.uuid4().hex[:8]
    csv_path = tmp_path / f"bundle_skip_review_{suffix}.csv"
    headers = [
        "family_name",
        "phone",
        "status",
        "action",
        "type",
        "wilaya",
        "locations",
        "budget_min",
        "budget_max",
        "surface_min",
        "surface_max",
        "beds_min",
        "remarks",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(
            ["Existing Client", "0555999001", "active", "", "", "", "", "", "", "", "", "", ""]
        )
        writer.writerow(
            [
                "Existing Client",
                "0555999001",
                "",
                "buy",
                "apartment",
                "16",
                "Hydra",
                "1200000",
                "2400000",
                "60",
                "130",
                "2",
                "DEM_OK",
            ]
        )
    detected_columns = _detected_columns(headers)
    mapping = {str(header): str(header) for header in headers if header}

    conn = admin_conn()
    agency_id = create_agency(conn, f"IMPSR{suffix}", f"Import Skip Review {suffix}")
    user_id = create_manager_user(
        conn,
        agency_id=agency_id,
        username=f"imp_skip_{suffix}",
        password="StrongTestPass_123!",
    )
    conn.execute(
        """
        INSERT INTO clients (agency_id, family_name, phone, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, NOW(), NOW())
        """,
        (agency_id, "Existing Client", "0555999001", "active"),
    )
    conn.commit()
    conn.close()

    _install_in_memory_artifact_store(monkeypatch=monkeypatch, tmp_path=tmp_path)
    _install_inline_task_dispatch(monkeypatch)
    monkeypatch.setattr(tasks_import, "download_to_temp", lambda *_args, **_kwargs: csv_path)
    monkeypatch.setattr(tasks_import, "emit_import_notification", lambda **_kwargs: None)
    import server.services.import_finalize_service as finalize_service

    monkeypatch.setattr(finalize_service, "emit_import_notification", lambda **_kwargs: None)

    job = None
    try:
        job = ImportJob.objects.create(
            user_id=user_id,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path="fixture://bundle-skip-review-distributed",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity="client",
            detected_columns=detected_columns,
            column_mapping=mapping,
            result_summary={"row_count": 2},
            inference_summary={
                "final_inference": {
                    "bundle_mode": "same_side_bundle",
                    "topology_side_hint": "client_side",
                }
            },
        )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            result = tasks_import.import_execute_task.run(
                session_id=str(job.id),
                user_id=user_id,
                agency_id=agency_id,
                entity_type="client",
                column_mapping=mapping,
                skip_rows=0,
                duplicate_strategy="review",
                skip_review_rows=True,
                corrections=None,
                execution_cost=1,
                schema=None,
                correlation_id="test-distributed-skip-review-duplicate-root",
            )

        job.refresh_from_db()
        assert result["session_id"] == str(job.id)
        assert job.status == ImportJob.Status.COMPLETED
        assert job.stage == ImportJob.Stage.EXECUTION
        assert list(job.review_rows or []) == []
        assert int((job.result_summary or {}).get("error_count", 0) or 0) >= 1
        assert any(
            "needs review" in " ".join(item.get("errors", [])).lower()
            or "existing records in your agency" in " ".join(item.get("errors", [])).lower()
            for item in list((job.result_summary or {}).get("errors", []) or [])
            if isinstance(item, dict)
        )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().session(actor="test_distributed_skip_review_verify") as session:
                client_count_row = session.execute(
                    "SELECT COUNT(*) AS c FROM clients WHERE agency_id = %s AND deleted_at IS NULL",
                    (agency_id,),
                ).fetchone()
                demande_count_row = session.execute(
                    "SELECT COUNT(*) AS c FROM demandes WHERE agency_id = %s AND deleted_at IS NULL",
                    (agency_id,),
                ).fetchone()
        assert client_count_row is not None and int(client_count_row["c"]) == 1
        assert demande_count_row is not None and int(demande_count_row["c"]) == 1
    finally:
        cleanup = admin_conn()
        cleanup.execute("DELETE FROM match_rebuild_state WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM demandes WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM imports_importjob WHERE agency_id = %s", (agency_id,))
        cleanup.execute(
            "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
            (user_id,),
        )
        cleanup.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        cleanup.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        cleanup.commit()
        cleanup.close()


@pytest.mark.parametrize(
    ("entity_type", "topology_side", "table_name", "remarks_prefix"),
    [
        ("demande", "client_side", "demandes", "DEM_CHILD_"),
        ("offer", "listing_side", "offers", "OFF_CHILD_"),
    ],
)
def test_distributed_import_task_chain_handles_medium_chaotic_child_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entity_type: str,
    topology_side: str,
    table_name: str,
    remarks_prefix: str,
) -> None:
    ensure_schema()
    _ensure_import_tables()
    suffix = uuid.uuid4().hex[:8]

    conn = admin_conn()
    agency_id = create_agency(conn, f"IMPCO{suffix}", f"Import Child Only {suffix}")
    user_id = create_manager_user(
        conn,
        agency_id=agency_id,
        username=f"imp_child_{suffix}",
        password="StrongTestPass_123!",
    )
    anchor_ids = _insert_anchor_roots(
        conn=conn,
        agency_id=agency_id,
        entity_type=entity_type,
        count=2,
        suffix=suffix,
    )
    conn.commit()
    conn.close()

    csv_path = _write_child_only_csv(
        path=tmp_path / f"{entity_type}_{suffix}.csv",
        entity_type=entity_type,
        anchor_ids=anchor_ids,
    )
    headers = next(csv.reader(csv_path.open("r", encoding="utf-8", newline="")))
    detected_columns = _detected_columns([str(header) for header in headers])
    mapping = {str(header): str(header) for header in headers if header}

    _install_in_memory_artifact_store(monkeypatch=monkeypatch, tmp_path=tmp_path)
    _install_inline_task_dispatch(monkeypatch)
    monkeypatch.setattr(tasks_import, "download_to_temp", lambda *_args, **_kwargs: csv_path)
    monkeypatch.setattr(tasks_import, "emit_import_notification", lambda **_kwargs: None)
    import server.services.import_finalize_service as finalize_service

    monkeypatch.setattr(finalize_service, "emit_import_notification", lambda **_kwargs: None)

    try:
        job = ImportJob.objects.create(
            user_id=user_id,
            agency_id=agency_id,
            filename=csv_path.name,
            file_type="csv",
            source_path=f"fixture://{entity_type}-child-only",
            status=ImportJob.Status.READY,
            stage=ImportJob.Stage.MAPPING,
            detected_entity=entity_type,
            detected_columns=detected_columns,
            column_mapping=mapping,
            result_summary={"row_count": 6},
            inference_summary={
                "final_inference": {
                    "bundle_mode": "single_entity",
                    "topology_side_hint": topology_side,
                    "detected_entity": entity_type,
                    "entity_type_hint": entity_type,
                }
            },
        )

        with use_security_context(agency_id=agency_id, is_superuser=False):
            result = tasks_import.import_execute_task.run(
                session_id=str(job.id),
                user_id=user_id,
                agency_id=agency_id,
                entity_type=entity_type,
                column_mapping=mapping,
                skip_rows=0,
                duplicate_strategy="review",
                skip_review_rows=False,
                corrections=None,
                execution_cost=1,
                schema=None,
                correlation_id=f"test-child-only-{entity_type}",
            )

        job.refresh_from_db()
        assert result["session_id"] == str(job.id)
        assert result["status"] == "failed"
        assert job.status == ImportJob.Status.FAILED
        assert "supported" in str(result.get("error", "")).lower()
        with use_security_context(agency_id=agency_id, is_superuser=False):
            with get_uow().session(actor=f"test_distributed_{entity_type}_verify") as session:
                row = session.execute(
                    f"SELECT COUNT(*) AS c FROM {table_name} "
                    "WHERE agency_id = %s AND deleted_at IS NULL AND remarks LIKE %s",
                    (agency_id, f"{remarks_prefix}%"),
                ).fetchone()
        assert row is not None and int(row["c"]) == 0
        workflow = workflow_payload(job)
        assert workflow.get("prepare_completed", False) is False
    finally:
        cleanup = admin_conn()
        cleanup.execute("DELETE FROM match_rebuild_state WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM demandes WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM offers WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM clients WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM listings WHERE agency_id = %s", (agency_id,))
        cleanup.execute("DELETE FROM imports_importjob WHERE agency_id = %s", (agency_id,))
        cleanup.execute(
            "DELETE FROM token_blacklist_outstandingtoken WHERE user_id = %s",
            (user_id,),
        )
        cleanup.execute("DELETE FROM accounts_user WHERE id = %s", (user_id,))
        cleanup.execute("DELETE FROM accounts_agency WHERE id = %s", (agency_id,))
        cleanup.commit()
        cleanup.close()
