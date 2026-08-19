# Repo State

This file is the current high-level state of the whole repo.

## What this repo currently is

ImmoApp is a desktop real-estate CRM and matching system with:

- a Qt desktop client under `app/`
- a Django + Celery backend under `server/`
- shared domain logic under `core/`
- Docker-managed local infrastructure under `deployment/`
- owner docs under `docs/`
- operational runbooks and policies under `ops/`

The product surface is broader than a single CRM screen. The current repo owns:

- client-side and listing-side CRM workflows
- importer/ETL workflows
- match computation and durable cache rebuilds
- auth, MFA, OIDC, step-up, and session security
- storage/media flows
- background work admission, queueing, and repair
- native Windows desktop E2E coverage for real PySide6 user journeys

## Runtime shape

Primary local mode:

1. Docker-managed local infra and compose-based service runtime
2. canonical clean-machine bootstrap through `scripts/bootstrap_local_runtime.ps1`
3. canonical OpenBao/bootstrap sequence through:
   `stack.ps1 -Action up-infra`,
   `setup_openbao_identity.ps1`,
   `stack.ps1 -Action sync-secrets`,
   `stack.ps1 -Action db-prepare`,
   `stack.ps1 -Action up-app`
4. repo quality gates through `checks.ps1`

Secondary local mode:

- host-local server + desktop runtime for targeted Django/debug work only

Current runtime/platform shape:

- desktop client: Qt under `app/`
- backend: Django + Celery under `server/`
- shared importer and matcher logic: `core/`
- local infra: Docker-managed Postgres, RabbitMQ, Valkey, MinIO, ClamAV, OpenBao, Caddy
- canonical external runtime root: `C:\ProgramData\ImmoApp`
- Docker-managed local state outside ProgramData:
  `openbao_data`, `openbao_logs`
- native desktop E2E runs the real app out of process with `pytest` +
  `pywinauto` UIA against the local backend/runtime stack

## What is authoritative

Repo truth:

- source code
- migrations
- deployment manifests
- supported scripts and checks
- owner docs and generated references
- runtime templates such as `deployment/env/.env.example`

External local truth:

- active env/runtime material under `C:\ProgramData\ImmoApp`
- local bootstrap/secret files under `C:\ProgramData\ImmoApp\secrets`
- local virtual environments
- bind-mounted Docker data
- OpenBao live secret payload

Important rule:

- repo code and machine-local runtime state are separate sources of truth
- the repo defines how machine state is created
- OpenBao remains the normal secrets backend
- repo `.env` fallback is non-default and unsupported unless explicitly enabled

## Runtime bootstrap ownership

Script ownership for the supported Windows local path:

- bootstrap and runtime directory creation:
  `scripts/bootstrap_local_runtime.ps1`
- env initialization from template:
  `scripts/bootstrap_local_runtime.ps1`
- OpenBao identity setup:
  `scripts/setup_openbao_identity.ps1`
- OpenBao secret sync from local bootstrap JSON:
  `scripts/stack.ps1 -Action sync-secrets`
- stack startup:
  `scripts/stack.ps1`
- destructive reset/recovery on an already bootstrapped machine:
  `scripts/dev_reset.ps1`

## Repo-wide architectural state

### Desktop client

The desktop client is a real first-class runtime, not a thin demo shell.

Current state:

- screen-level views live under `app/views/`
- reusable widgets live under `app/widgets/`
- API and client orchestration live under `app/services/`
- entity-specific server adapters live under `app/services/*_repository.py`
- background client work lives under `app/workers/`
- realtime notifications are maintained through `app/widgets/notification_hub.py`
- offline overlays and reconciliation exist for parts of the CRM surface
- stable `objectName` and accessibility hooks exist on critical desktop
  surfaces for native UI automation

Important rule:

- desktop runtime code must not import `server.*`

### Backend and API

The backend is a Django API plus Celery worker system.

Current state:

- canonical `/api/v1/` route truth lives in `server/api/route_registry.py`
- HTTP/API views live under `server/api/`
- request validation lives in `server/api/request_schemas*.py`
- stable response payloads live in `server/api/response_schemas.py`
- WebSocket routing/protocol lives in `server/api/ws_*.py`
- business/service orchestration lives under `server/services/`
- lower-level Postgres runtime and UoW code live under `server/pg/`
- durable import job state lives under `server/imports/`
- security/auth/account models live under `server/accounts/`

The service layer is the real use-case surface; views are not meant to hold the
business logic directly.

### UI, API, and service sync surface

The repo keeps the desktop, API, and service layers aligned through explicit
contract owners.

Current state:

- desktop views should talk to the backend through `app/services/api_client*.py`
  and `app/services/*_repository.py`
- exact live API surface is generated in `docs/reference/API_ROUTE_REFERENCE.md`
- request/response contract owners are `server/api/request_schemas*.py` and
  `server/api/response_schemas.py`
- use-case decisions belong in `server/services/*`, not duplicated in UI widgets
- shared HTTP and WebSocket protocol policy lives under `core/contracts/`

Important rule:

- when UI, API, and service behavior drift, fix the contract owner first, not
  only a single widget or endpoint

### Database and schema ownership

The repo is in a split authority model:

- Alembic owns physical schema truth for business tables
- Django owns runtime model state
- Django must not blindly duplicate Alembic DDL
- Alembic-owned runtime models must use state-only mirrors where required

Current schema mode remains:

- `IMMOAPP_SCHEMA_MODE=alembic`

Generated DB references under `docs/reference/` are part of the current repo
truth, not optional notes.

Important repo rule:

- admin/bootstrap raw SQL is still intentional in bounded repair paths
- normal runtime business side effects remain service-owned through the UoW and
  `on_commit` callbacks
- bootstrap helpers are not the model for normal application writes

### CRM lifecycle

The CRM surface is broader than simple contact management.

Current business entity surface includes:

- clients
- demandes
- listings
- offers
- visits
- contracts
- contract articles and clauses

Current state:

- write paths are UoW/SQL-backed
- list/detail reads are mostly SQL-backed, not ORM-heavy
- CRM writes can invalidate dashboard or matching cache state
- desktop UI has dedicated client, listing, and CRM surfaces
- `demande` price and surface are range fields
- `offer` price is a single budget plus optional negotiation margin

### Importer state

Current importer state:

- distributed import workflow is the real execution path
- grouped DB-backed review is the current review truth
- importer intelligence v2 is in the live code path:
  - column semantics
  - sheet/workbook profiling
  - agency profile hints
  - recovery and recoverability
  - dead-letter history
- importer workflow state is durable in DB/object storage
- importer execution ownership is now intentionally split:
  - `server/api/views_import_execute.py` is the HTTP edge only
  - `server/services/import_execute_request.py` owns execute admission and
    response shaping
  - `server/services/import_status_payload.py` owns status payload shaping
  - `server/services/import_cancel_flow.py` owns cancel mechanics
  - `server/services/import_executor.py` owns direct execution orchestration
  - `server/services/import_execution_state.py` owns direct execution state,
    failure, and cleanup helpers
  - `server/services/import_executor_checkpoint.py` owns planned-artifact
    checkpoint mechanics
  - `server/services/import_chunk_workflow.py` is the stable workflow facade
  - `server/services/import_workflow_storage.py`,
    `server/services/import_workflow_manifests.py`,
    `server/services/import_workflow_leases.py`, and
    `server/services/import_workflow_dispatch.py` own the durable workflow
    internals behind that facade
  - `server/services/task_attempt_lifecycle.py` owns domain-neutral
    task-attempt transition rules and terminal monotonicity
  - `server/services/import_review_submit_attempts.py` owns
    workflow-backed review-submit attempt persistence and row-locked
    cancellation/terminal fencing
  - `server/services/import_phase_attempts.py` owns distributed phase
    attempt mapping over existing `ImportChunkPhase` leases
  - `server/services/import_prepare_service.py` and
    `server/services/import_planning_service.py` remain the public phase
    facades, with mode-specific implementations under
    `server/services/import_prepare_*_flow.py` and
    `server/services/import_plan_*_flow.py`
- importer review ownership is also intentionally split:
  - `server/api/views_import_review.py` is the thin review API edge
  - `server/services/import_review_store.py` is the stable review storage facade
  - `server/services/import_review_db_state.py` owns DB-backed review
    persistence, compatibility sampling, and legacy backfill
  - `server/services/import_review_queries.py` owns review reads, paging, and
    snapshot queries
  - `server/services/import_review_mutations.py` owns stored review
    resolution-state mutations and effective submit payload derivation
  - `server/services/import_review_payloads.py` owns review payload shaping and
    submit normalization
  - `server/services/import_review_execution_service.py` is the stable
    review-resolution execution facade
  - `server/services/import_review_resolution.py` owns actual review-resolution
    execution with injected dependencies
  - `server/services/import_review_grouping.py`,
    `server/services/import_review_policy.py`, and
    `server/services/import_review_rescue.py` remain focused domain owners
- desktop importer review is no longer one large widget:
  - `app/views/imports/step_review.py` is the stable Qt root
  - `app/views/imports/review_row_card.py` owns row editing
  - `app/views/imports/review_page_controller.py` owns page hydration and
    conflict mapping
  - `app/views/imports/review_api_adapter.py` owns review transport calls
  - `app/views/imports/review_actions.py` owns pure action/draft shaping
- importer cancel support exists:
  - `POST /api/v1/import/<session_id>/cancel/`
- importer status now exposes wait-state diagnostics:
  - `queued`
  - `waiting_for_worker`
  - `running`
  - `stalled`
- finalize owns spool-backed review-row cleanup through one exception-safe
  `try/finally` cleanup site after review-row collection
- review metadata projection is strict by default:
  - arbitrary metadata stays nested under `metadata`
  - top-level promotion is explicit allowlist-only
  - explicit top-level review fields remain authoritative
- review resolution remains intentionally per-row OCC:
  - bounded by importer security limits
  - fail-fast on the first heterogeneous entity-service conflict
- weak same-side bundle files can expose mapping recovery palettes:
  - `entity_only`
  - `same_side_union`
  - `recovery_union`
- pipeline trace fixtures exist under:
  - `app/tests/fixtures/import_pipeline_trace/`
- replay corpus fixtures exist under:
  - `app/tests/fixtures/import_corpus/`
- importer normalization now treats extracted-extra collisions explicitly:
  - equivalent duplicates stay auto-safe
  - conflicting extracted extras force review
  - conflicted extras do not silently overwrite normalized business data
- importer numeric parsing is field-aware instead of suffix-strip based
- importer money normalization is now DZD-canonical and dialect-aware:
  - explicit `DZD` / `DA` stays DZD
  - explicit `centime` / `cts` stays centime and is converted to DZD
  - colloquial `mrd` / `milliard` defaults to Algerian centime-billion speech
  - ambiguous `m` / `M` / `million` shorthand only auto-resolves when header,
    column, or trusted agency context is strong enough
  - bare decimals like `1.5` no longer degrade into digit-stitched integers
- importer preview now exposes `price_dialect_summary` diagnostics for ambiguous
  money columns
- importer review rows now carry price interpretation candidates for bulk DZD vs
  centime confirmation
- importer learning now supports agency-scoped `price` alias memory with the
  same cautious promotion threshold as other domains
- importer phone normalization now accepts Algerian `08...` service numbers and
  `09...` special numbers as valid kinds instead of treating them as unknown
- importer preview now exposes dominant-side file-model diagnostics for chaotic
  sheets:
  - `client_lead_sheet`
  - `listing_inventory`
  - `mixed`
  - `unknown`
- parse-time semantic inference no longer flattens duplicate semantic domains
  into one lossy row projection
- passthrough sanitization failures now quarantine normalized values to `None`
  and force review instead of carrying unsafe raw text into normalized business
  data

The importer is no longer a purely synchronous or row-blob-based flow. It is a
durable workflow with grouped review, lease repair, cancel semantics, and
explicit wait-state diagnostics.

### Matching and cache state

Matching is an active subsystem, not just a read helper.

Current state:

- domain logic lives under `core/matcher/`
- durable pair and cache state live under `core/data/`
- backend task owners live under `server/api/tasks_match_*.py`
- count cache and pair rebuilds are durable and backpressured
- importer and CRM writes can trigger match rebuild or cache invalidation
- desktop match UI fetches and renders results; it does not compute them locally
- price overlap uses `demande` ranges against `offer` budget plus negotiation margin

### Storage and media state

Storage/media is a real subsystem.

Current state:

- object metadata lifecycle is durable
- presigned upload and completion flows are the canonical large-file path
- local presign readiness failures are surfaced as retryable `503` outcomes
  instead of being mislabeled as unreadable files
- importer file staging uses this subsystem
- offer photos and agency media ride on the same storage base
- offer photos belong to offers because listings represent owner/contact
  identity and offers represent marketed properties/opportunities
- native desktop E2E now covers offer property photo upload/delete with
  backend storage metadata and soft-delete truth
- quota accounting includes pending and ready reservations, not only completed uploads

### Auth and security state

Auth/security is broader than JWT login.

Current state:

- JWT login and refresh are session-aware
- password reset, activation, owner registration, and invite acceptance are durable flows
- optional OIDC exists
- TOTP MFA exists
- step-up authentication exists for sensitive actions
- temporary privilege elevation is a durable workflow, not an ad hoc flag
- auth/security event logging exists as an append-only audit surface
- request/task DB context carries tenant and actor information for safe access
- auth/session ownership is now intentionally split:
  - `server/services/auth_sessions.py` is the public session facade
  - `server/services/session_lifecycle.py` owns issuance, refresh binding,
    validation, touch, and validation cache behavior
  - `server/services/session_revocation.py` owns list/revoke/revoke-all behavior
- user action-token flows are intentionally purpose-scoped:
  - `server/services/user_auth_lifecycle.py` remains the public password
    reset/account-activation owner
  - `server/services/auth_token_actions.py` owns `UserActionToken`
    mechanics only for that subsystem
- registration and invite lifecycle ownership is now intentionally split:
  - `server/services/registration_lifecycle.py` is the compatibility facade and
    test seam owner
  - `server/services/registration_tokens.py` owns registration mechanical
    helpers such as token/code/hash/base-url logic
  - `server/services/registration_approval.py` owns submit/review/approve/
    blacklist/activate flows
  - `server/services/registration_invites.py` owns team invite create/list/
    resend/revoke/accept flows
- privilege elevation ownership is now intentionally split:
  - `server/services/permission_elevation.py` is the public facade
  - `server/services/permission_grant_queries.py` owns read-side request and
    effective-permission queries
  - `server/services/permission_grant_workflow.py` owns request/approve/deny/
    revoke workflow mutations
- security boundary views remain stable:
  - `server/api/auth_views.py`
  - `server/api/auth_account_views.py`
  - `server/api/views_registration.py`
  - `server/api/views_auth_sessions.py`
  - `server/api/views_user_permissions.py`
  - `server/api/step_up.py`

### Notifications and realtime state

Notifications are a first-class runtime path, not a UI-only nicety.

Current state:

- durable inbox APIs live under `/api/v1/notifications/*`
- realtime delivery lives under `/ws/notifications/`
- desktop realtime handling lives in `app/widgets/notification_hub.py`
- importer, matching, compliance, and other background work can emit notifications
- websocket delivery augments durable inbox state; it does not replace it

### Control plane and expensive work state

The repo has an explicit control-plane model for expensive work.

Current state:

- work admission and runtime pressure are explicit
- importer queueing and repair are control-plane owned
- one running import per agency is enforced
- queued and waiting-for-worker are different states
- maintenance tasks repair expired importer phases and stalled importer jobs
- match rebuilds and other expensive work classes are separately profiled

### Observability state

Observability is not optional glue.

Current state:

- SigNoz OSS is the documented local observability stack
- OTEL tracing/metrics/log export is part of the runtime contract
- repo verifiers enforce parts of the observability contract
- importer telemetry now includes terminal reason, wait-state, mapping, cancel, and repair signals
- generated route/schema references and domain integration docs are part of the repo truth surface

## Current documentation state

The docs set is intentionally small and owner-based.

Current state:

- `README.md` is the front door
- `docs/README.md` is the docs index
- `docs/reference/API_ROUTE_REFERENCE.md` is the exact route surface
- `docs/reference/DB_TABLE_CATALOG.md` is the exact table catalog
- `docs/reference/SCHEMA_AUTHORITY.md` is the exact schema authority map
- `docs/reference/DOMAIN_INTEGRATION_MATRIX.md` is the critical long-path coverage map
- `docs/reference/REPO_STATE.md` is the high-level repo snapshot
- subsystem owner docs under `docs/architecture/` and `ops/runbooks/` are the canonical narrative docs

Important documentation correction already in place:

- grouped DB-backed importer review is the current truth
- legacy descriptions that imply `ImportJob.review_rows` is the main review model are obsolete

## Current quality and verification state

Current repo verification shape:

- lint and typing are enforced through `ruff` and `mypy`
- schema and migration authority are enforced through dedicated verifier scripts
- route, runtime, supply-chain, UI copy, and observability contracts have explicit verifier coverage
- server and UI tests live under `app/tests/`
- native desktop E2E lives under `app/tests/e2e_desktop/`
- additional repo-level tests live under `tests/`
- native desktop E2E is a separate Windows-only lane:
  - smoke: `scripts/test_e2e_desktop.ps1 -Suite smoke`
  - broader coverage: `scripts/test_e2e_desktop.ps1 -Suite nightly`
- native desktop E2E verifies `GET /api/v1/e2e/runtime/identity/` before
  launching the app, so stale Docker/backend code fails fast
- disabled `/api/v1/e2e/...` routes are hidden as 404 before authentication,
  and E2E control service consumers self-gate so stale control state cannot
  affect normal runtime
- if backend code may be stale, use `scripts/test_e2e_desktop.ps1 -Suite smoke
  -RebuildBackend`; copied-file container sync is rejected for product E2E
- nightly native desktop E2E covers the CRM contract lifecycle from a real
  match through contract create, detail edit, print, sign, cancel, and
  soft-delete, with authenticated backend truth assertions
- desktop E2E artifacts are retained only for failed or explicitly kept runs
  and stale retained artifacts are pruned by age

Practical meaning:

- the repo has explicit static, contract, DB-backed, and deeper integration gates
- DB-backed lanes depend on the supported local infra being reachable through the expected local endpoints

## Current residual repo risks

The repo is materially more stable than earlier importer-only scans suggested,
but some residual risk remains.

Current highest-value open residual risks:

- ugly real-world importer heuristics can still over-review or conservatively block messy files
- importer stalled/orphaned recovery still needs real rollout observation
- doc drift can reappear if subsystem contracts evolve without doc/test updates
- broader native desktop E2E coverage still needs expansion for offline sync
  and step-up/reauth flows where those remain current product commitments

These are operability and maturity risks, not a known open core-breakage claim
against the main repo surface.

## Current remaining work

What is still left before the repo can honestly be called pre-canary complete:

- expand importer ugly-file truth matrix coverage further
- expand importer replay corpus further
- finish stronger importer-specific observability and operator feedback loops
- finish named final scan coverage for all pre-canary paths
- expand native desktop E2E beyond the current smoke/nightly canonical journeys
- keep importer owner docs and architecture guards aligned when control-plane
  seams move again

## Where to go next

Use these docs next depending on the topic:

- repo/runtime entry:
  - `README.md`
  - `docs/README.md`
- runtime truth:
  - `docs/guides/RUNTIME_AUTHORITY.md`
  - `docs/guides/ENV_RUNTIME.md`
- control plane and expensive work:
  - `docs/architecture/CONTROL_PLANE.md`
  - `docs/guides/OPERATING_EXPENSIVE_WORK.md`
- importer:
  - `docs/architecture/IMPORTER_ARCHITECTURE.md`
  - `ops/runbooks/IMPORTER_OPERATIONS.md`
- matching/cache:
  - `docs/architecture/MATCHING_AND_CACHE_ARCHITECTURE.md`
- CRM:
  - `docs/architecture/CRM_LIFECYCLE.md`
- storage/media:
  - `docs/architecture/STORAGE_AND_MEDIA.md`
- auth/security:
  - `docs/architecture/AUTH_AND_SECURITY.md`
- exact surfaces:
  - `docs/reference/API_ROUTE_REFERENCE.md`
  - `docs/reference/DB_TABLE_CATALOG.md`
