# Scripts Inventory

This folder contains both supported entrypoints and internal helpers. They are
not all equal.

## Hub Runtime Profile

- `hub_runtime_profile.py generate|print|validate|export-env` owns Hub/backend capacity detection
  and startup exports.
- `verify_small_hub_runtime_profile.py` simulates a tiny/small Hub and proves reduced worker,
  import, match, and DB pool limits without requiring weak hardware.
- `stack.ps1` calls the profile generator before app services start, so Docker/Celery concurrency
  comes from one central governor rather than hand-tuned worker counts.

The profile is a safety governor, not a performance optimizer. It prevents hidden 12-core-machine
assumptions and records evidence for support bundles and beta proof summaries. Baseline sizing uses
CPU, total RAM, and container limits; Windows free RAM only contributes to temporary green/yellow/red
pressure clamps.

## Supported Public Entry Points

Use these first.

Read in this order when you are orienting yourself:

1. `README.md`
2. `docs/guides/CLEAN_MACHINE_BOOTSTRAP.md`
3. `docs/guides/RUNTIME_AUTHORITY.md`
4. `docs/guides/STACK.md`
5. `docs/guides/OPENBAO_SETUP.md`

- `scripts/bootstrap_local_runtime.ps1`: canonical clean-machine bootstrap entrypoint
  Creates the declared `C:\ProgramData\ImmoApp` layout, initializes the canonical env file, creates the local bootstrap JSON when missing, and provisions the server/client venvs
- `scripts/stack.ps1`: canonical Docker lifecycle entrypoint
  Important actions: `up`, `up-infra`, `up-app`, `restart-app`, `sync-secrets`, `down`
- `scripts/setup_office_hub.ps1`: Hub Beta Milestone 1 setup wrapper
  Supports `HubDesktop`, `HubOnly`, and `WorkstationOnly`. It hides stack/profile/env details behind a setup surface, configures
  LAN API binding for Hub mode, rejects localhost workstation URLs, creates
  optional Hub Manager shortcuts, and records that manual Docker Desktop
  dependency is internal-beta only and real agency install NO-GO until the
  runtime is managed.
- `scripts/detect_hub_runtime.ps1`: read-only Hub runtime packaging probe
  Emits `immoapp_hub_runtime_detection` JSON and classifies the runtime as
  `manual_docker_desktop`, `managed_container_runtime`, `native_windows_services`,
  or `unavailable`. Manual Docker Desktop is always agency NO-GO. A managed
  runtime is accepted only through the strict ProgramData provider config and
  verified runtime/Compose checks; invalid provider config is NO-GO and does
  not silently fall back to Docker Desktop. A provider JSON alone is not trust:
  production agency GO also requires approved ProgramData roots, hidden
  ImmoApp-owned runtime paths, a verified package inventory, matching package
  SHA-256/provenance, no forbidden package content, and no secret-bearing
  provider fields.
- `scripts/register_managed_hub_runtime_provider.ps1`: staging/proof helper for
  registering `C:\ProgramData\ImmoApp\config\hub_runtime_provider.json` after an
  ImmoApp-owned hidden runtime exists. It requires explicit confirmation and
  refuses user-visible Docker Desktop paths. Without a verified package
  inventory it writes only a proof-only provider, which remains agency NO-GO.
- `scripts/build_managed_hub_runtime_package.ps1`: creates schema-v2 managed
  runtime package inventory evidence from an explicit file list and verifies the
  ZIP entries before it can emit GO. With no hidden runtime source it writes
  `managed_runtime_artifact_missing` and remains NO-GO rather than faking a
  managed runtime. The shared scanner rejects child symlinks/junctions,
  forbidden package content, unsafe paths, and empty proof trees; ZIP proof is
  bounded by file count, total bytes, single-file bytes, and compression ratio.
- `scripts/create_managed_runtime_vendor_provenance.ps1` and
  `scripts/verify_managed_runtime_vendor_provenance.ps1`: create and verify the
  vendor/runtime provenance manifest required before an external runtime
  artifact can become agency-eligible. The manifest records vendor, runtime,
  license, license distribution approval, license review status, artifact
  hash/size, safe ZIP extracted inventory hash, approval reason, approver,
  approval timestamp, and source commit. ZIP entries are checked for traversal,
  duplicates, unsafe names, reparse points, and forbidden/secret content. The
  script does not install or sign the runtime by itself.
- `scripts/prepare_managed_hub_runtime_prototype.ps1`: creates or validates the
  canonical ProgramData runtime/config/data/log scaffold for the next managed
  runtime prototype. It does not write an agency-ready provider; without a real
  hidden runtime and Compose-capable command it reports
  `managed_runtime_artifact_missing`.
- `scripts/build_managed_wsl2_runtime_artifact.ps1`: builds the first
  ImmoApp-owned internal WSL2/container artifact layout under
  `C:\ProgramData\ImmoApp\runtime` (or the explicit test ProgramData root) and
  writes a strict inventory. The artifact includes managed start/status wrapper
  scripts that call the fixed `ImmoAppRuntime` WSL distribution command path;
  they do not resolve repo Docker, manual Docker Desktop, or arbitrary PATH
  Docker tools. Startup is proven only by
  `bootstrap_managed_wsl2_runtime.ps1` identity evidence plus fresh
  `managed_wsl2_runtime_start_evidence.json` with service status GO,
  Caddy/front-door health, and identity marker GO. This remains agency/public
  beta NO-GO.
- `scripts/bootstrap_managed_wsl2_runtime.ps1`: read-only verifier for the
  active managed WSL2 artifact provider. It checks approved WSL executable
  availability, exact `ImmoAppRuntime` distro presence, runtime identity JSON,
  container engine status, and Compose status. It never installs WSL, imports a
  distro, or shuts WSL down silently.
- `scripts/build_managed_wsl2_runtime_rootfs.ps1`: overlays the required
  `/opt/immoapp/runtime/bin/*` command files onto an explicitly supplied local
  base rootfs tar and writes an importable `ImmoAppRuntime` rootfs tar under the
  approved ProgramData runtime root. It does not download or infer a distro and
  records runtime/start/agency/public beta as `NO-GO` until the imported distro,
  container engine, Compose path, and live Caddy/front-door proof are real.
- `scripts/build_official_managed_wsl2_runtime_rootfs.ps1`: builds the first
  internal `ImmoAppRuntime` rootfs from the official Ubuntu 24.04 LTS minimal
  amd64 rootfs on `cloud-images.ubuntu.com`. It downloads the source rootfs under
  `C:\ProgramData\ImmoApp\runtime\rootfs\sources`, verifies SHA-256, imports a
  temporary `ImmoAppRuntimeBuild` distro only when `-ConfirmBuild` is supplied,
  installs Docker Engine and the Compose plugin inside that build distro,
  configures Docker log rotation (`max-size=10m`, `max-file=5`), exports
  `C:\ProgramData\ImmoApp\runtime\rootfs\ImmoAppRuntime.rootfs.tar`, unregisters
  the temporary build distro unless `-KeepBuildDistro` is supplied, and runs the
  existing import script in `-PlanOnly` mode. It does not perform the final
  `ImmoAppRuntime` import or claim runtime start, agency, or public beta GO.
- `scripts/import_managed_wsl2_runtime_distro.ps1`: plan-first scaffold for
  importing the real `ImmoAppRuntime` WSL distribution under
  `C:\ProgramData\ImmoApp\runtime\wsl\ImmoAppRuntime`. It requires an explicit
  rootfs tar path containing the required ImmoApp runtime commands, defaults to plan-only unless
  `-ConfirmImportManagedWslRuntime` is supplied, refuses to replace an existing
  `ImmoAppRuntime` distro unless `-ConfirmReplaceExistingDistro` is also
  supplied, and records JSON evidence without claiming runtime start, agency, or
  public beta GO.
  Next operator sequence, once an approved local base rootfs tar is available:
  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_managed_wsl2_runtime_rootfs.ps1 -BaseRootfsTarPath <explicit-tar> -OutputRootfsTarPath C:\ProgramData\ImmoApp\runtime\rootfs\ImmoAppRuntime.rootfs.tar
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\import_managed_wsl2_runtime_distro.ps1 -RootfsTarPath C:\ProgramData\ImmoApp\runtime\rootfs\ImmoAppRuntime.rootfs.tar -PlanOnly
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\import_managed_wsl2_runtime_distro.ps1 -RootfsTarPath C:\ProgramData\ImmoApp\runtime\rootfs\ImmoAppRuntime.rootfs.tar -ConfirmImportManagedWslRuntime
  ```
  The final import command is not run until explicitly requested; the current
  blocker is selecting/providing that approved base rootfs tar.
- `scripts/hub_manager.ps1 -Action cleanup-runtime-logs`: bounded cleanup for
  managed runtime/debug logs under
  `C:\ProgramData\ImmoApp\logs\managed-runtime\`. Defaults are 14 days and
  536870912 bytes (512 MB). It deletes only managed runtime log-like files in
  that dedicated folder, writes `managed_runtime_log_retention.json`, and does
  not handle security/audit logs, support bundles, config, data, backups, or
  runtime binaries.
- `scripts/run_managed_runtime_candidate_proof.ps1`: orchestrates the next-phase
  candidate proof for a real runtime ZIP. It creates vendor provenance, builds
  package inventory, attempts provider registration/detection, and records
  missing proof tracks. Without a ZIP it emits `NO-GO` with
  `runtime_zip_candidate` missing. With a candidate it snapshots and restores the
  existing provider config by default; permanent promotion requires
  `-PromoteCandidateProvider`, `-ConfirmPromoteManagedRuntime`, and every proof
  phase to be GO. It never relabels Docker Desktop as managed.
- `scripts/install_managed_hub_runtime_provider.ps1`: deprecated compatibility
  wrapper that delegates to `register_managed_hub_runtime_provider.ps1` so there
  is only one provider-writing validation path. Production providers require
  canonical ProgramData config, inventory v2, package SHA/provenance checks, and
  installed runtime/Compose hashes matching inventory critical executables.
- `scripts/verify_managed_hub_runtime_provider.ps1`: verifies the provider
  through the central runtime detector and reports internal proof status versus
  agency status.
- `scripts/hub_manager.ps1 -Action install-runtime-artifact
  -ConfirmInstallRuntimeArtifact`: internal proof lane that generates WSL
  policy/config evidence, builds the WSL2 artifact inventory, registers the
  artifact provider, and keeps agency/public beta NO-GO. `start`, `status`,
  `health`, and `logs` use the artifact bridge while that provider is active;
  no silent fallback to repo Docker or manual Docker Desktop is allowed.
- `scripts/set_hub_identity.ps1` and `scripts/get_hub_identity.ps1`: write/read
  the friendly Hub display name under ProgramData. These scripts validate the
  name, use safe JSON writes, and never mutate the Windows hostname.
- `app/hub_manager_app.py`: source for the installed `ImmoApp Hub Manager.exe`
  user-facing app. The app is bundled only for Hub-capable installs and wraps
  the audited Hub Manager script with friendly actions and JSON evidence.
- `scripts/hub_manager.ps1`: internal Hub Manager command surface used by the
  app and installer shortcuts. Supports `start`, `stop`, `restart`, `status`,
  `health`, `logs`, `support`, `backup-now`, `open-desktop`, `copy-url`, and
  `rename-hub`, delegating to existing stack, backup, support bundle, identity,
  and runtime profile tools rather than duplicating backend runtime logic.
- `scripts/collect_hub_install_evidence.ps1` and
  `scripts/collect_hub_status_evidence.ps1`: structured Hub M1 evidence helpers
  for setup/install status, runtime dependency mode, LAN binding, health,
  profile, support bundle, data path, and GO/NO-GO reasons.
- `scripts/verify_hub_beta_m1_evidence.ps1`: GO/NO-GO aggregator for the first
  Hub milestone. It requires Hub install/status evidence, workstation LAN
  reachability, workstation product proof, backup/restore proof, support bundle,
  installed inventory, and install lifecycle evidence.
- `scripts/verify_hub_m1_local_proof.ps1`: local-only proof runner for the Hub
  wrapper/status surface. `-ValidateOnly` is the safe default and does not start
  services. `-StartHubForProof` may start the Hub for internal proof through the
  approved manager path, but manual Docker Desktop still leaves agency install
  NO-GO. Validate-only records any already-running Hub as
  `observed_existing_hub_status`; startup proof is only `started_hub_status`
  under `-StartHubForProof`. It does not turn synthetic LAN placeholders into
  real workstation proof.
- `scripts/run_hub_discovery_beacon.ps1` and
  `scripts/collect_hub_discovery_evidence.ps1`: dependency-light LAN discovery
  MVP. Discovery advertises the Hub display name and Caddy front-door URL only;
  secrets and internal service ports are forbidden.
- `scripts/verify_hub_network_boundary.ps1`: JSON proof that only Caddy may be
  LAN-facing and backend/internal/DB/storage/cache/queue/secrets ports remain
  localhost/internal. It separates `web_health_unreachable` from infra LAN
  exposure. This is `proof_scope=local_compose_boundary` and cannot satisfy real
  workstation LAN proof without second-machine/VM evidence.
- `scripts/dev_reset.ps1`: destructive reset/recovery on an already bootstrapped Docker-local machine
- `scripts/run_client.ps1`: desktop Qt client runtime
  Defaults to `https://localhost` and supports `-BaseUrl` for explicit endpoint override
- `scripts/run_server.ps1`: host-local Django debug runtime
- `scripts/test_e2e_desktop.ps1`: canonical Windows-native desktop E2E runner
  Supports `-Suite smoke|nightly`, verifies backend identity before desktop
  launch, and provides `-RebuildBackend`. Copied-file synced-container mode is
  rejected for product E2E. It also runs the runner environment preflight before
  backend rebuild/identity checks unless the runner preflight is explicitly
  disabled. Backend identity verification itself is mandatory. The desktop API
  timeout is explicit through `-ApiTimeoutSeconds` and defaults to 12 seconds.
- `scripts/reset_e2e_environment.ps1`: native desktop E2E runner reset/preflight
  Checks Windows interactive desktop readiness, local Python/Docker/resource
  health, safe artifact cleanup, and stale E2E process ownership. `-Mode check`
  is report-only; `-Mode reset` mutates only explicitly owned E2E paths/processes.
  The runner warns below 6 GB free RAM but hard-fails only on critical free RAM,
  low commit/page-file headroom, disk shortage, or required spawn canary failure.
- `scripts/run_e2e_release_validation.ps1`: release-oriented native desktop E2E
  wrapper that resets the runner, rebuilds the backend once, runs the broad
  nightly suite through `scripts/test_e2e_desktop.ps1`, then runs a required
  resolved-inventory dependency audit for the Docker backend image. The nightly
  suite includes smoke-marked tests, so smoke is not run twice.
- `scripts/run_beta_release_validation.ps1`: strict beta release validation
  orchestrator. It writes JSON and text summaries under
  `.tmp/beta_release_validation/<timestamp>/`, verifies repo/tooling hygiene,
  verifies required Hub runtime services plus `http://127.0.0.1:8000/api/v1/health/`,
  runs backup plus isolated restore proof, runs `scripts/run_e2e_release_validation.ps1`,
  runs `checks.ps1 -Stage pr` and `checks.ps1 -Stage full`, and attempts the
  installer build only when Git and Inno Setup are available. Fresh-machine and
  LAN Hub/workstation phases require structured evidence JSON; missing evidence
  is recorded as NO-GO. Internal validation artifacts stay under `.tmp`, while
  tester-facing release artifacts are copied after a successful installer build
  to `C:\ProgramData\ImmoApp\release_artifacts\beta\<commit-sha-short>\` by
  default. Use `-ReleaseArtifactRoot` to choose another non-repo root,
  `-AllowReplaceReleaseArtifacts` to replace only the current commit-specific
  stable artifact folder, and `-CleanPreviousValidationArtifacts` to delete only
  approved repo-local generated validation residue before a rerun. The cleanup
  option never deletes ProgramData runtime data, DB backups, Docker volumes,
  MinIO data, arbitrary temp folders, or the stable release artifact root.
  `repair_local_dev_release_integrity.ps1` is never called by release validation.
- `scripts/verify_lan_workstation_reachability.ps1`: read-only workstation
  reachability proof helper for LAN beta evidence. It calls
  `<HubBaseUrl>/api/v1/health/`, records machine/network/DNS details and
  TCP connectivity details, optional identity endpoint information when
  available, writes JSON proof when `-OutputJson` is supplied, and does not call
  mutation routes. Use `-RequireWorkstationUrl` for LAN proof so localhost Hub
  URLs are rejected.
- `scripts/collect_installed_app_inventory.ps1`: machine-verifiable installed
  desktop inventory. It requires the install location, proves `ImmoApp.exe`,
  the Inno uninstaller, and Windows uninstall registry entry exist, hashes every
  installed file, reads build identity when present, and fails if source,
  backend, test, docs, scripts, Docker, database, backup, or release-artifact
  paths are installed.
- `scripts/collect_install_lifecycle_evidence.ps1`: record-only evidence helper
  for install, uninstall, and reinstall observations. It uses strict
  `-Mode post_install`, `post_uninstall`, `post_reinstall`, and
  `combined_manual` phases. `post_uninstall` must observe the uninstall registry
  and installed executable absent; a final installed state cannot prove
  uninstall happened. It does not automate destructive uninstall behavior.
- `scripts/collect_fresh_machine_install_evidence.ps1`: structured fresh
  Windows profile/VM evidence helper. It verifies installer SHA-256, installed
  executable, backend health, support bundle, installed inventory, and lifecycle
  evidence. It refuses silent install path guessing: pass
  `-InstalledInventoryJson` for GO evidence, or an explicit `-InstalledExePath`
  for weaker debug/operator evidence that the beta wrapper will not accept for
  full GO. A localhost backend URL is recorded as Hub/local proof only, never
  workstation proof.
  Local evidence paths are verified on the current machine. Remote evidence
  must set `remote_evidence=true` and carry hashes plus embedded or hash-recorded
  inventory/lifecycle/reachability proof; remote paths alone are not GO proof.
- `scripts/write_manual_product_proof_evidence.ps1`: converts observed manual
  owner login, CRUD, and offer-photo-thumbnail proof into structured evidence.
  It requires explicit confirmation switches and a support bundle path.
- `scripts/collect_lan_workstation_evidence.ps1`: structured LAN workstation
  evidence helper. It consumes reachability proof generated by
  `verify_lan_workstation_reachability.ps1`, rejects localhost Hub/desktop URLs,
  requires support bundle evidence, and records owner login, CRUD, photo
  thumbnail, Hub backup/restore, and uninstall/reinstall status.
- `scripts/prepare_local_beta_client.ps1`: resets the desktop client to the
  local beta owner-account flow (`http://127.0.0.1:8000`, `owner`) and clears
  persisted admin/owner sessions before manual smoke.
- `scripts/build_desktop_installer.ps1`: deterministic Windows beta installer
  build. It requires a clean tracked worktree, PyInstaller 6.20.0 from
  `requirements/packaging.txt`, and Inno Setup 6 stable. Version 6.7.1 is the
  preferred pinned compiler for beta evidence, but the script accepts reliable
  Inno Setup 6 detection when Windows metadata is `0.0.0.0` or help output omits
  the patch version. Use `GIT_EXE` when Git is not on `PATH`, and
  `INNO_SETUP_ISCC` when ISCC is not on `PATH`; user-local installs under
  `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe` are discovered automatically.
  `-WhatIfToolCheckOnly` verifies Git, ISCC, and clean-worktree status without
  creating a build venv, running PyInstaller, or compiling an installer.
  `-KeepPyInstallerOutput` preserves the temporary PyInstaller dist/build root
  for inspection. `-InspectBundleOnly` builds and inventories the PyInstaller
  one-folder output without compiling the Inno installer.
  Public beta installers are named `ImmoApp-Beta-<version>-Setup.exe` and
  default to `C:\ProgramData\ImmoApp\release_artifacts\desktop_installer\<commit>\`.
  Repo-local output is developer-only and requires
  `-AllowRepoLocalReleaseArtifacts` unless it is under `.tmp` for internal
  validation. Commit SHA,
  installer SHA-256, and build identity are recorded in the adjacent
  `.summary.json`. The build also writes an
  `immoapp_installer_package_inventory` JSON listing every packaged file with
  category, size, and SHA-256 before Inno packages the bundle. The inventory
  requires role support for `desktop_and_or_hub`, curated Hub setup
  scripts, Hub Manager, Caddy/front-door deployment config, runtime contracts,
  assets, and license notices. The build excludes tests, server code, docs,
  cache folders, repo artifacts, and unapproved scripts/deployment files from
  the bundle and fails if those source-only paths appear in the packaged
  output. The installer default path is
  `%LOCALAPPDATA%\Programs\ImmoApp Beta`; Desktop and Start Menu entries are
  shortcuts, not the product file location. It offers independent Desktop and
  Office Hub choices: Desktop only, Hub only, or Desktop + Hub. The Desktop-only
  choice remains an installer-only path for the client. The Hub choice writes a friendly
  Hub identity and applied foundation evidence, but still does not make agency
  readiness GO without a hidden managed runtime, signing, HTTPS/cert policy,
  backup/restore, lifecycle, support, and real LAN proof.
  Installed inventory validates installed build identity. The installer SHA-256
  is not derivable from installed files; it is recorded as an operator claim in
  installed inventory and becomes proof only when tied to lifecycle evidence that
  checked the installer file hash before install/reinstall observations.
- `scripts/backup_release_bundle.ps1` / `scripts/restore_release_bundle.ps1`:
  release backup/restore proof for PostgreSQL plus MinIO/S3 object data.
  Backup refuses dirty release-critical DB integrity and missing `ready`
  storage object bytes before `pg_dump`, and includes a manifest, SHA-256
  hashes, and integrity report. Restore verifies
  the manifest before touching the DB or object storage and restores object
  bytes into an isolated `immoapp-restore-drill-*` bucket for beta proof.
  Restore verification hashes restored object bytes against the manifest; S3
  object existence alone is not accepted.
- `scripts/verify_release_backup_integrity.py`: read-only release backup
  integrity gate. Non-zero orphan counts are a beta NO-GO, not warnings.
- `scripts/repair_local_dev_release_integrity.ps1`: explicit disposable-local
  repair helper for known orphan residue and missing local `ready` storage
  bytes. It is dry-run by default and requires `-ConfirmDisposableLocalData
  -Apply` to mutate. It is not production repair.
- `scripts/collect_desktop_support_bundle.ps1`: host-side support bundle
  collection for app logs and sanitized runtime metadata.
- `scripts/trust_local_caddy_ca.ps1`: trust the local Caddy CA for browser-clean stack HTTPS
- `scripts/setup_openbao_identity.ps1`: one-time local identity bootstrap
- `checks.ps1` from repo root: canonical quality gate entrypoint

## Supported Check Lanes

These are implementation targets behind `checks.ps1`.

- `scripts/checks_fast.ps1`
- `scripts/checks_pr.ps1`
- `scripts/checks_full.ps1`
- `scripts/checks_nightly.ps1`
- `scripts/checks_tla.ps1`: manual/formal-method lane, intentionally separate

## Internal Orchestration And Recovery

These are valid, but they are specialized operational tools rather than the
default developer workflow.

- `scripts/infra_recover.ps1`
- `scripts/clean_local_state.ps1`
- `scripts/preflight_prod.ps1`
- `scripts/release_canary.ps1`
- `scripts/release_rollback.ps1`
- `scripts/db_backup.ps1`
- `scripts/db_restore_drill.ps1`
- `scripts/run_perf.ps1`
- `scripts/run_chaos_short.ps1`
- `scripts/run_soak.ps1`
- `scripts/sanitize_local_dev_state.ps1`

## Internal Verification Surface

These scripts are mostly called by check lanes, CI, or targeted debugging:

- `scripts/verify_*.py`
- `scripts/verify_*.ps1`
- `scripts/generate_api_route_reference.py`
- `scripts/verify_api_route_reference.py`
- `scripts/generate_db_table_catalog.py`
- `scripts/verify_db_table_catalog.py`
- `scripts/check_live_auth_smoke.py`
- `scripts/check_startup.py`
- `scripts/smoke_test.py`

Run them directly only when debugging a specific subsystem.

## Compatibility Wrapper

- `scripts/check.ps1`: wrapper to repo-root `checks.ps1`

## Subfolders

- `scripts/maintenance/`: one-off maintenance tasks
- `scripts/diagnostics/`: troubleshooting helpers
- `scripts/perf/`: load/perf support assets
- `scripts/benchmark_outputs/`, `scripts/perf_outputs/`, `scripts/profiling/`:
  generated measurement output areas. These paths are ignored by Git and
  recreated by benchmark/performance commands; do not keep release evidence or
  hand-maintained scripts there.

## Runtime Rules

- Canonical env file: `C:\ProgramData\ImmoApp\config\.env.local`
- Canonical clean-machine bootstrap:
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap_local_runtime.ps1`
- Canonical runtime/source-of-truth map:
  [docs/guides/ENV_RUNTIME.md](../docs/guides/ENV_RUNTIME.md)
- Runtime authority and ownership map:
  [docs/guides/RUNTIME_AUTHORITY.md](../docs/guides/RUNTIME_AUTHORITY.md)
- Expensive-work operator guide:
  [docs/guides/OPERATING_EXPENSIVE_WORK.md](../docs/guides/OPERATING_EXPENSIVE_WORK.md)
- Docker stack detail:
  [docs/guides/STACK.md](../docs/guides/STACK.md)

## Native Desktop E2E Runner Operations

Native desktop E2E is outside the fast PR lane. Use the runner preflight before
heavy validation when a local Windows session has been running for a while:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/reset_e2e_environment.ps1 -Mode check -RequireInteractiveDesktop
```

The default adaptive policy is suitable for a 16 GB dev machine: warn below
6 GB free physical RAM, fail below 1 GB critical free RAM, fail below 2 GB
commit/page-file headroom, and fail if PowerShell, server Python, client Python,
or the client Qt import canary cannot spawn. Override thresholds explicitly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/reset_e2e_environment.ps1 -Mode check -RequireInteractiveDesktop -WarnFreeMemoryGb 6 -MinCriticalFreeMemoryGb 1 -MinCommitHeadroomGb 2
```

Use reset mode to prune stale E2E artifacts and stop only command-line-verified
E2E desktop processes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/reset_e2e_environment.ps1 -Mode reset -CleanArtifacts -KillStaleDesktopProcesses -RequireInteractiveDesktop -WarnFreeMemoryGb 6 -MinCriticalFreeMemoryGb 1 -MinCommitHeadroomGb 2
```

The runner does not require 6 GB free RAM to run. It warns below 6 GB, but fails
only when free RAM is critically low, commit headroom is critically low, disk is
short, or required process spawn canaries fail.

For the release/E2E lane, prefer:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_e2e_release_validation.ps1
```

That wrapper resets the runner first and stops stale desktop plus stale E2E
server/preflight processes only when command-line ownership proves they belong
to this repo. It begins with a Docker backend rebuild so backend identity is
stamped from the current checkout.

The dependency vulnerability check audits generated resolved inventories. The
PR lane audits the installed host server and client environments. Full and
release lanes additionally require the Docker backend target (`docker-backend`)
after the backend image is built, so Linux-only packages in the production-like
image are covered. Every target uses `pip freeze --all` followed by
`pip-audit --no-deps --disable-pip` for bounded no-resolver runtime; enforced
lanes fail if a required inventory or audit tool is missing.

If resource checks still fail after targeted reset, close unrelated applications,
restart Docker Desktop, increase the Windows page file, or reboot before release
validation.

Do not treat every script in this folder as a first-class public workflow.

## Managed WSL2 Runtime Policy Scripts

- `managed_wsl2_runtime_policy.ps1`: the only owner for managed WSL2/container
  cap planning. It reads total RAM, logical CPU count, and the existing Hub
  runtime profile envelope when present. The planned cap uses the lower of the
  machine tier and that profile. It does not use raw free RAM. It writes
  `immoapp_managed_wsl2_runtime_policy` evidence and always keeps
  `agency_install_status=NO_GO`.
- `configure_managed_wsl2_runtime.ps1`: the only `.wslconfig` planner/writer.
  It defaults to plan-only. Applying requires `-Apply` and
  `-ConfirmGlobalWslConfigChange`; existing `.wslconfig` content is preserved
  and backed up before writes. `wsl --shutdown` is never run unless
  `-ApplyShutdown` is supplied.
- `hub_manager.ps1 -Action install-runtime-candidate -ConfirmInstallRuntimeCandidate`:
  generates WSL policy evidence plus `.wslconfig` plan evidence, then registers
  a proof-only `managed_wsl2_container_runtime_candidate` provider. Detection
  validates both evidence files, hashes, and semantic sizing fields. This is
  internal beta bridge evidence only; `candidate_registration_status=GO` is not
  runtime artifact/start GO, and Hub Manager start remains `NO-GO` with
  `managed_wsl2_runtime_artifact_missing` until a real ProgramData runtime
  artifact exists.
- `hub_manager.ps1 -Action remove-runtime-candidate`: removes only the
  proof-only WSL candidate provider config and leaves Hub data, backups,
  identity, logs, and runtime artifacts untouched.
- Candidate install may refresh an existing WSL candidate provider, but refuses
  to overwrite any other provider mode with
  `existing_managed_runtime_provider_refuses_candidate_overwrite`.

Hub policy:

- below the normalized 8 GB installed-RAM class: Hub NO-GO, workstation-only
- 7.5 GB through 8 GB Windows-reported RAM: normalize to the 8 GB class
- 8 GB RAM: tiny/conservative Hub with warning
- 15.x GB through 16 GB Windows-reported RAM: normalize to the 16 GB class
- 16 GB RAM: small/medium candidate
- 31.5 GB through 32 GB Windows-reported RAM: normalize to the 32 GB class
- 32 GB and above: medium/large candidate only when CPU also supports that tier
- CPU classes: 1-2 logical processors=tiny, 3-4=small, 5-7=medium, 8+=large

WSL `memory`, `processors`, and `swap` are ceilings. They are not reservations.
Startup spikes are expected; sustained pressure after warm-up drives backoff.
Free/available RAM is diagnostics-only and must not drive baseline sizing. A
WSL policy file is passive and does not activate runtime behavior unless a
verified provider config selects the WSL candidate mode.
Runtime profile provenance is explicit in the policy evidence: source, status,
path, SHA-256, error, and observed profile. Explicit profile input or a default
ProgramData profile must be valid; malformed or unsupported profiles are
`NO-GO`.
Ambiguous `.wslconfig` files with duplicate `[wsl2]` sections or duplicate
managed keys are rejected unchanged for manual cleanup.
Manual Docker Desktop and WSL policy/config/provider planning remain internal
proof only until a real ImmoApp-managed runtime artifact exists and passes
provider/startup/release proofs.
