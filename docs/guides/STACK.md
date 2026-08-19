# Stack Guide

Read [ENV_RUNTIME.md](ENV_RUNTIME.md) first. That file defines the runtime
inventory and which local mode is authoritative. This document only covers the
Docker-local stack commands and recovery operations.

## Hub Runtime Adaptation

`scripts/stack.ps1` generates `hub_runtime_profile.json` through
`scripts/hub_runtime_profile.py` before starting Hub/backend services. Docker and Celery receive
profile-derived worker, import, match, rebuild, DB pool, and batch limits through environment
variables. Weak machines use `tiny`/`small` limits and run slower; larger machines can use
`medium`/`large` limits safely.

Baseline sizing uses the weakest stable dimension among CPU, total RAM, DB capacity, and container
limits. CPU alone does not make a Hub `large`: RAM can lower concurrency because Docker, Postgres,
Celery, and the desktop all share memory. Windows free RAM is not the sizing source because Windows
uses RAM as cache; sustained memory pressure only slows expensive background work temporarily.

Auto-generated persisted profiles include a schema version, selected limits, source, reason, and a
stable capacity fingerprint. Startup regenerates auto profiles when stable hardware/container
capacity changes. Pinned or custom profiles remain only if they validate against the current safe
baseline. `server/services/match_runtime_profile.py` remains a workload pressure clamp; effective
match settings are `min(Hub profile, match pressure profile)`.

For VPS/server deployments, set `IMMOAPP_HUB_PROFILE=tiny|small|medium|large|developer|custom` or
the supported `IMMOAPP_HUB_*` numeric overrides in the runtime env file. Production/staging rejects
unsafe overrides; local/dev can allow non-custom oversubscription only with the explicit unsafe
override flag and warnings. `custom` requires a complete, safe field set.

## Scope

Deployment assets live under:

- `deployment/compose/`
- `deployment/docker/`
- `deployment/proxy/`
- `deployment/env/`

Use the public wrappers instead of raw `docker compose`:

- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap_local_runtime.ps1`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 ...`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_office_hub.ps1 ...`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/hub_manager.ps1 ...`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev_reset.ps1 ...`

## Hub Beta Milestone 1 Wrapper

`scripts/setup_office_hub.ps1` is the first Office Hub setup wrapper. The beta
Inno installer can now call it when the user selects the Office Hub checkbox,
with or without the Desktop checkbox. The main installer remains lowest-privilege; only the Hub
foundation step asks for elevation because opening the private-network Caddy
front-door firewall port requires admin rights. If that elevation is refused or
the setup evidence is not applied GO, the user must finish later from Hub
Manager. This is still not public Hub readiness: it configures the existing
Docker/Compose stack behind a manager-facing surface and records evidence that
real agency setup is still NO-GO while the runtime depends on manually
available Docker Desktop.
`-ValidateOnly` is planning evidence only: it may report
`foundation_plan_status=GO`, but it must not report applied setup GO and its
`proof_result` remains NO-GO. Applied Hub foundation proof requires the friendly
Hub identity file to be written, the ProgramData config/data/logs/runtime
directories to be created or already safe, Caddy/front-door config to be
present, and a verified Private-profile Windows Firewall rule for the Caddy
front-door port when LAN access is enabled. If `-NoLanAccess` is selected, the
firewall evidence is `skipped_local_only` and the front door is local-only.
Hub foundation GO is not agency install GO.
`scripts/detect_hub_runtime.ps1` records that distinction as
`manual_docker_desktop`, `managed_container_runtime`, `native_windows_services`,
or `unavailable`. It reads the managed provider contract at
`C:\ProgramData\ImmoApp\config\hub_runtime_provider.json` when present and
refuses invalid provider config instead of silently falling back to Docker
Desktop in Hub evidence.

A provider JSON alone is not trust. Production agency GO requires the canonical
ProgramData provider config path, `provider_mode=managed_container_runtime`, a
non-proof provider under approved ProgramData runtime/data/log paths, hidden
from the operator, with no symlinks/junctions/reparse points and runtime plus
Compose version checks passing. Test or app-data override roots are internal
proof only and force `noncanonical_runtime_root`.

The internal WSL2 bridge is represented separately. `install-runtime-candidate`
records WSL policy/config-plan proof only. `install-runtime-artifact` builds and
registers the first ImmoApp-owned artifact under
`C:\ProgramData\ImmoApp\runtime`. While this mode is active, Hub Manager
`start`, `status`, `health`, and `logs` call only the managed artifact bridge
for the fixed `ImmoAppRuntime` WSL distribution command path; it does not
silently fall back to the repo Docker stack or manual Docker Desktop. Runtime
start GO still requires `bootstrap_managed_wsl2_runtime.ps1` evidence proving
the expected distro identity, container engine GO, and Compose GO, then fresh
managed start evidence plus Caddy/front-door health and identity marker proof.
The operational proof order is: stop the repo/dev stack, run `wsl --shutdown`
only when explicitly requested by the WSL config planner, install/register the
artifact, start through Hub Manager, then collect status, health, support, and
network-boundary evidence.
Production managed runtime proof also requires schema-v2 package inventory,
package artifact SHA-256 verification,
installed runtime/Compose executable hashes matching inventory critical
executables, required 40-character lowercase source provenance, no forbidden
package content, non-zero file/byte counts, and no secret/token/password/private
key fields. Proof-only providers, non-canonical provider paths, native service
self-declarations, and repo-dev Hub script paths are internal proof only.
External runtime artifacts additionally require a validated
`immoapp_managed_runtime_vendor_provenance` manifest with license, artifact
hash/bytes, extracted inventory hash, approval reason, matching source commit,
and `approved_by_immoapp=true`; without it they remain NO-GO for agency proof.

Supported roles:

- `HubDesktop`: prepare the local office Hub plus desktop on the Hub machine.
  The wrapper requires a friendly Hub display name, writes `hub_identity.json`,
  enables the `hub-front-door` Caddy profile, sets `DJANGO_DEBUG=0`, keeps the
  backend direct port localhost/internal, generates the Hub runtime profile,
  can start the Hub when explicitly requested, can create Hub Manager
  shortcuts, and can apply/verify only the Caddy front-door firewall rule on
  Private networks. The installer foundation path writes applied setup evidence
  but does not claim agency readiness while the hidden managed runtime is
  missing.
- `WorkstationOnly`: verify a non-localhost Hub front-door URL and write the
  desktop API endpoint. Localhost is rejected unless the user explicitly
  chooses the local-Hub-on-this-computer path. It does not start backend
  services or require a local backend runtime.
- `HubOnly`: future packaging role. It is documented but not agency-ready in
  M1.

`ImmoApp Hub Manager.exe` is the user-facing Hub Manager installed for Hub
roles. It exposes friendly actions for `start`, `stop`, `restart`, `status`,
`health`, `logs`, `support`, `backup-now`, `open-desktop`, `copy-url`, and
`rename-hub`. The app delegates to the audited `scripts/hub_manager.ps1`
control plane internally; operators should use the app or installer-created app
shortcuts, not raw PowerShell or Compose commands.

LAN Hub mode exposes only Caddy as the Hub front door. Caddy proxies internally
to the backend web service. The backend direct port, Database, RabbitMQ, Valkey,
OpenBao, MinIO API/console, and ClamAV ports remain localhost/internal bindings
in Compose. Local HTTP is allowed for private LAN beta evidence only;
HTTPS/certificate automation remains a later milestone and blocks public beta.

Hub identity lives at `C:\ProgramData\ImmoApp\config\hub_identity.json`. Normal
UI shows the user-friendly Hub display name. Hostname and IP are read-only
technical diagnostics only, and setup never changes the Windows machine
hostname.

`scripts/register_managed_hub_runtime_provider.ps1` is a proof/staging helper
for the next packaging phase. It registers an explicit ImmoApp-owned hidden
container runtime provider config; it does not install Docker Desktop and it
must not be used to label a user-visible runtime as managed. Caddy/proxy ingress
is disabled by default behind a future profile and remains localhost-only until
HTTPS/certificate policy is implemented.

`scripts/verify_hub_network_boundary.ps1` records JSON evidence that Caddy is
the only approved LAN-facing service and that backend/internal and infra ports
are localhost/internal.
The evidence separates API availability from boundary safety:
`web_health_unreachable` means the Hub API was down, while `infra_exposed`
means a non-web service was published to LAN. Its default
`proof_scope=local_compose_boundary` is not a second-machine LAN proof.

`scripts/verify_hub_m1_local_proof.ps1` collects local runtime/setup/status,
support bundle, and GO/NO-GO evidence. By default, and with `-ValidateOnly`, it
does not start services. `-StartHubForProof` may start the local Hub for
internal proof through the approved manager/start path, but manual Docker
Desktop still keeps agency install NO-GO. It does not synthesize real LAN
proof: a second workstation, VM, or isolated network namespace must prove access
using the Hub IP/hostname before LAN GO. Backup/restore evidence is required for
Hub beta GO; missing restore evidence remains NO-GO.

Managed runtime package proof starts with
`scripts/build_managed_hub_runtime_package.ps1`,
`scripts/install_managed_hub_runtime_provider.ps1`, and
`scripts/verify_managed_hub_runtime_provider.ps1`. If no hidden runtime artifact
is supplied, the package proof records `managed_runtime_artifact_missing` and
remains NO-GO instead of pretending Docker Desktop is managed. Proof-only
providers can validate command paths but keep `agency_install_status=NO_GO`.
Production provider installation requires schema-v2 package inventory evidence;
without inventory the registration helpers force proof-only or fail instead of
creating an agency-ready provider. The install helper is deprecated and
delegates to the register helper so there is one provider-writing validation
path.

`scripts/prepare_managed_hub_runtime_prototype.ps1` is the next-phase scaffold.
It prepares or validates the canonical ProgramData runtime/config/data/log
directories with explicit confirmation and stays NO-GO until a real hidden
runtime executable plus Compose-capable command exists under
`C:\ProgramData\ImmoApp\runtime\`.

## Canonical clean-machine sequence

Do not start a clean machine with `dev_reset.ps1`.

Use this sequence instead:

1. `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap_local_runtime.ps1`
2. Edit `C:\ProgramData\ImmoApp\config\.env.local`
3. `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-infra -UseWindowsVolumes`
4. `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_openbao_identity.ps1`
5. `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action sync-secrets -UseWindowsVolumes`
6. `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action db-prepare -UseWindowsVolumes`
7. `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-app -UseWindowsVolumes`

`stack.ps1 -Action up` is a supported steady-state shorthand after bootstrap,
not the canonical first clean-machine step.

## Public stack commands

Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-infra -UseWindowsVolumes
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action sync-secrets -UseWindowsVolumes
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action db-prepare -UseWindowsVolumes
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-app -UseWindowsVolumes
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up -UseWindowsVolumes
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action restart-app -UseWindowsVolumes
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action ps -UseWindowsVolumes
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action logs -UseWindowsVolumes
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action down -UseWindowsVolumes
```

## Action meanings

- `up-infra`: start db/rabbitmq/valkey/minio/clamav/openbao and run
  `openbao-init` + `openbao-seed`
- `sync-secrets`: validate the local bootstrap JSON, re-seed OpenBao from local
  bootstrap material, and restart only app services
- `db-prepare`: run the canonical DB/schema/security preparation step
- `up-app`: start app services on top of a ready infra stack
- `up`: full local shorthand for infra + build + db-prepare + app start
- `restart-app`: restart only app services against the existing infra/OpenBao
  state
- `ps`: show current compose service status
- `logs`: follow app logs
- `down`: stop the local stack

## Runtime data used by the stack

Docker-local Windows bind volume mode uses these ProgramData paths:

- `C:\ProgramData\ImmoApp\data\pgdata`
- `C:\ProgramData\ImmoApp\data\rabbitmq`
- `C:\ProgramData\ImmoApp\data\valkey`
- `C:\ProgramData\ImmoApp\data\minio`
- `C:\ProgramData\ImmoApp\data\clamav`
- `C:\ProgramData\ImmoApp\data\caddy\data`
- `C:\ProgramData\ImmoApp\data\caddy\config`
- `C:\ProgramData\ImmoApp\data\app`

App containers see `C:\ProgramData\ImmoApp\data\app` as `/var/lib/immoapp`.

Two local Docker-managed named volumes remain outside ProgramData:

- `openbao_data`
- `openbao_logs`

## Env and bootstrap assumptions

`stack.ps1` expects:

- canonical env file: `C:\ProgramData\ImmoApp\config\.env.local`
- operator-edit placeholders resolved before `up*`, `db-prepare`,
  `restart-app`, or `sync-secrets`
- canonical bootstrap JSON: `C:\ProgramData\ImmoApp\secrets\immoapp-dev-secrets.json`

If the env file or bootstrap JSON is missing, run
`scripts/bootstrap_local_runtime.ps1` first.

## Native desktop E2E backend freshness

Native desktop E2E does not trust a running Docker backend blindly. The runner
enables E2E mode for orchestration, then verifies the authenticated local-only
identity endpoint:

```text
GET /api/v1/e2e/runtime/identity/
```

The identity check compares the current checkout against product backend source
inside the running backend container and, for image-mode backends, the Docker
build identity stamped into the image. If the code is stale or E2E mode is
disabled, `scripts/test_e2e_desktop.ps1` fails before launching the desktop app.
Expected preflight failures print a concise operator error instead of a Python
traceback.

When E2E mode is disabled, all `/api/v1/e2e/...` routes return 404 before
authentication. The service owner also self-gates E2E runtime controls so stale
Redis state cannot fault normal authenticated API requests.

Supported modes:

- Default: verify identity mandatorily, then fail fast on mismatch.
- `-EnsureBackend`: recreate/start the existing stack with E2E mode enabled,
  without rebuilding images.
- `-RebuildBackend`: rebuild and restart the local backend image from this
  checkout before verification. This is the preferred green path.
- `-ApiTimeoutSeconds`: validated desktop client API timeout, defaulting to 12
  seconds with an accepted range of 3 to 60 seconds.

Do not manually copy backend files into containers for product desktop E2E.
Copied-file synced-container mode is rejected; rebuild the backend image so the
Docker build identity is stamped from this checkout.

Full and release validation also audit the resolved dependency inventory from
the Docker backend image as `docker-backend`, in addition to the host server and
client inventories. The Docker inventory comes from `python -m pip freeze --all`
inside the image and is audited without dependency resolution.

## Native desktop E2E runner readiness

Backend freshness is not enough for native desktop E2E. The Windows runner also
needs enough interactive desktop, memory, commit/page-file, disk, Python, and
Docker capacity to launch PySide6 and pywinauto reliably.

Check the runner without mutation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/reset_e2e_environment.ps1 -Mode check -RequireInteractiveDesktop -WarnFreeMemoryGb 6 -MinCriticalFreeMemoryGb 1 -MinCommitHeadroomGb 2
```

Run a safe targeted reset before heavy release/E2E validation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/reset_e2e_environment.ps1 -Mode reset -CleanArtifacts -KillStaleDesktopProcesses -RequireInteractiveDesktop -WarnFreeMemoryGb 6 -MinCriticalFreeMemoryGb 1 -MinCommitHeadroomGb 2
```

Reset mode only removes E2E-owned paths such as `.tmp/desktop_e2e_artifacts`,
repo pytest cache when requested, and explicitly named E2E temp children. It
only stops stale E2E processes after command-line ownership proves they belong
to this repo and the desktop E2E runner. It does not delete broad system temp
directories, does not delete `C:\ProgramData\ImmoApp`, and does not kill generic
Python, PowerShell, or Docker processes by name. Artifact cleanup keeps children
newer than `-ArtifactRetentionDays`; use `-ArtifactRetentionDays 0` only for an
explicit full artifact-tree cleanup. If Windows cannot provide command-line
process ownership data, reset mode reports a warning and leaves processes alone.

The canonical release-style lane is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_e2e_release_validation.ps1
```

That wrapper resets the runner, rebuilds the backend once, and runs the broad
nightly suite. Nightly includes smoke-marked tests, so release E2E does not run
smoke twice. Native desktop E2E remains outside `checks.ps1 -Stage pr`.

Its reset step stops stale desktop and stale E2E server/preflight processes
only when command-line ownership proves they belong to this repo.

Recommended local runner baseline:

- 6 GB free physical memory is a warning threshold, not a hard requirement
- 1 GB free physical memory is the default critical hard-failure threshold
- 2 GB or more commit/page-file headroom before starting native E2E
- 20 GB or more free disk on the repo and Docker/data drive
- Windows page file enabled so commit limit is not tight during Docker rebuilds
- Fresh interactive desktop resources before release validation

The hard gates are PowerShell/server Python/client Python/client Qt import spawn
canaries, critical free RAM, commit/page-file headroom, disk shortage, Docker
availability when Docker actions are requested, backend identity, and interactive
desktop availability when requested. Low physical free RAM below 6 GB only emits
a warning unless it is below the critical threshold.

If preflight still fails after targeted reset, close unrelated applications,
restart Docker Desktop, increase the Windows page file, or reboot before running
the release/E2E lane.

## Secret sync

The supported local secret-edit path is:

1. Edit `C:\ProgramData\ImmoApp\secrets\immoapp-dev-secrets.json`
2. Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action sync-secrets -UseWindowsVolumes
```

Do not use ad hoc scripts for incremental local secret updates.

## Recovery and reset

Supported answers:

- Re-seed OpenBao after editing local bootstrap JSON:
  `scripts/stack.ps1 -Action sync-secrets -UseWindowsVolumes`
- Restart app services only:
  `scripts/stack.ps1 -Action restart-app -UseWindowsVolumes`
- Reset dirty local app data on an already bootstrapped machine:
  `scripts/dev_reset.ps1 -UseWindowsVolumes`
- Repair stale/broken Windows bind volume mappings:
  `scripts/fix_windows_volume_bind_mismatch.ps1 -EnvFile C:\ProgramData\ImmoApp\config\.env.local`
- Heavy infra recovery:
  `scripts/infra_recover.ps1`

Bootstrap and reset are different operations:

- `bootstrap_local_runtime.ps1` creates declared runtime state on a clean or
  partially prepared machine
- `dev_reset.ps1` is destructive local reset/recovery on an already
  bootstrapped machine

## Direct compose usage

Direct `docker compose` is supported only for developer debugging of Compose
behavior itself. Hub setup/status/release scripts must use the runtime detector
and shared Hub runtime helpers so a managed provider can replace Docker Desktop
without duplicating thresholds or runtime calculators.

Example:

```powershell
docker compose --project-directory . -f deployment/compose/compose.yml -f deployment/compose/compose.windows.yml up -d
```

## Managed WSL2 Container Runtime Candidate

The WSL2/container runtime path is the internal beta bridge for the next Hub
runtime candidate. It can generate policy/config evidence and register a
proof-only `managed_wsl2_container_runtime_candidate` provider, but it still
does not install WSL, create a distribution, install a container engine, or make
agency GO.

Use the planner:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\managed_wsl2_runtime_policy.ps1 -PlanOnly -OutputJson .tmp\managed_wsl2_policy_plan.json
```

Use the config wrapper only as a dry-run unless you intend to change the current
Windows user's global WSL config:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\configure_managed_wsl2_runtime.ps1 -PlanOnly -OutputJson .tmp\managed_wsl2_config_plan.json
```

Register the internal proof-only candidate through Hub Manager:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\hub_manager.ps1 -Action install-runtime-candidate -ConfirmInstallRuntimeCandidate
```

The registered provider records both the policy JSON and the `.wslconfig` plan
JSON with SHA-256 hashes and matching sizing fields. Candidate evidence is
registration-only: `candidate_registration_status=GO` does not mean a runtime
artifact exists or can start. `detect_hub_runtime.ps1` can then report
`runtime_dependency_mode=managed_wsl2_container_runtime_candidate`, but Hub
Manager start remains NO-GO with `managed_wsl2_runtime_artifact_missing` until a
real ImmoApp-owned WSL2/container runtime artifact exists.

Remove the proof-only provider without deleting data:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\hub_manager.ps1 -Action remove-runtime-candidate
```

`install-runtime-candidate` refuses to overwrite a non-candidate provider. If a
real managed provider already exists, it reports
`existing_managed_runtime_provider_refuses_candidate_overwrite` and preserves the
provider config unchanged.

Important constraints:

- `%UserProfile%\.wslconfig` is global for that Windows user's WSL2
  distributions.
- `memory` and `processors` are ceilings, not reservations.
- `swap` is bounded; ImmoApp does not create large implicit swap.
- `autoMemoryReclaim` defaults to `gradual`.
- `.wslconfig` changes may require `wsl --shutdown`, but the wrapper runs it
  only with explicit `-ApplyShutdown`.
- Hub minimum RAM is the normalized 8 GB installed-RAM class. Windows-reported
  7.5 GB through 8 GB normalizes to the 8 GB class; below 7.5 GB is
  workstation-only. Windows-reported 15.x GB normalizes to the 16 GB class.
- Runtime profile envelope participates in sizing when supplied: the WSL cap is
  bounded by the lower of machine tier and Hub runtime profile.
- WSL policy evidence records whether that envelope came from explicit input,
  default ProgramData config, or machine capacity only, including path, SHA-256,
  status, and error fields. Invalid profile JSON or unsupported profile names
  are `NO-GO`.
- CPU is part of machine tier selection: 1-2 logical processors=tiny, 3-4=small,
  5-7=medium, 8+=large. A 32 GB machine with 2 CPUs is not a large Hub.
- Managed runtime/debug logs are kept under
  `C:\ProgramData\ImmoApp\logs\managed-runtime\` and may be cleaned with Hub
  Manager's 14-day / 536870912-byte default retention policy. This cleanup is
  operational only; security/audit logs and support bundles are separate and are
  not handled by this action.
- Raw free RAM is diagnostics/live pressure only, not profile sizing input.
- A WSL policy file is passive. It does not change active runtime behavior until
  an explicit verified provider config activates the WSL candidate mode.
- Duplicate `[wsl2]` sections or duplicate managed keys in `.wslconfig` require
  manual cleanup; ImmoApp does not guess which shadowed setting is authoritative.

Manual Docker Desktop remains internal proof only. A WSL2 policy/config/provider
GO is not a managed runtime artifact and remains agency `NO-GO`.
