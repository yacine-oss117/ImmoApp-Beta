"""Importer-specific admission logic with degraded-safe fallback."""

from __future__ import annotations

from dataclasses import dataclass

from server.imports.models import ImportJob
from server.services import tenant_resource_governor
from server.services.import_execution_governor import effective_import_runtime_profile
from server.services.work_admission import AdmissionMode


@dataclass(frozen=True)
class AdmissionDecision:
    allowed: bool
    retry_after: int
    degraded: bool
    execution_profile: str
    admission_mode: AdmissionMode
    queue_on_pressure: bool = False
    pressure_reason: str = ""


def admit_import_parse(*, agency_id: int, budget_name: str = "import_parse") -> AdmissionDecision:
    profile_hint = effective_import_runtime_profile().name
    if tenant_resource_governor.governor_backend_available():
        allowed, retry_after = tenant_resource_governor.allow_expensive_work(
            budget_name=budget_name,
            agency_id=int(agency_id),
        )
        return AdmissionDecision(
            allowed=bool(allowed),
            retry_after=int(retry_after or 0),
            degraded=False,
            execution_profile=profile_hint,
            admission_mode="normal",
            pressure_reason="token_bucket",
        )
    global_active = int(
        ImportJob.objects.filter(
            status__in=[ImportJob.Status.PARSING, ImportJob.Status.RUNNING]
        ).count()
    )
    allowed = global_active < 2
    return AdmissionDecision(
        allowed=allowed,
        retry_after=0 if allowed else 10,
        degraded=True,
        execution_profile="red",
        admission_mode="degraded",
        pressure_reason="degraded_parse_fallback",
    )


def admit_import_execute(
    *,
    agency_id: int,
    cost: int,
    execution_profile: str,
) -> AdmissionDecision:
    if tenant_resource_governor.governor_backend_available():
        allowed, retry_after = tenant_resource_governor.allow_expensive_work(
            budget_name="import_execute",
            agency_id=int(agency_id),
            cost=max(1, int(cost)),
        )
        return AdmissionDecision(
            allowed=bool(allowed),
            retry_after=int(retry_after or 0),
            degraded=False,
            execution_profile=str(execution_profile or "green"),
            admission_mode="normal",
            pressure_reason="token_bucket",
        )
    agency_running = ImportJob.objects.filter(
        agency_id=int(agency_id),
        status=ImportJob.Status.RUNNING,
    ).exists()
    global_running = int(ImportJob.objects.filter(status=ImportJob.Status.RUNNING).count())
    allowed = (not agency_running) and global_running < 2
    return AdmissionDecision(
        allowed=allowed,
        retry_after=0 if allowed else 10,
        degraded=True,
        execution_profile="red",
        admission_mode="degraded",
        queue_on_pressure=not allowed,
        pressure_reason="degraded_execute_fallback",
    )


__all__ = [
    "AdmissionDecision",
    "admit_import_execute",
    "admit_import_parse",
]
