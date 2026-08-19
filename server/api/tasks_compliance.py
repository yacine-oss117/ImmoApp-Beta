"""Compliance background tasks."""

from __future__ import annotations

from server.services import compliance_jobs

from .tasks_core import task_decorator


@task_decorator(name="server.api.tasks_compliance.run_compliance_export_task")
def run_compliance_export_task(_task: object, job_id: str) -> dict[str, object]:
    return compliance_jobs.run_export_job(job_id=job_id)


@task_decorator(name="server.api.tasks_compliance.run_compliance_delete_task")
def run_compliance_delete_task(_task: object, job_id: str) -> dict[str, object]:
    return compliance_jobs.run_delete_job(job_id=job_id)


__all__ = ["run_compliance_delete_task", "run_compliance_export_task"]
