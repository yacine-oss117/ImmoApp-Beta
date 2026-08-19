# Runtime And Data Flows

This file explains how the major runtime paths work at a high level.

## Hub Runtime Profile

`core/runtime/hub_runtime_profile.py` is the central backend owner for machine capacity detection
and safe runtime limits. Server services, scripts, Docker startup, diagnostics, and tests must use
this owner instead of calling `os.cpu_count()` or `psutil.virtual_memory()` directly. The baseline
profile is selected from the weakest stable dimension among CPU, total RAM, DB capacity, and
container limits. CPU alone does not make a machine `large`: a 12-core machine with 16 GB RAM still
uses `medium` limits because Docker, Postgres, Celery, and the desktop share that memory. Windows
free RAM is only diagnostics/live pressure input because Windows uses RAM as cache; it does not
choose the baseline machine class.

Hub startup persists `hub_runtime_profile.json` with schema, selected limits, source, reason, and a
stable capacity fingerprint. Auto-generated persisted profiles regenerate when stable CPU/RAM or
container capacity changes materially. Pinned/custom profiles are kept only when they validate
against the current safe baseline.

The same owner exposes a green/yellow/red memory-pressure snapshot. Yellow/red pressure temporarily
reduces non-urgent import, match, background, polling, and media limits without rewriting the
persisted baseline profile.

`server/services/match_runtime_profile.py` remains the match-specific pressure controller. Its
green/yellow/red settings are bounded by the Hub Runtime Profile so match rebuilds use the safer
lower value between machine baseline capacity and live DB pressure: effective match concurrency and
batching are `min(Hub profile, match pressure profile)`.

## Hub Beta Milestone 1 Setup Surface

Milestone 1 productizes the existing backend stack through wrapper commands
instead of replacing it. `scripts/setup_office_hub.ps1` prepares either a
`HubDesktop` machine or a `WorkstationOnly` desktop profile. `HubDesktop`
requires a friendly Hub display name, writes `hub_identity.json`, uses the
existing Docker/Compose stack internally, sets Hub-mode runtime env, enables
Caddy as the LAN front door, generates the runtime profile, and creates Hub
Manager shortcuts. `WorkstationOnly` verifies and stores a Hub front-door URL;
localhost is refused unless the user explicitly chooses the local-Hub path.
Validate-only Hub setup is dry-run planning evidence only: it can prove the
plan shape but cannot prove that identity, directories, Caddy/front-door config,
or firewall rules were applied. Applied foundation proof requires real writes,
safe ProgramData directory creation without reparse/junction escapes, and, for
LAN mode, a verified Private-profile Windows Firewall rule for only the Caddy
front-door port. Local-only Hub setup may skip the firewall only when the front
door is bound local-only. Hub foundation GO is not agency install GO.

`ImmoApp Hub Manager.exe` is the installed Hub Manager app for Hub roles. It is
a thin UI/control surface over `scripts/hub_manager.ps1`; the script remains
the audited backend control plane and delegates to the existing stack, support
bundle, backup, runtime profile, and health tools so there is still one backend
runtime path. Hub evidence comes from
`collect_hub_install_evidence.ps1` and `collect_hub_status_evidence.ps1`, which
record profile, LAN binding, firewall status, health, data path, runtime
dependency mode, and whether the install is real-agency GO. While Docker Desktop
is manually required, evidence must say `runtime_dependency_mode:
manual_docker_desktop` and `agency_install_status: NO_GO`.
Runtime visibility evidence must be honest: manual Docker Desktop is
operator-visible/internal proof only, while `runtime_hidden_from_operator=true`
is reserved for a verified hidden managed runtime.
The managed WSL2 runtime path now has two explicit internal states:
`managed_wsl2_container_runtime_candidate` proves WSL policy/config planning
only, and `managed_wsl2_container_runtime_artifact` proves a clean
ImmoApp-owned artifact inventory under ProgramData. Neither state starts the Hub
or satisfies agency/public beta readiness. Hub Manager must not fall back to the
repo/dev Docker stack while either provider is active.
`scripts/detect_hub_runtime.ps1` is the read-only runtime detection layer for
packaging proof. Docker Desktop is recorded as `manual_docker_desktop`; only a
hidden ImmoApp-managed runtime registered through the strict ProgramData
provider contract can become `managed_container_runtime`. Invalid provider
config is reported as `invalid_provider_config` and remains NO-GO; Hub/release
paths must not silently fall back to manual Docker Desktop in that case.
Managed runtime package proof is explicit: missing hidden runtime artifacts are
reported as `managed_runtime_artifact_missing`, proof-only providers can prove
command wiring for internal validation, and only a non-proof hidden ImmoApp-owned
provider can make agency install GO.

The provider config is not trusted by declaration. Agency GO requires the
detector to verify canonical `C:\ProgramData\ImmoApp` runtime/config/data/log
roots, lexical and resolved path containment, no symlinks/junctions/reparse
points, a hidden non-Docker-Desktop runtime path, runtime and Compose command
checks, installer SHA-256, a package inventory schema v2 with matching package
artifact SHA-256, required clean source provenance, non-zero inventory size, no
forbidden package paths, and installed runtime/Compose executable hashes
matching inventory critical executable entries. Non-canonical provider paths,
test/dev app-data roots, proof-only providers, self-declared native service
providers, and repo-dev Hub Manager or desktop executable paths are internal
proof only and keep real agency install NO-GO.
External runtime artifacts require a validated
`immoapp_managed_runtime_vendor_provenance` manifest before they can be used for
agency-eligible package proof. The manifest records the runtime license,
artifact hash/bytes, extracted inventory hash, approval reason, matching source
commit, and `approved_by_immoapp=true`; without it external artifacts remain
internal proof only.

Status evidence records both `hub_status` and the lower-level reason fields:
`runtime_state`, `compose_state`, and `status_reason_code`. This separates a
stopped stack from missing app services, starting services, unhealthy services,
runtime unavailability, health endpoint failure, and network/firewall failure.
`verify_hub_m1_local_proof.ps1 -ValidateOnly` does not start services.
It records a running old Hub only as `observed_existing_hub_status`; startup
proof stays `not_applicable`. `-StartHubForProof` may start the local Hub for
internal proof and records `startup_attempted=true`, but that does not replace
real LAN, backup/restore, managed-runtime, or public beta evidence.

LAN exposure is intentionally narrow. Caddy is the only LAN-facing service in
final Hub mode and proxies internally to the backend. The backend direct port,
Postgres, RabbitMQ, Valkey, OpenBao, MinIO API/console, and ClamAV stay
localhost/internal.
Local HTTP is acceptable only for private LAN beta proof and is not public beta
security posture.

Real LAN proof requires a second workstation, VM, or network-isolated client
using the Hub front-door URL. Localhost or synthetic local evidence is never LAN
GO. The local network boundary proof has `proof_scope=local_compose_boundary`
and only proves Compose publisher policy plus local Caddy/front-door health; it
cannot satisfy workstation LAN proof by itself.
Backup/restore evidence must prove an isolated restore bucket, object hash
verification, a restore database, and that the live source bucket was not used
as the restore target.

## 1. Desktop startup

Entry:

- `app/main.py`

Flow:

1. configure pycache/appdata paths
2. configure logging and crash handling
3. initialize Qt application and theme
4. run setup wizard if API target is missing
5. run login flow
6. preload main window and tabs

Key implication: the desktop is a thin client. It should orchestrate through
`app/services/`, not talk directly to server internals.

## 2. Desktop request path

For normal UI actions:

1. a view or widget collects user input
2. an adapter under `app/services/*_repository.py` prepares the request
3. `app/services/api_client*.py` applies auth, retry, timeout, and circuit rules
4. the request hits a route registered in `server/api/route_registry.py`
5. `server/api/request_schemas*.py` or view-level validation normalizes the payload
6. the view delegates to `server/services/*`
7. services call `core/*`, `core/data/*`, and `server/pg/*`
8. the response returns through `server/api/response_schemas.py` or response helpers
9. the repository adapter returns Qt-friendly data back to the view

Key implication: UI, API, and services stay in sync through explicit adapters
and serializers, not by sharing server internals.

## 3. Desktop realtime notifications path

Entry points:

- `app/widgets/notification_hub.py`
- `server/api/ws_routing.py`
- `server/api/ws_notifications.py`

Flow:

1. the desktop notification hub opens `/ws/notifications/`
2. the WebSocket authenticates with the current access token
3. server-side WebSocket handlers validate scope and stream notification events
4. the desktop updates inbox state and toast UI
5. durable inbox reads and mutations still use `/api/v1/notifications/*`

Key implication: notifications are both realtime and durable. WebSocket fanout
does not replace the HTTP inbox.

## 4. Server startup

Entry:

- `server/manage.py`

Flow:

1. configure pycache path
2. load secrets from OpenBao/bootstrap env
3. load Django settings
4. expose root URLs from `server/immoapp_server/urls.py`

Task runtime:

- `server/immoapp_server/celery.py`

Celery boot:

1. load secrets
2. set up observability
3. autodiscover tasks from `server/api/tasks*.py`
4. emit task success/failure events

## 5. HTTP request path

For `/api/v1/*`:

1. root URL config includes `server.api.urls`
2. `server/api/urls.py` builds urlpatterns from the route registry
3. a `views_*.py` function handles request parsing and auth
4. request payloads are normalized through `server/api/request_schemas*.py` where used
5. the view delegates to `server/services/*`
6. services use psycopg UoW/repositories or Django ORM, depending on domain
7. the response is serialized back through DRF/Django response helpers or `response_schemas.py`

Important rule:

- Django ORM is not the business-data default
- business tables are primarily handled through psycopg/UoW paths

## 6. Background job path

Typical pattern:

1. an API endpoint validates request and calls `apply_async(...)`
2. the task name comes from `server/api/tasks.py` exports
3. a task module under `server/api/tasks_*.py` performs scoped work
4. task code uses `server/services/*`, `core/*`, and `server/pg/*`
5. task status/events are surfaced back through task event or status endpoints

Examples:

- importer: `server/api/tasks_import.py`
- match cache rebuild: `server/api/tasks_match_cache.py`
- match pair rebuild: `server/api/tasks_match_pairs.py`

## 7. Import lifecycle

Persistent state:

- `server/imports/models.py`

Flow:

1. upload/presign endpoints create an `ImportJob`
2. `import_parse_task` detects columns, preview rows, and inference summary
3. preview builds a normalized `ImportDecision` and exposes:
   manual mapping, reason codes, palette mode, recoverability, and candidate actions
4. execute recomputes the decision from the latest mapping instead of trusting stale preview state
5. distributed workflow state lives in `ImportWorkflowState`, `ImportChunk`, and `ImportChunkPhase`
6. grouped human review lives in `ImportReviewGroup` and `ImportReviewItem`
7. status reports `wait_state`, stall diagnostics, cancelability, and `terminal_reason`
8. notifications are emitted for started/completed/failed/review-required/cancelled states
9. row-level audit is recorded in `ImportRowAudit`

Core modules:

- `core/importer/`
- `server/services/import_*.py`
- `docs/architecture/IMPORTER_ARCHITECTURE.md`

Current importer execution/control-plane owners:

- HTTP execute/status/cancel edge:
  `server/api/views_import_execute.py`
- execute admission and response shaping:
  `server/services/import_execute_request.py`
- status payload shaping:
  `server/services/import_status_payload.py`
- cancel mechanics:
  `server/services/import_cancel_flow.py`
- direct execution orchestration, state, and checkpoints:
  `server/services/import_executor.py`
  `server/services/import_execution_state.py`
  `server/services/import_executor_checkpoint.py`
- distributed workflow facade and internals:
  `server/services/import_chunk_workflow.py`
  `server/services/import_workflow_storage.py`
  `server/services/import_workflow_manifests.py`
  `server/services/import_workflow_leases.py`
  `server/services/import_workflow_dispatch.py`
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
- prepare and planning public facades:
  `server/services/import_prepare_service.py`
  `server/services/import_planning_service.py`
- mode-specific prepare and planning flows:
  `server/services/import_prepare_*_flow.py`
  `server/services/import_plan_*_flow.py`

## 8. Matching and cache rebuild flow

Core logic:

- `core/matcher/`

Runtime path:

1. entity changes mark rebuild or cache work as needed
2. cache rebuild endpoints or janitors enqueue scoped tasks
3. `tasks_match_pairs.py` computes durable pair state
4. `tasks_match_cache.py` refreshes `match_counts_cache`
5. `match_rebuild_state` prevents missed updates and supports reruns

Matching domain truth:

- `demande` price and surface are range-based (`budget_min/max`, `surface_min/max`)
- `offer` price is a single value plus optional negotiation margin
- matching evaluates price overlap against those normalized shapes

This path is intentionally lock-aware, queued, and tenant-scoped.

See:

- `docs/architecture/MATCHING_AND_CACHE_ARCHITECTURE.md`
- `docs/architecture/CRM_LIFECYCLE.md`
- `docs/architecture/STORAGE_AND_MEDIA.md`
- `docs/architecture/AUTH_AND_SECURITY.md`

## 10. Auth, sessions, registration, and permission flow

Core service owners:

- session facade and internals:
  `server/services/auth_sessions.py`
  `server/services/session_lifecycle.py`
  `server/services/session_revocation.py`
- password reset and account-action tokens:
  `server/services/user_auth_lifecycle.py`
  `server/services/auth_token_actions.py`
- owner registration and team invites:
  `server/services/registration_lifecycle.py`
  `server/services/registration_tokens.py`
  `server/services/registration_approval.py`
  `server/services/registration_invites.py`
- temporary privilege elevation:
  `server/services/permission_elevation.py`
  `server/services/permission_grant_queries.py`
  `server/services/permission_grant_workflow.py`

Typical runtime flow:

1. auth/security request hits `server/api/auth_*.py`,
   `server/api/views_registration.py`,
   `server/api/views_auth_sessions.py`,
   `server/api/views_user_permissions.py`, or `server/api/step_up.py`
2. the view keeps the current lockout, step-up, and denial-path boundaries
3. login serializers in `server/api/auth_session_jwt.py` authenticate the user
4. `server/services/auth_sessions.py` issues, binds, and validates session
   state through `server/services/session_lifecycle.py`
5. session list/revoke/revoke-all behavior runs through
   `server/services/session_revocation.py`
6. password reset and account-action flows stay in
   `server/services/user_auth_lifecycle.py`, with token mechanics isolated in
   `server/services/auth_token_actions.py`
7. registration approval/activation and team invites stay behind
   `server/services/registration_lifecycle.py`, which delegates to narrower
   helper modules without moving the public seam
8. privilege elevation request/approve/deny/revoke flows stay behind
   `server/services/permission_elevation.py`, which delegates to
   `server/services/permission_grant_queries.py` and
   `server/services/permission_grant_workflow.py`
9. auth/security side effects still route through
   `server/services/auth_events.py` and related hardening helpers

Important rule:

- token-purpose boundaries are intentionally separate
- security boundary views still own step-up and sensitive denial-path checks

## 11. Schema and data ownership

- Django migrations own Django app tables
- Alembic owns business-table DDL
- runtime startup does not invent schema
- tenant isolation is enforced in the database with RLS and tenant context

See:

- `docs/reference/DB_MIGRATION_STRATEGY.md`
- `docs/reference/DB_SCHEMA_REFERENCE.md`
- `docs/reference/DB_TABLE_CATALOG.md`

## 12. Managed WSL2 Container Runtime Candidate

The managed WSL2/container runtime lane is the internal beta bridge for the next
Hub runtime candidate. `scripts/managed_wsl2_runtime_policy.ps1` derives a planned WSL2 VM
envelope from stable machine capacity: total physical RAM, logical processors,
and the existing Hub runtime profile envelope. The machine tier is the lower of
the RAM-derived profile and CPU-derived profile; if a runtime profile is
supplied, the planned WSL cap uses the lower of the machine tier and that
runtime profile. It does not use raw free RAM as a sizing baseline;
free/available RAM is diagnostics-only.

WSL policy evidence records the runtime profile provenance explicitly:
`runtime_profile_source`, `runtime_profile_status`, `runtime_profile_path`,
`runtime_profile_sha256`, `runtime_profile_error`, and
`observed_hub_runtime_profile`. Explicit profile input must parse and name a
supported profile, and the default persisted profile has the same fail-closed
validation.

The policy is:

- below the normalized 8 GB RAM class: Hub NO-GO, workstation-only
- 7.5 GB through 8 GB Windows-reported RAM: normalize to the 8 GB class
- 8 GB RAM: tiny/conservative Hub with `hub_on_minimum_ram` warning
- 15.x GB through 16 GB Windows-reported RAM: normalize to the 16 GB class
- 16 GB RAM: small/medium candidate depending on CPU/profile
- 31.5 GB through 32 GB Windows-reported RAM: normalize to the 32 GB class
- 32 GB and above: medium/large candidate only when CPU also supports that tier
- CPU classes: 1-2 logical processors=tiny, 3-4=small, 5-7=medium, 8+=large

WSL caps are ceilings, not reservations. Startup spikes are not failures;
sustained pressure after warm-up is the signal for backoff. Plan-only policy
evidence is recorded as a planned runtime envelope and must not change live Hub
runtime behavior or switch `runtime_dependency_mode`. The live adaptability
layer changes only when an active, verified provider/runtime envelope supplies
effective CPU and memory limits.

Hub Manager can register a proof-only
`managed_wsl2_container_runtime_candidate` provider after generating both WSL
policy evidence and `.wslconfig` plan evidence, but the action requires
`-ConfirmInstallRuntimeCandidate` before it writes provider config. Detection
validates the provider path, the policy/config plan paths, their hashes, and the
semantic WSL sizing fields. This candidate mode is internal proof only:
candidate registration GO is `proof_scope=registration_only`, and Hub Manager
start refuses it with
`managed_wsl2_runtime_artifact_missing` until a real ProgramData runtime
artifact exists. It never upgrades manual Docker Desktop, WSL policy evidence,
or proof-only provider JSON into agency readiness.

`hub_manager.ps1 -Action remove-runtime-candidate` removes only this proof-only
provider config. It does not delete Hub data, backups, identity, logs, or
runtime artifacts, and detection falls back to manual Docker/internal proof or
unavailable state afterward.

The candidate install path refuses to overwrite an existing non-candidate
provider. If a real or promoted provider config already exists, the action
returns `existing_managed_runtime_provider_refuses_candidate_overwrite` and
leaves the provider file byte-for-byte unchanged.

`scripts/configure_managed_wsl2_runtime.ps1` owns `.wslconfig` planning/apply.
`.wslconfig` is global for WSL2 in the current Windows user profile, so ImmoApp
never edits it silently. Apply requires explicit confirmation and may require
`wsl --shutdown`. Duplicate `[wsl2]` sections or duplicate managed keys inside
`[wsl2]` are ambiguous and are rejected unchanged for manual cleanup.
