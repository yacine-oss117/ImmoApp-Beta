from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_import_executor_does_not_write_progress_via_django_orm_inside_uow() -> None:
    executor_text = _read("server/services/import_executor.py")
    progress_text = _read("server/services/import_progress_runtime.py")
    assert "ImportJob.objects.filter(id=job.id).update(" not in executor_text
    assert "ImportJob.objects.filter(id=job.id).update(" not in progress_text
    assert "import_jobs_write.update_import_job_progress(" in progress_text
    assert not Path("server/services/import_execution_runtime.py").exists()


def test_import_load_phase_does_not_perform_identity_resolution_queries() -> None:
    load_text = _read("server/services/import_load_service.py")
    planning_text = _read("server/services/import_planning_service.py")
    assert "resolve_existing_matches(" not in load_text
    assert "resolve_child_anchor(" not in load_text
    assert "resolve_existing_matches(" in planning_text
    assert "resolve_child_anchor(" in planning_text
