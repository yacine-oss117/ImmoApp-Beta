from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _fn(node: ast.Module, name: str) -> ast.FunctionDef:
    for item in node.body:
        if isinstance(item, ast.FunctionDef) and item.name == name:
            return item
    raise AssertionError(f"Function {name} not found")


def _calls_import_service(fn: ast.FunctionDef) -> bool:
    for n in ast.walk(fn):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "ImportService"
        ):
            return True
    return False


def _server_paths_with_import_job_manager_access() -> set[str]:
    matches: set[str] = set()
    for path in (ROOT / "server").rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if "ImportJob.objects" in _read(path):
            matches.add(relative)
    return matches


def test_import_upload_views_use_import_service_permission_guard() -> None:
    module = _parse(ROOT / "server" / "api" / "views_import_upload.py")
    for name in ("import_presign", "import_complete", "import_upload"):
        fn = _fn(module, name)
        assert _calls_import_service(fn), f"{name} must guard with ImportService(request.user)"


def test_import_preview_execute_views_use_import_service_permission_guard() -> None:
    preview_module = _parse(ROOT / "server" / "api" / "views_import_preview.py")
    execute_module = _parse(ROOT / "server" / "api" / "views_import_execute.py")
    review_module = _parse(ROOT / "server" / "api" / "views_import_review.py")

    for module, name in (
        (preview_module, "import_preview"),
        (execute_module, "import_execute"),
        (execute_module, "import_status"),
        (review_module, "import_review"),
        (review_module, "import_review_submit"),
    ):
        fn = _fn(module, name)
        assert _calls_import_service(fn), f"{name} must guard with ImportService(request.user)"


def test_import_user_facing_views_do_not_query_import_job_objects_directly() -> None:
    view_paths = (
        ROOT / "server" / "api" / "views_import_upload.py",
        ROOT / "server" / "api" / "views_import_preview.py",
        ROOT / "server" / "api" / "views_import_execute.py",
        ROOT / "server" / "api" / "views_import_review.py",
    )

    for path in view_paths:
        assert "ImportJob.objects" not in _read(
            path
        ), f"{path.name} must stay behind ImportService/import_jobs"


def test_import_service_job_reads_delegate_to_scoped_helper_module() -> None:
    text = _read(ROOT / "server" / "services" / "import_service.py")

    assert "import_jobs.get_job_scoped(" in text
    assert "import_jobs.get_job_by_task_id(" in text


def test_direct_import_job_manager_access_stays_in_explicit_internal_allowlist() -> None:
    allowlist = {
        "server/api/tasks_maintenance.py",
        "server/services/import_admission_service.py",
        "server/services/import_chunk_workflow.py",
        "server/services/import_execution_health.py",
        "server/services/import_job_queue.py",
        "server/services/import_jobs.py",
        "server/services/import_review_submit_dispatch.py",
        "server/services/import_review_submit_attempts.py",
        "server/services/import_runtime_maintenance.py",
        "server/services/import_workflow_leases.py",
    }

    assert _server_paths_with_import_job_manager_access() == allowlist
