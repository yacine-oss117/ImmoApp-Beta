# Codebase Map

This file explains what each major repo area is for and which files are the
normal starting points.

## Top-level map

- `app/`: Qt desktop client
- `core/`: shared domain logic and contracts
- `server/`: Django API, Celery tasks, runtime services, DB integration
- `deployment/`: Compose, Docker, proxy, env templates
- `docs/`: owner docs and generated references
- `ops/`: runbooks and policies
- `scripts/`: public commands, checks, verifiers, generators
- `requirements/`: Python dependency authority
- `tools/`: non-app tooling assets

## `app/` desktop client

Important areas:

- `app/main.py`: desktop entrypoint and bootstrap
- `app/views/`: screen-level UI
- `app/widgets/`: reusable UI building blocks and dialogs
- `app/services/`: client orchestration, API access, local persistence helpers
- `app/services/api_client*.py`: HTTP client, auth refresh, retry, and circuit logic
- `app/services/*_repository.py`: entity-specific desktop adapters over the API
- `app/workers/`: background work off the UI thread
- `app/widgets/notification_hub.py`: realtime notification WebSocket client
- `app/ui/`: theme, fonts, and presentation support
- `app/utils/`: lower-level helpers
- `app/tests/e2e_desktop/`: true out-of-process Windows desktop E2E layer

Rule: desktop runtime code must not import `server.*`.

## `core/` shared/domain layer

Important areas:

- `core/contracts/`: shared protocol and route policy contracts
- `core/data/`: server-side SQL/data helpers shared by repositories or tasks
- `core/importer/`: parsing, normalization, detection, validation
- `core/matcher/`: match SQL generation, scoring, batching, counters
- `core/observability/`: shared telemetry helpers
- `core/env_files.py`: env resolution helper

This is where domain logic that should not live directly in Django views or Qt
widgets belongs.

## `server/` backend

Important areas:

- `server/manage.py`: Django entrypoint
- `server/immoapp_server/`: settings, urls, celery, observability bootstrap
- `server/api/route_registry.py`: canonical `/api/v1/` route registry
- `server/api/`: HTTP views, task modules, request/response contracts
- `server/api/request_schemas*.py`: request validation boundary
- `server/api/response_schemas.py`: stable response payload boundary
- `server/api/ws_*.py`: WebSocket routing, auth, and notification protocol handlers
- `server/api/views_e2e.py`: local-only native E2E control endpoints
- `server/services/`: use-case layer for business operations
- `server/services/e2e_control.py`: Redis-backed local-only E2E controls
- `server/pg/`: psycopg UoW, schema, tenancy, security, low-level DB runtime
- `server/alembic/`: business-table migrations
- `server/imports/`: Django models for persisted import jobs and audits
- `server/secret_store/`: OpenBao integration and secret loading
- `server/accounts/`: Django auth/account models and app config

## Cross-layer sync seams

UI to API:

- `app/services/api_client.py`
- `app/services/api_types.py`
- `app/services/*_repository.py`
- `docs/reference/API_ROUTE_REFERENCE.md`

API to service layer:

- `server/api/route_registry.py`
- `server/api/request_schemas*.py`
- `server/api/response_schemas.py`
- `server/api/views_*.py`
- `server/services/*`

Service to domain/data layer:

- `server/services/*`
- `core/contracts/*`
- `core/data/*`
- `server/pg/*`

Realtime notifications:

- `app/widgets/notification_hub.py`
- `core/contracts/ws_protocol.py`
- `server/api/ws_routing.py`
- `server/api/ws_notifications.py`

Native desktop E2E:

- `app/tests/e2e_desktop/`
- `scripts/test_e2e_desktop.ps1`
- `server/services/e2e_control.py`
- `server/api/views_e2e.py`
- `GET /api/v1/e2e/runtime/identity/` validates E2E mode, route presence,
  runtime source mode, and critical backend file fingerprints before launch

## Where to start by topic

Importer:

- `docs/architecture/IMPORTER_ARCHITECTURE.md`
- `core/importer/`
- `server/api/views_import_*.py`
- execute/status/cancel edges and helpers:
  `server/api/views_import_execute.py`
  `server/services/import_execute_request.py`
  `server/services/import_status_payload.py`
  `server/services/import_cancel_flow.py`
- direct execution and checkpoint state:
  `server/services/import_executor.py`
  `server/services/import_execution_state.py`
  `server/services/import_executor_checkpoint.py`
- workflow facade and split owners:
  `server/services/import_chunk_workflow.py`
  `server/services/import_workflow_storage.py`
  `server/services/import_workflow_manifests.py`
  `server/services/import_workflow_leases.py`
  `server/services/import_workflow_dispatch.py`
- prepare and planning public facades:
  `server/services/import_prepare_service.py`
  `server/services/import_planning_service.py`
- mode-specific prepare and planning flows:
  `server/services/import_prepare_*_flow.py`
  `server/services/import_plan_*_flow.py`
- load/finalize execution:
  `server/services/import_load_service.py`
  `server/services/import_distributed_execution.py`
  `server/services/import_finalize_service.py`
- grouped review API/backend:
  `server/api/views_import_review.py`
  `server/services/import_review_store.py`
  `server/services/import_review_execution_service.py`
  `server/services/import_review_db_state.py`
  `server/services/import_review_queries.py`
  `server/services/import_review_mutations.py`
  `server/services/import_review_payloads.py`
  `server/services/import_review_resolution.py`
- grouped review desktop:
  `app/views/imports/step_review.py`
  `app/views/imports/review_row_card.py`
  `app/views/imports/review_page_controller.py`
  `app/views/imports/review_api_adapter.py`
  `app/views/imports/review_actions.py`
- `server/api/tasks_import.py`
- `server/imports/models.py`

Matching and cache rebuild:

- `core/matcher/`
- `docs/architecture/MATCHING_AND_CACHE_ARCHITECTURE.md`
- `server/api/views_cache_tasks.py`
- `server/api/tasks_match_cache.py`
- `server/api/tasks_match_pairs.py`
- `server/services/match_*.py`

CRM entities:

- `docs/architecture/CRM_LIFECYCLE.md`
- `server/api/views_clients_*.py`
- `server/api/views_listings_*.py`
- `server/api/views_demandes.py`
- `server/api/views_offers.py`
- `server/services/clients.py`
- `server/services/listings.py`
- `server/services/demandes.py`
- `server/services/offers.py`

Storage and media:

- `docs/architecture/STORAGE_AND_MEDIA.md`
- `server/api/views_storage.py`
- `server/api/views_agency.py`
- `server/services/storage*.py`

Auth and security:

- `docs/architecture/AUTH_AND_SECURITY.md`
- `server/immoapp_server/urls.py`
- `server/api/auth_*.py`
- `server/api/views_registration.py`
- `server/api/views_auth_sessions.py`
- `server/api/views_user_permissions.py`
- `server/api/step_up.py`
- session facade and internals:
  `server/services/auth_sessions.py`
  `server/services/session_lifecycle.py`
  `server/services/session_revocation.py`
- password reset and account-action tokens:
  `server/services/user_auth_lifecycle.py`
  `server/services/auth_token_actions.py`
- registration and team invites:
  `server/services/registration_lifecycle.py`
  `server/services/registration_tokens.py`
  `server/services/registration_approval.py`
  `server/services/registration_invites.py`
- privilege elevation:
  `server/services/permission_elevation.py`
  `server/services/permission_grant_queries.py`
  `server/services/permission_grant_workflow.py`
- auth hardening and telemetry:
  `server/services/auth_events.py`
  `server/services/auth_lockout.py`
  `server/services/auth_security_alerts.py`
  `server/services/mfa_service.py`
  `server/services/mfa_totp.py`
  `server/services/oidc_auth.py`
- `server/secret_store/`

Native desktop E2E:

- `app/tests/e2e_desktop/conftest.py`
- `app/tests/e2e_desktop/runtime.py`
- `app/tests/e2e_desktop/ui.py`
- `app/tests/e2e_desktop/pages.py`
- `app/tests/e2e_desktop/backend.py`
- `app/tests/e2e_desktop/test_smoke.py`
- `app/tests/e2e_desktop/test_journeys.py`
- `app/tests/e2e_desktop/test_backend_preflight.py`
- `scripts/test_e2e_desktop.ps1`

## Tests

- `app/tests/server_tests/`: most backend contract and runtime tests
- `app/tests/ui_tests/`: Qt/UI tests
- `app/tests/e2e_desktop/`: out-of-process Windows native desktop E2E tests
- `tests/test_importer/`: importer-focused tests outside app/server package trees

## Generated reference files

Use these when you need exact current surfaces instead of prose summaries:

- `docs/reference/API_ROUTE_REFERENCE.md`
- `docs/reference/DB_TABLE_CATALOG.md`
- `docs/reference/SCHEMA_AUTHORITY.md`
- `docs/reference/DOMAIN_INTEGRATION_MATRIX.md`
