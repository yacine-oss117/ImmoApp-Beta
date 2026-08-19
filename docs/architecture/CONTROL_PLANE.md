# Control Plane

This document is the owner doc for expensive-work coordination.

## What The Control Plane Owns

The control plane owns:

- work classification
- admission and backpressure
- runtime pressure profiles
- importer queueing and execution admission
- importer workflow/lease repair
- janitors for stale workflow state

It does not own importer normalization or review business logic. It owns when
expensive work is allowed to start, wait, repair, slow down, or fail.

## Authoritative Owner Files

- runtime pressure profile:
  - `server/services/match_runtime_profile.py`
- shared work admission:
  - `server/services/work_admission.py`
- importer admission:
  - `server/services/import_admission_service.py`
- importer runtime profile:
  - `server/services/import_execution_governor.py`
- importer execution queue:
  - `server/services/import_job_queue.py`
- importer execute/status/cancel HTTP edge:
  - `server/api/views_import_execute.py`
- importer execute request helper:
  - `server/services/import_execute_request.py`
- importer status payload helper:
  - `server/services/import_status_payload.py`
- importer cancel helper:
  - `server/services/import_cancel_flow.py`
- importer direct execution orchestration:
  - `server/services/import_executor.py`
- importer direct execution state/failure/cleanup:
  - `server/services/import_execution_state.py`
- importer direct execution checkpoint helpers:
  - `server/services/import_executor_checkpoint.py`
- importer workflow facade:
  - `server/services/import_chunk_workflow.py`
- importer workflow storage:
  - `server/services/import_workflow_storage.py`
- importer workflow manifests:
  - `server/services/import_workflow_manifests.py`
- importer workflow leases:
  - `server/services/import_workflow_leases.py`
- importer workflow dispatch/progress:
  - `server/services/import_workflow_dispatch.py`
- importer control-plane compatibility facade:
  - `server/services/import_control_plane.py`
- importer execution health:
  - `server/services/import_execution_health.py`
- importer maintenance entrypoints:
  - `server/api/tasks_maintenance.py`
- importer runtime cleanup:
  - `server/services/import_runtime_maintenance.py`

If behavior and docs disagree, these files win.

Important current shape:

- `server/api/views_import_execute.py` is intentionally view-only
- `server/services/import_control_plane.py` is a compatibility facade, not the
  main implementation bucket
- `server/services/import_chunk_workflow.py` is the stable workflow facade, but
  storage/manifests/leases/dispatch ownership lives in dedicated
  `server/services/import_workflow_*.py` modules

## Importer Queue and Watchdog Model

The importer currently uses:

- one running import per agency
- one queued import per agency
- queue positions stored in durable job/workflow state
- lease-based chunk phases for distributed plan/load work
- maintenance tasks for queue/lease repair

Relevant maintenance tasks:

- `requeue_expired_import_phases_task`
- `prune_importer_runtime_artifacts_task`
- `repair_stalled_import_jobs_task`

Ownership split for importer workflow coordination:

- storage and durable workflow payloads:
  `server/services/import_workflow_storage.py`
- manifests, staged artifacts, and materialized row loads:
  `server/services/import_workflow_manifests.py`
- phase leases and cancellation requests:
  `server/services/import_workflow_leases.py`
- task-attempt transition rules:
  `server/services/task_attempt_lifecycle.py`
- review-submit attempt persistence and workflow-backed fencing:
  `server/services/import_review_submit_attempts.py`
- distributed phase attempt persistence over existing phase leases:
  `server/services/import_phase_attempts.py`
- progress rollup and next-phase dispatch:
  `server/services/import_workflow_dispatch.py`
- stable facade and compatibility entrypoints:
  `server/services/import_chunk_workflow.py`

Fairness and admission policy decides which import is scheduled or allowed
to start. Task-attempt fencing decides which running worker may write durable
state. Future preemption must request cancellation through the relevant
attempt adapter instead of killing arbitrary in-flight work.

## Importer Wait States

Canonical importer wait-state language:

- `queued`
  - waiting behind another import for the same agency
- `waiting_for_worker`
  - accepted into execution, but no worker phase has started yet
- `running`
  - active phase work is in progress
- `review`
  - execution paused on grouped operator review
- `completed`
  - terminal success or zero-change completion
- `failed`
  - terminal failure, cancellation, or overflow

Important rule:

- `waiting_for_worker` is not the same thing as active phase execution
- it is a control-plane diagnostic state

## Repair Paths

Repair/janitor owners:

- importer phase lease repair:
  - `requeue_expired_import_phases_task`
- importer stalled-start and orphaned-job repair:
  - `repair_stalled_import_jobs_task`
- importer temp/artifact cleanup:
  - `prune_importer_runtime_artifacts_task`

Current conservative repair rule:

- diagnose and repair only when there is no valid active lease or safe active
  owner
- started review-submit repair first invalidates the workflow-backed attempt
  fence; stale workers that arrive later are ignored
- record repair metadata in workflow payload
- prefer safe redispatch or explicit failure over mutating active leased work

## Work Classes

Current expensive-work classes:

- `import_parse`
- `import_plan`
- `import_load`
- `import_finalize`
- `match_all`
- `match_rebuild_batch`
- `cache_rebuild`
- `maintenance_repair`

Practical DB-first priority order:

1. `import_load`
2. `match_all`
3. `match_rebuild_batch`
4. `import_plan`
5. `import_parse`
6. `import_finalize`
7. `maintenance_repair`

## Runtime Pressure Model

Runtime pressure is expressed as:

- `green`
- `yellow`
- `red`

Admission modes are:

- `normal`
- `degraded`
- `queued`
- `rejected`

Rules:

- degraded mode protects Postgres first
- queued means work is admitted later, not lost
- rejected means the caller must retry later

## How To Debug Importer Pressure Problems

1. Check `health/snapshot/`.
2. Read:
   - `import_runtime_health`
   - `import_runtime_cleanup`
   - `match_runtime_profile*`
3. Inspect importer queue depth and queued imports per agency.
4. Check whether imports are `queued`, `waiting_for_worker`, or truly `running`.
5. Inspect `repair_stalled_import_jobs_task` and
   `requeue_expired_import_phases_task` outputs before forcing intervention.
