# Docs Index

This directory contains the maintained architecture, runtime, security, and reference documentation for the current repository snapshot.

Draft and obsolete planning documents are intentionally excluded. When implementation and prose disagree, use the executable contracts, generated references, and tests as the source of truth.

## Start here

- [guides/CLEAN_MACHINE_BOOTSTRAP.md](guides/CLEAN_MACHINE_BOOTSTRAP.md)
- [guides/NEW_DEVELOPER_START.md](guides/NEW_DEVELOPER_START.md)
- [reference/REPO_STATE.md](reference/REPO_STATE.md)
- [guides/ENV_RUNTIME.md](guides/ENV_RUNTIME.md)
- [guides/RUNTIME_AUTHORITY.md](guides/RUNTIME_AUTHORITY.md)
- [guides/STACK.md](guides/STACK.md)
- [guides/OPENBAO_SETUP.md](guides/OPENBAO_SETUP.md)
- [guides/OBSERVABILITY.md](guides/OBSERVABILITY.md)
- [guides/OPERATING_EXPENSIVE_WORK.md](guides/OPERATING_EXPENSIVE_WORK.md)
- [guides/PERF_PROFILES.md](guides/PERF_PROFILES.md)
- [architecture/CONTROL_PLANE.md](architecture/CONTROL_PLANE.md)
- [architecture/EXPENSIVE_WORK_MAP.md](architecture/EXPENSIVE_WORK_MAP.md)
- [architecture/CODEBASE_MAP.md](architecture/CODEBASE_MAP.md)
- [../app/tests/e2e_desktop/README.md](../app/tests/e2e_desktop/README.md)
- [architecture/RUNTIME_AND_DATA_FLOWS.md](architecture/RUNTIME_AND_DATA_FLOWS.md)
- [architecture/IMPORTER_ARCHITECTURE.md](architecture/IMPORTER_ARCHITECTURE.md)
- [architecture/MATCH_SCHEDULER_ARCHITECTURE.md](architecture/MATCH_SCHEDULER_ARCHITECTURE.md)
- [architecture/MATCHING_AND_CACHE_ARCHITECTURE.md](architecture/MATCHING_AND_CACHE_ARCHITECTURE.md)
- [architecture/CRM_LIFECYCLE.md](architecture/CRM_LIFECYCLE.md)
- [architecture/STORAGE_AND_MEDIA.md](architecture/STORAGE_AND_MEDIA.md)
- [architecture/AUTH_AND_SECURITY.md](architecture/AUTH_AND_SECURITY.md)
- [reference/DB_SCHEMA_REFERENCE.md](reference/DB_SCHEMA_REFERENCE.md)
- [reference/DB_MIGRATION_STRATEGY.md](reference/DB_MIGRATION_STRATEGY.md)
- [reference/API_VERSIONING_PAGINATION_POLICY.md](reference/API_VERSIONING_PAGINATION_POLICY.md)
- [reference/API_ROUTE_REFERENCE.md](reference/API_ROUTE_REFERENCE.md)
- [reference/DB_TABLE_CATALOG.md](reference/DB_TABLE_CATALOG.md)
- [architecture/ARCHITECTURE_INVARIANTS.md](architecture/ARCHITECTURE_INVARIANTS.md)

## Importer Reading Order

If you are touching importer execution or triaging importer runtime issues, use
these in order:

1. [architecture/IMPORTER_ARCHITECTURE.md](architecture/IMPORTER_ARCHITECTURE.md)
2. [architecture/CONTROL_PLANE.md](architecture/CONTROL_PLANE.md)
3. [architecture/RUNTIME_AND_DATA_FLOWS.md](architecture/RUNTIME_AND_DATA_FLOWS.md)
4. [../ops/runbooks/IMPORTER_OPERATIONS.md](../ops/runbooks/IMPORTER_OPERATIONS.md)

Important current shape:

- `server/api/views_import_execute.py` is the HTTP edge only
- status payload shaping lives in `server/services/import_status_payload.py`
- execute admission/response shaping lives in `server/services/import_execute_request.py`
- cancel mechanics live in `server/services/import_cancel_flow.py`
- `server/services/import_chunk_workflow.py` is the stable workflow facade
- workflow storage/manifests/leases/dispatch now live in dedicated
  `server/services/import_workflow_*.py` modules
- `server/api/views_import_review.py` is now the thin review API edge
- importer review ownership is split across:
  `server/services/import_review_store.py` as the public facade,
  `server/services/import_review_db_state.py` for DB-backed review
  persistence/backfill,
  `server/services/import_review_queries.py` for review reads,
  `server/services/import_review_mutations.py` for stored resolution-state
  mutations, and
  `server/services/import_review_payloads.py` for payload shaping/submit
  normalization
- importer review execution is split across:
  `server/services/import_review_execution_service.py` and
  `server/services/import_review_resolution.py`
- `app/views/imports/step_review.py` is now the stable review-step root
- row-card rendering, review-page hydration, API transport, and draft/action
  shaping live in dedicated `review_*.py` UI modules

## Auth/Security Reading Order

If you are touching auth, registration, sessions, MFA, step-up, or permission
grants, use these in order:

1. [architecture/AUTH_AND_SECURITY.md](architecture/AUTH_AND_SECURITY.md)
2. [reference/REPO_STATE.md](reference/REPO_STATE.md)
3. [reference/API_ROUTE_REFERENCE.md](reference/API_ROUTE_REFERENCE.md)

Important current auth/security shape:

- `server/services/auth_sessions.py` is the stable public facade over:
  `server/services/session_lifecycle.py` and
  `server/services/session_revocation.py`
- `server/services/user_auth_lifecycle.py` remains the public orchestration
  owner for password reset and account-action flows, with token mechanics in
  `server/services/auth_token_actions.py`
- `server/services/registration_lifecycle.py` is the compatibility facade over:
  `server/services/registration_tokens.py`,
  `server/services/registration_approval.py`, and
  `server/services/registration_invites.py`
- `server/services/permission_elevation.py` is the stable public facade over:
  `server/services/permission_grant_queries.py` and
  `server/services/permission_grant_workflow.py`
- security-sensitive API views remain the boundary for lockout, step-up, and
  denial-path behavior; those checks were not moved into generic helpers

## Native Desktop E2E Reading Order

Use this when validating real PySide6 user journeys rather than widget-level
tests:

1. [../app/tests/e2e_desktop/README.md](../app/tests/e2e_desktop/README.md)
2. [guides/STACK.md](guides/STACK.md)
3. [guides/ENV_RUNTIME.md](guides/ENV_RUNTIME.md)
4. [reference/REPO_STATE.md](reference/REPO_STATE.md)

Important current E2E shape:

- native desktop E2E uses `pytest` + `pywinauto` with `backend="uia"`
- tests launch the real `app/main.py` process and use the real backend stack
- local-only E2E backend controls are enabled only by `IMMOAPP_E2E_TEST_MODE=1`
- the runner verifies the authenticated E2E runtime identity endpoint before
  launch and fails fast on stale Docker/backend code
- disabled E2E HTTP routes are hidden as 404 before auth, and E2E control
  service consumers self-gate when mode is disabled
- passing E2E artifacts are deleted automatically
- retained failed/kept artifacts are pruned by retention age
- the E2E lane is intentionally separate from `checks.ps1 -Stage pr`

## Exact current surfaces

Use these when prose is not enough and you need the live repo contract:

- [reference/API_ROUTE_REFERENCE.md](reference/API_ROUTE_REFERENCE.md):
  generated `/api/v1/` route surface from `server/api/route_registry.py`
- [reference/DB_TABLE_CATALOG.md](reference/DB_TABLE_CATALOG.md):
  generated table catalog
- [reference/SCHEMA_AUTHORITY.md](reference/SCHEMA_AUTHORITY.md):
  generated schema authority map
- [reference/DOMAIN_INTEGRATION_MATRIX.md](reference/DOMAIN_INTEGRATION_MATRIX.md):
  critical runtime long-path coverage map
- [../app/tests/e2e_desktop/README.md](../app/tests/e2e_desktop/README.md):
  native desktop E2E runtime, markers, selectors, and artifact retention

Operational runbooks and policies live under `ops/`, not here.
