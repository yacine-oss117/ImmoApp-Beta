# Expensive Work Map

This is the shortest system map for work that can hurt the VPS.

## Importer

- entry:
  `server/api/views_import_upload.py`
  `server/api/views_import_execute.py`
- execute/status/cancel helpers:
  `server/services/import_execute_request.py`
  `server/services/import_status_payload.py`
  `server/services/import_cancel_flow.py`
- task entry:
  `server/api/tasks_import.py`
- direct execution:
  `server/services/import_executor.py`
  `server/services/import_execution_state.py`
  `server/services/import_executor_checkpoint.py`
- phase facades:
  `server/services/import_prepare_service.py`
  `server/services/import_planning_service.py`
  `server/services/import_distributed_execution.py`
  `server/services/import_finalize_service.py`
- mode-specific prepare/plan flows:
  `server/services/import_prepare_*_flow.py`
  `server/services/import_plan_*_flow.py`
- workflow state:
  `server/imports/models.py`
  `ImportWorkflowState`
  `ImportChunk`
  `ImportChunkPhase`
  `ImportArtifactManifest`
- queue/health control:
  `server/services/import_job_queue.py`
  `server/services/import_chunk_workflow.py`
  `server/services/import_workflow_storage.py`
  `server/services/import_workflow_manifests.py`
  `server/services/import_workflow_leases.py`
  `server/services/import_workflow_dispatch.py`
  `server/services/import_execution_health.py`
  `server/api/tasks_maintenance.py`

## Match-All

- entry:
  `server/api/views_matches.py`
- fairness scheduler:
  `server/services/match_all_scheduler.py`
- lease truth:
  `core/data/tenant_work_lease.py`

## Match Rebuild Batching

- request helpers:
  `server/services/match_jobs.py`
- durable dispatch truth:
  `core/data/match_rebuild_state.py`
- batch task entry:
  `server/api/tasks_match_pairs.py`
- janitor:
  `server/api/tasks_integrity.py`

## Pressure / Admission

- runtime profile:
  `server/services/match_runtime_profile.py`
- tripwire:
  `server/services/runtime_pressure_tripwire.py`
- importer cost/profile:
  `server/services/import_execution_governor.py`
- shared work counts and match-all admission:
  `server/services/work_admission.py`
- importer degraded-safe admission:
  `server/services/import_admission_service.py`

## Cleanup / Repair

- importer runtime cleanup:
  `server/services/import_runtime_maintenance.py`
- maintenance tasks:
  `server/api/tasks_maintenance.py`
- match janitor:
  `server/api/tasks_integrity.py`

## Realtime fanout

- durable notification writes:
  `server/api/notifications.py`
  `server/services/notifications.py`
- websocket fanout:
  `server/api/ws_notifications.py`

Realtime notifications are user-facing, but they are not a separate expensive
work queue. They fan out from durable state written by importer, matching, CRM,
and maintenance flows.

## Queues

- `imports`
- `match_pairs`
- `rebuild_batch`
- `maintenance`

These queues are intentionally separate. Do not collapse them without a new
resource model.
