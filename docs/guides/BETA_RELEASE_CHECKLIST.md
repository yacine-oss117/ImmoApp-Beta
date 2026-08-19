# Windows Desktop Beta Release Checklist

This checklist freezes the controlled beta scope for the Windows desktop app. Use it for release-readiness only: do not add product features, broad refactors, compatibility sinks, E2E mutation backdoors, copied-container backend sync, skipped tests, xfails, sleeps, or broad retries to hide failures.

## Hub Runtime Profile Evidence

The Hub/backend resolves a Hub Runtime Profile before startup. The profile is a safety governor:
weak machines run with lower concurrency and smaller batches instead of becoming unsafe, while
normal office PCs and larger workstations use balanced limits. Manager/agent operators should not
manually tune workers for beta proof; use centralized `IMMOAPP_HUB_*` overrides only when a
VPS/server deployment needs an explicit safe profile.

Baseline sizing uses CPU count, total RAM, and container limits. Windows free RAM is not the sizing
source; sustained memory pressure is recorded as green/yellow/red and only temporarily slows
expensive background work.

Beta proof summaries and support bundles must record the selected profile, source,
effective CPU/memory budget, worker/import/match concurrency, DB pool size, pressure state, and
warnings. This runtime profile evidence does not replace signing, fresh-machine install proof, or
fresh LAN Hub/workstation proof.

## Managed WSL2 Runtime Artifact Proof

The first WSL2/container artifact lane is internal proof only. A valid artifact
inventory can prove that ImmoApp-owned files exist under ProgramData, required
wrapper entries are present, and forbidden source/test/secret content is absent.
The managed bridge can prove Hub startup only when fresh
`managed_wsl2_runtime_bootstrap_evidence.json` proves the exact
`ImmoAppRuntime` distro identity, container engine GO, and Compose GO, and
`managed_wsl2_runtime_start_evidence.json` records the fixed WSL artifact
command path, service command GO, pre-start port contamination checks,
Caddy/front-door health 200, the Caddy marker header, and the front-door
identity payload. Release evidence must keep agency install and public beta
NO-GO until network boundary, backup/restore, lifecycle, support bundle,
signing, and HTTPS/cert policy proofs are also real GO.

## Scope Freeze

Beta validation covers only these workflows:

- Auth, session, login, and logout.
- Clients create, edit, delete, and restore basics.
- Listings and owners create, edit, delete, and restore basics.
- Offers create, edit, delete, and two-offer listing behavior.
- Demandes create, edit, and delete.
- Matching visibility and rebuild after demande or offer mutation.
- Offer photos upload, list, view, delete, and re-add.
- Import happy path and review-required path.
- Contract create, edit, print, sign or cancel, and delete.
- Notifications basic visibility.
- Backup and restore drill, including database and object storage.

Manual product-flow validation uses the local agency owner account `owner/admin`. The platform superuser `admin/admin` is reserved for tests that explicitly need superuser behavior.

Before manual local validation, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/prepare_local_beta_client.ps1
```

This resets the desktop client to `http://127.0.0.1:8000`, clears persisted `admin` and `owner` sessions, disables remembered-session reuse, and configures the username as `owner`.

## Repository Hygiene Before Git Or Installer

Run this before creating the real Git repository, building an installer, or
collecting release evidence. The goal is a source tree containing source,
tests, docs, and intentionally versioned configuration only.

Remove generated/local-only residue:

- `.tmp/`
- `.cache/`
- `.hypothesis/`
- `__pycache__/`
- `scripts/benchmark_outputs/`
- `scripts/perf_outputs/`
- `scripts/profiling/`

Do not delete source files, release scripts, migrations, tests, or operational
docs just because they look old. Delete those only after a reference and
ownership audit proves they have no caller and no release purpose.

Cleanliness proof:

```powershell
Get-ChildItem -Force -Recurse -Directory -Include __pycache__,.pytest_cache,.mypy_cache,.ruff_cache,.hypothesis,.cache
Get-ChildItem -Force -Recurse -File | Where-Object { $_.Name -match '(^\.coverage$|\.pyc$|\.pyo$|\.tmp$|\.log$|\.bak$|~$|\.orig$|\.rej$)' }
Get-ChildItem -Force -Recurse -Directory | Where-Object { -not (Get-ChildItem -Force -LiteralPath $_.FullName -ErrorAction SilentlyContinue | Select-Object -First 1) }
```

The repo is clean only when these checks return no source-tree residue.

## Local And Installer Readiness

- Docker stack services must be healthy: `db`, `web`, `workers`, `worker-import`, `worker-match`, `worker-rebuild`, `beat`, `rabbitmq`, `valkey`, `minio`, `openbao`, and `clamav`.
- MinIO recent logs must have no corruption, KMS, or decrypt errors.
- `http://127.0.0.1:8000/api/v1/health/` must return 200.
- `.tmp/` is disposable validation workspace only. Beta artifacts intended for
  manual testers are copied by `scripts/run_beta_release_validation.ps1` to
  `C:\ProgramData\ImmoApp\release_artifacts\beta\<commit-sha-short>\` with
  SHA-256 hashes recorded in `stable_artifacts_manifest.json`. Do not send
  installers directly from `.tmp/`.
- Installer packaging supports Inno Setup 6 stable. Version 6.7.1 is the
  preferred pinned compiler for beta evidence when available, but release
  scripts must not rely on brittle help text exposing the patch version; they
  record the ISCC path, help/version text, product version, file version, and
  version source.
- The current Inno installer uses two independent choices: Install ImmoApp Desktop,
  Set up this computer as Office Hub, or both. The Hub choice asks for a
  friendly Hub display name, writes Hub identity/foundation evidence, and runs the applied
  `setup_office_hub.ps1 -Role HubDesktop` path. The main installer remains
  lowest-privilege; the Hub role launches the setup/firewall step elevated and
  tells the user to finish later from Hub Manager if permission is refused or
  evidence is not applied GO. This is still not public Hub readiness until the
  runtime dependency is hidden/managed and evidence no longer reports manual
  Docker Desktop as a real-agency blocker.
  Hub-only mode suppresses desktop launch/shortcut behavior, but this milestone
  still uses a shared PyInstaller/Inno payload; physically splitting the desktop
  runtime from the Hub Manager payload remains a package-boundary TODO.
  Hub Beta Milestone 1 adds the role-aware installer foundation, not the final
  public Hub installer.
  Evidence must explicitly flag manual Docker Desktop as a real-agency blocker.
- Real users should install product files into the default stable per-user
  location, `{localappdata}\Programs\ImmoApp Beta`; do not install product
  files directly on Desktop by default. The installer creates a Desktop
  shortcut for users by default and also creates a Start Menu shortcut.
- Uninstall removes the desktop-client program files and Inno uninstaller entry.
  It must not delete backend data, Docker volumes, MinIO data, Postgres data,
  release artifacts, backup bundles, or support bundles.
- PyInstaller one-folder output normally contains `ImmoApp.exe` plus
  `_internal\`. `_internal` is the Python/PySide6/Qt/native runtime payload, not
  a source leak. `base_library.zip` is the Python standard-library payload.
  Native `.dll`/`.pyd` files, PySide6/Qt runtime files, PIL, certifi,
  cryptography, charset_normalizer, required client HTTP/security dependencies,
  `app/build_identity.json`, app assets, and font license files are expected.
  Source/backend/test/release-artifact folders are forbidden in the packaged
  desktop bundle.
- Build the Windows installer from a clean tracked worktree:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_desktop_installer.ps1
```

- Install the generated `ImmoApp-Beta-<version>-Setup.exe` on a fresh Windows VM or fresh Windows user profile. For wrapper-created builds, use the stable ProgramData artifact path, not `.tmp`. The public filename must stay user-friendly; the exact Git commit SHA and installer SHA-256 belong in the adjacent `.summary.json`, wrapper summary, and support evidence, not in the tester-facing filename.
- Build output includes `immoapp_installer_package_inventory` evidence. That
  inventory must list every packaged file with category, size, and SHA-256,
  prove `installer_role_support=desktop_and_or_hub`, include the
  curated Hub setup/manager/Caddy/runtime-contract payload, and show no
  forbidden folders such as `.git`, `.tmp`, `tests`, `app/tests`, `server`,
  docs, `__pycache__`, backup bundles, local secret files, unapproved scripts,
  unapproved deployment files, or MinIO/Postgres data.
- The installed app inventory proves the installed payload and build identity.
  It does not prove the installer SHA-256 by itself; `ExpectedInstallerSha256`
  is recorded as `installer_sha256_claimed_by_operator`. The installer file hash
  is tied to evidence through install lifecycle collection, which checks the
  installer file before install/reinstall proof.
- Confirm startup has no developer tools, the login dialog appears, `owner/admin` login works against local or staging, no DLL/Qt/cert/path dependency is missing, and logs are written under the app log directory.
- The beta installer is unsigned unless code signing is configured. Unsigned
  installers can trigger Windows SmartScreen. This is acceptable for a private
  local/internal beta only when testers are warned. Public beta distribution is NO-GO without code signing.

## Smoke And Gates

Run one manual owner smoke:

- Login as `owner/admin`.
- Create owner/listing.
- Create two offers with different locations.
- Add two photos.
- Create client.
- Create two demandes that match the offers.
- Confirm expected matches.
- Confirm photo visibility from owner/listing and match surfaces.
- Create a contract from a match.
- Exercise draft, edit, print/pending signature, sign or cancel, and delete.
- Run import happy path.
- Run import review-required path.
- Confirm no crash, stale UI state, backend 500, or silent photo failure.

Then run automated gates in order:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_e2e_release_validation.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File checks.ps1 -Stage pr
powershell -NoProfile -ExecutionPolicy Bypass -File checks.ps1 -Stage full
```

The release E2E wrapper runs the broad desktop nightly suite once after rebuilding
the backend; nightly includes smoke-marked tests. The release wrapper and full
gate must include host and Docker backend dependency inventories.

## Backup And Restore

Use release bundles for beta recovery proof. A DB-only restore is not enough for media-bearing environments. PR/full gates are necessary but not sufficient for beta: backup plus isolated restore proof must pass.

Release backup runs a read-only integrity gate before `pg_dump`. If release-critical orphan rows or `ready` storage metadata without object bytes exist, backup refuses to create a bundle. Backup never repairs or deletes data.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/backup_release_bundle.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/restore_release_bundle.ps1 -BundlePath "C:\ProgramData\ImmoApp\backups\release_YYYYMMDD_HHMMSS.zip"
```

For disposable local development data only, inspect and then explicitly repair known orphan residue and missing local `ready` storage-byte residue:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/repair_local_dev_release_integrity.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/repair_local_dev_release_integrity.ps1 -ConfirmDisposableLocalData -Apply
```

The repair command is dry-run by default, refuses strict production/staging/non-local DB targets, and is not a production repair strategy. For missing local object bytes it soft-deletes affected media metadata instead of fabricating replacement objects.

The bundle must include:

- PostgreSQL custom dump.
- MinIO/S3 bucket object mirror.
- Manifest, SHA-256 hashes, and a passing integrity report.
- Restore evidence proving active `storage_objects` rows have corresponding object data in an isolated `immoapp-restore-drill-*` bucket, with byte size and SHA-256 matching the bundle manifest.

Restore drills verify the manifest before touching the DB or object storage. Beta proof restores objects into an isolated drill bucket and must not mirror them back into the live source bucket. Production restore is a separate operational procedure. Fail the release pass if offer photos restore only as database rows without recoverable object bytes.

## Staging

Beta staging uses local MinIO/object storage unless a later release plan explicitly changes storage. Staging must have HTTPS, strict production config verification, non-dev secrets, object storage configured, backup schedule, restore drill, and no dev-only E2E control routes enabled.

Run production preflight before deployment:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/preflight_prod.ps1 -EnvFile <staging-env-file>
```

Run desktop E2E against staging only when supported without dev-only mutation routes. Otherwise run the owner manual smoke against staging.

## Fresh-Machine And LAN Proof

This is the next release-readiness milestone after backup/restore proof. It is a separate GO/NO-GO track and must not be inferred from green PR/full gates.
docs/checklist alone are not proof: every GO entry below needs command output,
artifact paths, screenshots, logs, or a signed manual record captured during the
actual beta proof. Installer build GO does not imply fresh-machine GO or LAN GO;
installer build GO does not imply fresh-machine GO or LAN GO.

Fresh-machine install proof and LAN Hub/workstation proof are separate phases.
A desktop installed and tested on the Hub machine can use
`http://127.0.0.1:8000`; a workstation cannot. Workstation proof must use a Hub
IP address or DNS hostname in the desktop backend URL, and that Hub URL must be
reachable from the workstation profile before any LAN GO decision.

Use the read-only reachability helper from the workstation/profile:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify_lan_workstation_reachability.ps1 -HubBaseUrl "http://<hub-ip-or-hostname>:8000" -RequireWorkstationUrl -OutputJson ".\lan_reachability.json"
```

The helper calls `/api/v1/health/`, records DNS/IP resolution, machine name,
network adapter summary, timestamp, and optional backend identity information
when available. It does not mutate backend data and does not use E2E mutation
routes.

Record status for:

- Git available: exact Git executable path and version recorded.
- Inno Setup available: exact ISCC executable path and version metadata recorded
  for Inno Setup 6 stable. Version 6.7.1 is preferred/pinned in docs, but
  detection accepts reliable Inno Setup 6 evidence even when Windows file
  metadata reports `0.0.0.0`.
- Installer build: deterministic beta installer EXE produced from a clean tracked worktree.
- Installer SHA-256 recorded.
- Source commit SHA recorded.
- Fresh Windows profile install: app starts without developer tools, missing DLLs, Qt plugin errors, certificate/path assumptions, or hidden dev dependencies.
- Desktop launches from the installed shortcut.
- Office Hub machine setup: backend stack starts on the Hub machine, object storage is configured, and backup/restore scripts use the Hub data paths.
- Hub setup wrapper: `scripts/setup_office_hub.ps1 -Role HubDesktop` prepares
  Hub mode, writes LAN web binding and allowed hosts, generates the runtime
  profile, creates Hub Manager shortcuts, and records
  `agency_install_status=NO_GO` when Docker Desktop is still manually required.
  Validate-only Hub foundation evidence is planning evidence only:
  `foundation_plan_status=GO` does not mean setup was applied, and release
  validation rejects validate-only foundation evidence as install proof. Applied
  foundation proof requires real writes for `hub_identity.json`, safe ProgramData
  config/data/logs/runtime directories, Caddy/front-door configuration, and a
  verified Private-profile Windows Firewall rule for the Caddy front-door port
  when LAN access is enabled. Skipped, disabled, wrong-port, wrong-profile, or
  name-only firewall evidence is NO-GO for LAN foundation. Hub foundation GO is
  not agency install GO or public beta GO.
- Runtime packaging proof: `scripts/detect_hub_runtime.ps1` records
  `manual_docker_desktop`, `managed_container_runtime`,
  `native_windows_services`, or `unavailable`. Manual Docker Desktop is
  internal/dev proof only and cannot satisfy real agency GO. A managed runtime
  can be considered only when the canonical ProgramData provider config is valid,
  ImmoApp-owned, hidden from the operator, and verified by runtime plus Compose
  checks. A provider JSON alone is not trust: agency GO also requires a
  schema-v2 verified package inventory/hash/provenance under canonical
  `C:\ProgramData\ImmoApp` paths, no symlinks/junctions/reparse points,
  installer SHA-256, package artifact hash verification, installed
  runtime/Compose file hashes matching inventory critical executables, no
  forbidden package content, no proof-only flag, and no
  secret/token/password/private-key fields in the provider config. Test or
  app-data override roots force `noncanonical_runtime_root`. `native_windows_services`
  is deferred and cannot become GO from self-declared provider booleans. Invalid
  provider config is its own NO-GO and must not silently fall back to manual
  Docker Desktop.
- Vendor/runtime provenance: external runtime artifacts require
  `kind: immoapp_managed_runtime_vendor_provenance` under canonical ProgramData
  runtime/config roots, with `artifact_kind=zip`, license, license distribution
  approval, license review status `approved`, artifact SHA-256/bytes, safe ZIP
  extracted inventory hash, approval reason, approver/timestamp, source commit,
  and `approved_by_immoapp=true`. The extracted ZIP inventory must match the
  staged runtime tree inventory, and unsafe ZIP entries, duplicates, traversal,
  reparse points, or secret package content are NO-GO.
  Without this manifest, external artifacts remain internal proof only.
- Installed path proof: real agency GO requires installed Hub Manager and
  desktop executable paths. `hub_manager_script_source=repo_dev` or
  `desktop_exe_source=repo_dev` is internal/debug proof only and keeps agency
  install NO-GO.
- Hub Manager: `ImmoApp Hub Manager.exe` is installed for Hub roles and exposes
  start, stop, restart, status, health, support bundle, backup-now, connection
  URL, rename, logs, and open-desktop actions without requiring the operator to
  run PowerShell or Docker/Compose directly. The app delegates internally to the
  audited `scripts/hub_manager.ps1` control plane.
- Hub identity: a friendly display name is required in
  `C:\ProgramData\ImmoApp\config\hub_identity.json`. The Windows hostname/IP
  are read-only technical diagnostics and must not be silently accepted as the
  display name.
- Office Hub front door is reachable from the Hub machine through Caddy.
- Workstation connection to Hub: desktop can reach the Caddy front-door URL over
  LAN using the configured base URL and normal `owner/admin` agency account
  behavior.
- Workstation desktop backend URL: must be the Hub front-door URL, not
  `localhost`, `127.0.0.1`, or the backend-internal direct port; it is
  explicitly not `localhost` or `127.0.0.1`.
- LAN reachability proof: JSON generated by
  `scripts/verify_lan_workstation_reachability.ps1` with health status 200.
- Local proof: `scripts/verify_hub_m1_local_proof.ps1` may collect local
  runtime/setup/status/support evidence, but it must remain NO-GO for real LAN
  proof unless separate workstation evidence is supplied. `-ValidateOnly` never
  starts Hub services and records any running Hub only as
  `observed_existing_hub_status`; `started_hub_status` is `not_applicable`.
  `-StartHubForProof` may start services for internal proof and records
  `startup_attempted=true`, but it does not change agency GO while the runtime
  is manual Docker Desktop, proof-only, or repo-dev path based.
- Managed runtime package proof: `scripts/build_managed_hub_runtime_package.ps1`
  must produce inventory evidence. Missing hidden runtime artifacts are
  recorded as `managed_runtime_artifact_missing`, not as GO. Forbidden package
  content such as `.git`, `.tmp`, tests, docs, E2E artifacts, dumps, developer
  data, and secrets blocks the package proof. The builder stages and promotes
  ZIPs only on GO; NO-GO evidence must not reference stale package files. The
  next-phase scaffold is `scripts/prepare_managed_hub_runtime_prototype.ps1`,
  which remains NO-GO until a real hidden runtime and Compose-capable command
  exist under ProgramData.
- Managed runtime candidate proof: `scripts/run_managed_runtime_candidate_proof.ps1`
  is the next wrapper for a real runtime ZIP candidate. It must report exact
  missing artifacts and cannot satisfy agency GO unless vendor provenance,
  package inventory, provider registration/detection, Hub startup/status,
  network boundary, backup/restore, LAN workstation, lifecycle, and support
  evidence are all real and GO.
- Installed inventory evidence must mark whether the installer SHA-256 was
  verified from an installer file or only claimed by an operator. Claimed-only
  installer hashes are rejected for local Hub M1 GO.
- Backup/restore proof for Hub M1 aggregation must use explicit backup evidence
  kinds (`immoapp_release_backup_restore_evidence` or
  `immoapp_beta_release_backup_restore_evidence`) with schema version, isolated
  restore bucket, restore DB, object hash verification, and backup bundle
  SHA-256. A path without a matching SHA-256 is not proof.
- Network type recorded: Ethernet or Wi-Fi.
- Windows firewall rule status recorded.
- Workstation can login as `owner/admin`.
- Workstation can create/read/update core records.
- Workstation can view an offer photo thumbnail from storage.
- support bundle can be collected from workstation.
- Backup/restore proof passed on Hub data.
- Backup schedule visibility: operator can see where backups land, when the last backup ran, and how restore drill evidence is recorded.
- Hub install evidence JSON uses `kind: immoapp_hub_install_evidence` and
  records install role, runtime dependency mode, agency install status,
  transport security, data path, support bundle path/hash, and GO/NO-GO reason.
- Hub status evidence JSON uses `kind: immoapp_hub_status_evidence` and records
  Hub status, API/DB/storage/worker health, runtime profile, LAN address and
  bind host, firewall state, data path, backup status, and Compose service
  status. It must include `runtime_state`, `compose_state`,
  `status_reason_code`, exact failing service names, missing services, and
  starting services so support can distinguish stopped stack, starting stack,
  missing app services, unhealthy service, runtime unavailable, health endpoint
  failure, and network/firewall failure.
- Hub network boundary evidence JSON uses `kind:
  immoapp_hub_network_boundary_evidence` and records that only web/API may be
  LAN-facing. DB, RabbitMQ, Valkey, OpenBao, MinIO API/console, ClamAV, and
  default Caddy/proxy ingress must stay localhost/internal for M1. Web/API down
  is reported as `web_health_unreachable`; non-web LAN exposure is reported
  separately as an infra exposure failure. The proof scope is
  `local_compose_boundary`; it does not satisfy the second-machine workstation
  LAN proof by itself.
- Hub M1 GO/NO-GO aggregation uses
  `scripts/verify_hub_beta_m1_evidence.ps1` and writes
  `kind: immoapp_hub_beta_m1_go_no_go_evidence`. It requires Hub install/status,
  workstation reachability, workstation product proof, backup/restore, support
  bundle, installed inventory, and install lifecycle evidence.
- Support bundle collection: app log, sanitized config, backend URL, health result, build identity, and environment summary can be collected without secrets.
- Uninstall/reinstall behavior: uninstall/reinstall does not destroy Hub data unless explicitly requested, and reinstall can reconnect without stale admin sessions.

Fresh-machine/LAN proof is GO only when each item above has concrete command/output or manual evidence; missing Git, Inno Setup, a fresh Windows profile/VM, or a second workstation means LAN beta remains NO-GO until proven. Do not substitute assumptions for proof.

Fresh-machine evidence JSON must use `kind:
immoapp_fresh_machine_install_evidence`, include a schema version, source
commit SHA, installer SHA-256, installed shortcut path, installed app launch
path, desktop backend URL, support bundle path, owner login proof,
create/read/update proof, and offer photo thumbnail proof. LAN evidence JSON
must use `kind: immoapp_lan_hub_workstation_evidence`, include the Hub URL,
desktop backend URL, `backend_url_is_localhost`, health status, reachability
proof path, firewall status, owner login proof, workstation CRUD proof,
workstation photo thumbnail proof, workstation support bundle path,
Hub backup/restore proof, and uninstall/reinstall behavior. Free-form text is
not enough for GO evidence.

Use structured evidence helpers instead of free-form notes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/collect_installed_app_inventory.ps1 -InstallLocation "$env:LOCALAPPDATA\Programs\ImmoApp Beta" -OutputJson ".\installed_inventory.json" -ExpectedSourceCommitSha "<commit>"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/collect_install_lifecycle_evidence.ps1 -Mode post_install -InstallerPath ".\ImmoApp-Beta-1.0.0-Setup.exe" -InstallerSha256 "<sha256>" -SourceCommitSha "<commit>" -BackendUrl "http://127.0.0.1:8000" -InstallLocation "$env:LOCALAPPDATA\Programs\ImmoApp Beta" -OutputJson ".\lifecycle_post_install.json"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/collect_install_lifecycle_evidence.ps1 -Mode post_uninstall -InstallerPath ".\ImmoApp-Beta-1.0.0-Setup.exe" -InstallerSha256 "<sha256>" -SourceCommitSha "<commit>" -InstallLocation "$env:LOCALAPPDATA\Programs\ImmoApp Beta" -OutputJson ".\lifecycle_post_uninstall.json"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/collect_install_lifecycle_evidence.ps1 -Mode post_reinstall -InstallerPath ".\ImmoApp-Beta-1.0.0-Setup.exe" -InstallerSha256 "<sha256>" -SourceCommitSha "<commit>" -BackendUrl "http://127.0.0.1:8000" -InstallLocation "$env:LOCALAPPDATA\Programs\ImmoApp Beta" -OutputJson ".\lifecycle_post_reinstall.json"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/collect_install_lifecycle_evidence.ps1 -Mode combined_manual -InstallerPath ".\ImmoApp-Beta-1.0.0-Setup.exe" -InstallerSha256 "<sha256>" -SourceCommitSha "<commit>" -BackendUrl "http://127.0.0.1:8000" -PostInstallEvidenceJson ".\lifecycle_post_install.json" -PostUninstallEvidenceJson ".\lifecycle_post_uninstall.json" -PostReinstallEvidenceJson ".\lifecycle_post_reinstall.json" -OutputJson ".\install_lifecycle.json"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/collect_fresh_machine_install_evidence.ps1 -InstallerPath ".\ImmoApp-Beta-1.0.0-Setup.exe" -InstallerSha256 "<sha256>" -SourceCommitSha "<commit>" -BackendUrl "http://127.0.0.1:8000" -SupportBundlePath ".\support_bundle.zip" -InstalledInventoryJson ".\installed_inventory.json" -InstallLifecycleEvidenceJson ".\install_lifecycle.json" -OutputJson ".\fresh_machine.json"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/write_manual_product_proof_evidence.ps1 -FreshEvidenceJson ".\fresh_machine.json" -SupportBundlePath ".\support_bundle.zip" -OutputJson ".\manual_product_proof.json" -OwnerLoginConfirmed -CrudConfirmed -OfferPhotoThumbnailConfirmed
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/collect_lan_workstation_evidence.ps1 -HubBaseUrl "http://<hub-ip-or-hostname>:8000" -ReachabilityProofJson ".\lan_reachability.json" -InstallerSha256 "<sha256>" -SourceCommitSha "<commit>" -DesktopBackendUrl "http://<hub-ip-or-hostname>:8000" -SupportBundlePath ".\workstation_support_bundle.zip" -OutputJson ".\lan_workstation.json" -OwnerLoginConfirmed -CrudConfirmed -OfferPhotoThumbnailConfirmed -HubBackupRestoreConfirmed -UninstallReinstallConfirmed
```

Fresh-machine support bundle and workstation support bundle collection are
required. Local evidence paths must exist. Remote evidence must include file
SHA-256 values and embedded or hashed proof references. LAN proof must use Hub
IP/hostname, not `127.0.0.1` or `localhost`.
For remote evidence, set `remote_evidence: true` and include
`evidence_file_sha256`, `support_bundle_sha256`, `copied_from_machine`,
`copied_at_utc`, and embedded or hash-recorded installed inventory, lifecycle,
and reachability proof. The release wrapper does not treat remote filesystem
paths as local proof.

Install lifecycle proof is phase-based. `post_install` must observe registry and
installed executable present. `post_uninstall` must observe registry and
installed executable absent and the install directory absent or empty.
`post_reinstall` must observe registry and installed executable present again.
A single final installed state is not uninstall proof. Schema v3 separates
`install_mechanics_status` from
`installed_app_front_door_connectivity_status`; mechanics-only evidence is not
full desktop installer proof.

Fresh-machine GO requires installed inventory evidence, install lifecycle
evidence with `desktop_installer_release_proof_status: GO`, and installed
desktop front-door connectivity evidence proving the saved client endpoint is a
verified Caddy Hub front-door URL. Passing only an explicit installed executable
path is weaker evidence and remains NO-GO for full beta.

Use the existing endpoint helper when preparing a workstation desktop profile:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/set_client_api_endpoint.ps1 -BaseUrl "http://<hub-ip-or-hostname>:8000" -Username owner
```

Future work, separate from this milestone: managed/bundled container runtime,
final friendly Hub installer pages, LAN auto-discovery, full Hub GUI,
certificate automation, and code signing.

## GO/NO-GO Scorecard

Record status for:

- Core workflow status.
- Installer status.
- Backend deploy status.
- Backup/restore status.
- Security status.
- Dependency audit status.
- E2E status.
- Known warnings.
- Known non-blocking gaps.
- Explicit beta blockers.

GO requires no known data-loss bug, no auth/session security bug, no core-flow crash, fresh install success, rebuilt Docker backend smoke/nightly/release wrapper success, PR/full gate success, dependency audit success, DB plus photo-object restore success, HTTPS staging deployment with strict prod config verification, and documented non-core gaps only.

NO-GO if any backend 500 or crash occurs in a core UI path, restore is broken, dependency audit fails, E2E backend identity mismatches, a dev-only route is enabled outside local E2E mode, or manual testing requires platform `admin` instead of `owner`.

## Managed WSL2 Runtime Candidate Evidence

The managed WSL2/container lane is an internal beta bridge, not an agency/public
beta release gate. It can generate WSL policy evidence and register a
proof-only `managed_wsl2_container_runtime_candidate` provider under ProgramData,
but Hub start remains NO-GO until a real ImmoApp-owned runtime artifact exists.
The official policy is:

- Desktop can run on low-resource PCs.
- Hub minimum RAM is 8 GB.
- Below 8 GB is Hub NO-GO and workstation-only.
- 8 GB is allowed only as a tiny/conservative Hub with warning.
- 16 GB is a normal small/medium Hub candidate.
- 32 GB and above is a comfortable medium/large candidate.
- WSL `memory` and `processors` are ceilings, not reservations.
- Startup spikes are not failures; sustained post-warm-up pressure drives
  backoff.
- `.wslconfig` is global for WSL2 in the current Windows user profile and must
  not be edited silently.

Record WSL policy evidence with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\managed_wsl2_runtime_policy.ps1 -PlanOnly -OutputJson .tmp\managed_wsl2_policy_plan.json
```

Dry-run `.wslconfig` planning with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\configure_managed_wsl2_runtime.ps1 -PlanOnly -OutputJson .tmp\managed_wsl2_config_plan.json
```

Register the internal proof-only candidate provider with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\hub_manager.ps1 -Action install-runtime-candidate -ConfirmInstallRuntimeCandidate
```

This evidence is `proof_scope=registration_only`: candidate registration GO is
not runtime artifact/start GO. Remove the proof-only provider with
`hub_manager.ps1 -Action remove-runtime-candidate`; removal preserves Hub data,
backups, identity, logs, and runtime artifacts. `managed_wsl2_container_runtime_candidate`
proof remains `agency_install_status=NO_GO` and Hub Manager start reports
`managed_wsl2_runtime_artifact_missing` until the real runtime artifact is
installed. Public beta remains NO-GO until the real managed runtime artifact,
Hub startup, backup/restore, real LAN proof, lifecycle, support bundle, signing,
and HTTPS/certificate policy all pass.

Candidate install may refresh an existing WSL candidate provider, but it refuses
to overwrite any other provider mode. The expected failure reason is
`existing_managed_runtime_provider_refuses_candidate_overwrite`.
