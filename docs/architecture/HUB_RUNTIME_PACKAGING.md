# Hub Runtime Packaging

Hub Beta Milestone 1 keeps the backend stack Compose/container-based internally,
but the agency manager must not operate Docker, Compose, Postgres, MinIO,
RabbitMQ, Valkey, OpenBao, Celery, ports, or env files. Runtime packaging proof
therefore separates the current developer runtime from the future managed Hub
runtime.

## ADR: Managed Runtime Strategy For The Next Release Phase

Decision: keep the backend Compose/container-based internally and build a real
hidden ImmoApp-owned managed container runtime package next. Do not rewrite to
native Windows services and do not move the first office Hub milestone to
remote/VPS-only deployment.

| Strategy | User complexity | Engineering complexity | Update model | Backup/restore impact | Support risk | Licensing/distribution risk | Windows compatibility | Security/firewall model | Recommendation |
|---|---:|---:|---|---|---:|---:|---|---|---|
| Manual Docker Desktop | High | Low | User-visible Docker Desktop updates | Fits current volumes | High | Medium | Works on developer machines, variable on agency PCs | Easy to misconfigure; Docker UI is exposed | Internal/dev proof only; real agency NO-GO |
| Managed Docker/Moby-compatible runtime hidden by Hub installer | Low | Medium-high | Hub setup owns runtime install/update | Fits current Compose paths and backup model | Medium | Must be resolved before public beta | Best near-term fit if redistribution and service ownership are solved | Hub exposes only web/API; infra remains local/internal | Recommended next phase |
| Podman-compatible runtime hidden by Hub installer | Low | Medium-high | Hub setup owns runtime install/update | May need Compose/network compatibility proof | Medium-high | Must validate Windows support and Compose parity | Possible, but proof burden is higher than Moby-compatible path | Hub exposes only web/API; infra remains local/internal | Evaluate only if Moby-compatible packaging is blocked |
| Native Windows services | Low | Very high | App-owned service updates | Requires service-specific DB/storage lifecycle | High | Lower container licensing risk | Possible, but large rewrite | Windows Service Control Manager, custom firewall rules | Defer unless managed container runtime fails |
| Remote/VPS Hub only | Low local burden | High product change | Server/VPS deployment pipeline | Changes local backup/restore and LAN assumptions | High for first agency beta | Hosting/legal/support scope expands | Good later, not first office Hub | Public ingress, HTTPS, tenant isolation, ops monitoring | Defer |

## Current Policy

- `scripts/detect_hub_runtime.ps1` is the read-only runtime authority for Hub
  packaging evidence.
- `manual_docker_desktop` is always `agency_install_status=NO_GO`.
- `managed_container_runtime` can be agency `GO` only when
  `C:\ProgramData\ImmoApp\config\hub_runtime_provider.json` is present, valid,
  ImmoApp-managed, hidden from the user, and the engine plus Compose checks
  pass.
- Agency `GO` requires the canonical provider config path. A provider loaded
  through `-ProviderConfigPath` is internal proof only and must remain NO-GO.
- Agency `GO` requires the canonical production root
  `C:\ProgramData\ImmoApp`. `IMMOAPP_APPDATA_ROOT` and
  `IMMOAPP_TEST_PROGRAMDATA_ROOT` are internal/test roots and force
  `reason_code=noncanonical_runtime_root`.
- A provider JSON alone is not trust. Agency GO requires the detector to verify
  approved canonical ProgramData roots, lexical and resolved path containment,
  no symlinks/junctions/reparse points, runtime/Compose command checks, package
  inventory, package artifact SHA-256, installed executable hashes, source
  provenance, forbidden-content scan, installer SHA-256, and secret-free
  provider config.
- Proof-only managed providers are allowed for package validation only. They
  may set `internal_proof_status=GO`, but they keep
  `agency_install_status=NO_GO` until a production hidden runtime package is
  installed.
- `managed_wsl2_container_runtime_candidate` is registration/planning proof
  only. It can prove WSL policy and config-plan evidence, but
  `runtime_artifact_status=NO-GO` and `runtime_start_status=NO-GO`.
- `managed_wsl2_container_runtime_artifact` is the first ImmoApp-owned internal
  artifact lane under `C:\ProgramData\ImmoApp\runtime`. The artifact builder
  writes small ImmoApp-owned WSL2/container runtime wrapper files plus a strict
  inventory. The bridge wrapper calls the fixed `ImmoAppRuntime` WSL
  distribution command path and never falls back to repo Docker, manual Docker
  Desktop, or PATH-resolved Docker tools. This can move
  `runtime_artifact_status=GO`; `runtime_start_status=GO` requires bootstrap
  evidence proving the expected distro name, ImmoApp runtime identity,
  container engine GO, Compose GO, service status GO, fresh start evidence, and
  Caddy/front-door health and identity marker proof. Agency install and public
  beta remain `NO-GO` until LAN, backup/restore, lifecycle, support, signing,
  and HTTPS/cert proofs are also real GO.
- Proof-only providers may execute commands only from canonical ProgramData
  roots or from `IMMOAPP_TEST_PROGRAMDATA_ROOT` when
  `IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT=1`. Any other proof provider path returns
  `reason_code=managed_runtime_proof_provider_path_not_approved` before the
  runtime command is executed.
- Candidate promotion also requires backup/restore evidence bound to the exact
  candidate proof run ID, source commit, installer SHA-256, runtime dependency
  mode, provider config path, provider config SHA-256, and provider mode.
- Inline provenance generated during a candidate proof is internal-only,
  proof-only, and written under the unique candidate proof directory. It must
  never overwrite the shared `managed_runtime_vendor_provenance.json`.
- Provider config mutation is serialized by the Hub provider mutation lock.
  Snapshot, provider write, detection, final-state verification, restore, and
  promotion all occur inside that lock in one process. Direct registration and
  candidate proof share the same registration function; a readable lock token is
  not accepted as provider-write authority.
- Backup/restore, support bundle, installed inventory, and runtime package
  evidence must verify the referenced local artifact or provide complete remote
  artifact proof. Hash-only evidence is never sufficient for GO.
- Hub M1 GO evidence must include `schema_version`, `created_at_utc`,
  `machine_name`, `source_commit_sha`, and `installer_sha256`; missing identity
  is `NO-GO`, not a legacy success path.
- Invalid provider config returns `reason_code=invalid_provider_config` and
  remains NO-GO. Hub/release paths must not silently fall back to manual Docker
  Desktop when a malformed provider was supplied.
- `native_windows_services` remains `NO_GO` with
  `reason_code=native_services_deferred` until a real native service verifier
  exists. Self-declared provider booleans are not proof.
- The current stack remains Compose/container-based internally. Do not duplicate
  runtime classification logic in setup scripts, Compose files, or release
  wrappers.

## Managed Provider Contract

`hub_runtime_provider.json` uses:

- `kind: immoapp_hub_runtime_provider`
- `schema_version: 1`
- `provider_mode: managed_container_runtime`
- `installed_by_immoapp: true`
- `user_visible_runtime: false`
- `runtime_executable_path`
- `compose_mode: docker_cli_plugin` or `compose_executable_path`
- `runtime_version`
- `install_root`, `data_root`, `logs_root`
- `managed_service_name`
- `created_at_utc`
- `source_commit_sha`
- `installer_sha256`
- optional `proof_only`, `package_sha256`, and `package_inventory_path`

Production agency-GO providers must be non-proof (`proof_only: false`), have
`runtime_executable_path` and `install_root` under
`C:\ProgramData\ImmoApp\runtime\`, `data_root` under
`C:\ProgramData\ImmoApp\data\`, and `logs_root` under
`C:\ProgramData\ImmoApp\logs\`. They must not reference Docker Desktop or any
user-visible runtime path.

Production providers also require a schema v2 package inventory under
`C:\ProgramData\ImmoApp\runtime\` or `C:\ProgramData\ImmoApp\config\`. The
inventory must use `kind: immoapp_managed_hub_runtime_package_inventory`,
`schema_version: 2`, `proof_result: GO`, `proof_only: false`, non-zero
`package_file_count`, `package_bytes`, `file_count`, and `total_bytes`, no
`forbidden_matches`, and a `package_sha256` matching both the provider and the
package file. `source_commit_sha` is required on provider and inventory as a
40-character lowercase git SHA, and both values must match.
`installer_sha256` is required as a 64-character lowercase SHA-256. Provider
config loaded from any non-canonical path, or from a non-canonical app-data
root, remains internal proof only even if commands are reachable.

The inventory must list every archived file with path, byte size, and SHA-256,
and must name `critical_executables.runtime_executable_relative_path` and
`critical_executables.compose_executable_relative_path`. The detector verifies
the installed runtime and Compose executable hashes against those inventory file
entries. Missing, stale, tampered, or relocated package artifacts are NO-GO.

Any provider or nested object field containing names such as secret, token,
password, access_token, refresh_token, client_secret, credential, presigned,
apiKey, private_key, key_material, signature, certificate, cert, or `.env` is
rejected or redacted in evidence as `managed_runtime_secret_in_config`.

`scripts/register_managed_hub_runtime_provider.ps1` is a staging/proof helper
for writing that config after a managed runtime has been installed by ImmoApp.
It does not install Docker Desktop and refuses to label user-visible Docker
Desktop paths as managed. Without a verified package inventory it can only
write a proof-only provider; proof-only providers remain agency NO-GO.

`scripts/build_managed_hub_runtime_package.ps1` creates schema v2 package
inventory evidence for a hidden runtime artifact. It builds the ZIP from a
sorted explicit file list and reopens the ZIP to verify entry path, byte size,
and SHA-256 before emitting `proof_result=GO`. When no runtime source is
supplied it returns a structured `NO-GO` with
`reason_code=managed_runtime_artifact_missing`; this is intentional and prevents
manual Docker Desktop from being relabeled as managed. The inventory rejects
`.git`, `.tmp`, tests, docs, scripts, E2E artifacts, dumps, developer
DB/MinIO/Postgres data, `.env`, private keys/certs, kube credentials, and
secrets.

The package builder refuses a non-empty explicit output root unless
`-AllowReplaceOutputRoot` is passed. It writes ZIPs to a staging path first,
verifies entries against inventory, and promotes the ZIP atomically only on GO.
On any NO-GO result it removes staging/final ZIP outputs and emits empty
`package_path`, empty `package_sha256`, and `package_bytes: 0` so stale package
artifacts cannot be reused as proof.

The package builder preserves package-relative paths exactly after converting
backslashes to forward slashes. It removes only a literal leading `./` or `.\`
prefix; dotfiles such as `.env`, `.git/config`, `.secret`, and `.pem` remain
visible in `files[]` and `forbidden_matches[]` evidence. If a normalized package
path cannot be mapped back to an existing source file under the runtime source
root, the inventory is emitted as `NO-GO` with
`reason_code=managed_runtime_package_path_mapping_failed`, and no package ZIP is
created.

Schema v2 package inventory also records clean provenance:
`source_tree_clean`, `source_commit_override`, `runtime_source_origin`, and
`dirty_files_summary_count`. Agency-ready inventory requires a valid 40-character
lowercase `source_commit_sha` from the current repo, a clean source tree,
tracked source files, no source-commit override, and
`runtime_source_origin: repo`. External runtime source remains internal proof
only unless it is backed by a vendor/runtime provenance manifest. The manifest
must use `kind: immoapp_managed_runtime_vendor_provenance`,
`schema_version: 1`, and `artifact_kind: zip`. It records
vendor/runtime/license details, identifies the upstream source or internal
source reference, and verifies artifact path, artifact SHA-256, artifact byte
size, safe extracted inventory SHA-256, approval reason, approving ImmoApp
commit, machine, and user. It must also record
`license_distribution_allowed: true`, `license_review_status: approved`,
`approved_by`, and `approved_at_utc`.

Vendor ZIP artifacts are safely inspected by extracting to an isolated
temporary directory. The verifier rejects absolute paths, drive-letter paths,
path traversal, duplicate entries, empty archives, reparse points, and
forbidden/secret runtime package content. The extracted ZIP inventory hash must
match the runtime source tree inventory hash before package proof can become
GO. The provenance file must live under canonical ProgramData runtime or config
roots, must not be behind a reparse point, must be secret-free, and must have
`approved_by_immoapp: true`. Package building, provider registration, and
runtime detection all revalidate this provenance before an external artifact
can become agency-eligible. Dirty repo source or manual source SHA overrides can
be used only for internal proof; they force `proof_result=NO-GO`. Git provenance
fails closed: if Git is unavailable, `HEAD` cannot be read, or status cannot be
verified, the builder records structured git state and cannot emit an
agency-ready package inventory.

Runtime tree and ZIP inspection are shared trust helpers, not per-script logic.
The strict tree scanner rejects root or child reparse points, unsafe relative
paths, duplicate normalized paths, forbidden package content, and empty trees
for provenance proof. ZIP inspection is bounded to 20,000 files, 2 GB total
extracted bytes, 512 MB per file, and a 100:1 maximum compression ratio. JSON
provenance/proof output is written only through the safe writer, which rejects
paths outside approved roots, reparse output files, reparse parents, and
resolved-path escapes.

`scripts/create_managed_runtime_vendor_provenance.ps1` creates this manifest for
a staged runtime artifact, and
`scripts/verify_managed_runtime_vendor_provenance.ps1` validates it. These
scripts do not sign, notarize, or install the runtime. They only make the
artifact provenance contract enforceable so the next managed-runtime prototype
can be evaluated without relabeling Docker Desktop or arbitrary ZIP files as
trusted.

`scripts/install_managed_hub_runtime_provider.ps1` is a deprecated compatibility
wrapper. It delegates to `scripts/register_managed_hub_runtime_provider.ps1` so
there is one provider-writing validation path.

Provider registration without `PackageInventoryJson` is refused unless
`-AllowTestOnlyPath` is explicitly supplied. That proof-only path may write a
provider file for internal validation, but its registration evidence is
`proof_result=NO-GO`, `reason_code=proof_only_provider`,
`internal_proof_status=GO`, and `agency_install_status=NO_GO`.

`scripts/run_managed_runtime_candidate_proof.ps1` is the next-phase candidate
wrapper. It accepts a real runtime ZIP candidate and orchestrates vendor
provenance, package inventory, provider registration, runtime detection, optional
Hub startup/status proof, network-boundary proof, support-bundle proof, and
backup/restore evidence. With no ZIP it emits `NO-GO` with
`missing_artifacts=["runtime_zip_candidate"]`. By default it snapshots and
restores any existing provider config after proof; permanent promotion requires
`-PromoteCandidateProvider`, `-ConfirmPromoteManagedRuntime`, and every required
phase to be GO. It never maps Docker Desktop or proof-only evidence to managed
agency GO.

## Next Phase: Managed Container Runtime Prototype

The next implementation phase is a managed container runtime prototype under
`C:\ProgramData\ImmoApp\runtime\`. The prototype must provide a real hidden
runtime executable plus Compose-compatible command path, package it with schema
v2 inventory, install it through ImmoApp-owned setup, and then pass provider
detection, Hub startup, backup/restore, LAN workstation, install lifecycle, and
support-bundle proofs. Until that artifact exists, managed runtime package proof,
real agency install, and public beta remain `NO-GO`.

The recommended first prototype remains the managed Docker/Moby-compatible path
because it preserves the existing Compose backend, Docker volume layout, and
backup/restore model. Podman-compatible runtime remains a fallback if Moby
licensing or redistribution is blocked. Native Windows services remain deferred
because they would replace service lifecycle, storage, update, and backup
semantics at the same time. Remote/VPS Hub remains a later product mode because
it changes LAN, HTTPS, tenant isolation, operations, and support responsibilities.

## Status Reason Codes

Hub status evidence must include `runtime_state`, `compose_state`, and
`status_reason_code`. Supported reason codes are `runtime_unavailable`,
`stack_stopped`, `stack_starting`, `service_missing`, `service_unhealthy`,
`health_endpoint_unreachable`, `health_endpoint_failed`, and `online`.
`compose_state=partial_stack_required_services_missing` is retained for
backward-compatible evidence when infra is up but app services are absent.

## Network Boundary

Only Caddy may bind to LAN in final Hub mode. Caddy proxies internally to
`web:8000`; the backend direct port plus Postgres, RabbitMQ, Valkey, OpenBao,
MinIO API/console, and ClamAV remain localhost/internal. Private-LAN HTTP is
acceptable only for local beta proof; public beta requires signing and
HTTPS/certificate policy.

The Caddy front door is enabled through the `hub-front-door` Compose profile.
M1 evidence must use `scripts/verify_hub_network_boundary.ps1` to prove that no
infra/backend direct port is LAN-facing and that the Caddy admin endpoint is not
published to LAN. It reports front-door health separately from infra exposure:
`web_health_unreachable` means the front-door health path is down, while
`infra_exposed` means a non-Caddy service is published to LAN.

This proof has `proof_scope=local_compose_boundary`. It is not a replacement
for real workstation LAN proof. Real LAN GO still requires a second workstation,
VM, or network-isolated client using the Hub front-door URL instead of
localhost.

## Managed WSL2 Container Runtime Candidate

The next managed-runtime candidate is an ImmoApp-owned WSL2/container runtime
installed under canonical ProgramData roots. The internal beta bridge can now
generate WSL policy/config evidence and register a proof-only
`managed_wsl2_container_runtime_candidate` provider under ProgramData. This does
not install a runtime artifact, create a WSL distribution, install a container
engine, or make agency install/public beta GO.

WSL2 configuration constraints are product constraints:

- `%UserProfile%\.wslconfig` is global for WSL2 distributions owned by the
  current Windows user.
- `memory` caps the WSL2 VM growth; it is a ceiling, not a reservation.
- `processors` caps logical processors available to WSL2; it is maximum
  parallel CPU use, not fixed CPU consumption.
- `swap` controls WSL swap and must be explicitly bounded.
- `autoMemoryReclaim` may be `disabled`, `gradual`, or `dropCache`; ImmoApp
  defaults to `gradual` and never disables reclaim.
- `.wslconfig` changes may require `wsl --shutdown`; ImmoApp does not run that
  command unless explicitly requested.
- Docker Desktop Resource Saver can reduce CPU while idle, but it does not
  fully solve WSL VM memory retention. WSL memory reclaim remains relevant.

ImmoApp product policy:

- Desktop app remains supported on small PCs.
- Office Hub minimum supported RAM is 8 GB.
- Below 8 GB: Hub is NO-GO and the machine is workstation-only.
- Windows-reported 7.5 GB through 8 GB is treated as the 8 GB installed-RAM
  class. Values below 7.5 GB stay below the Hub minimum.
- Windows-reported 15.x GB through 16 GB is treated as the 16 GB installed-RAM
  class, and 31.5 GB through 32 GB is treated as the 32 GB class.
- 8 GB: Hub is allowed only as a tiny/conservative profile with a clear warning.
- CPU is a real sizing dimension: 1-2 logical processors cap the policy to
  tiny, 3-4 to small, 5-7 to medium, and 8+ can support large if RAM also
  supports large.
- 16 GB: normal small/medium Hub candidate depending on CPU and runtime profile.
- 32 GB and above: comfortable medium/large Hub candidate only when CPU also
  supports that profile.
- Startup spikes are expected and do not automatically mean NO-GO.
- Sustained memory pressure after warm-up triggers backoff/tuning.
- Sizing uses total RAM, CPU count, and the Hub runtime profile envelope, not
  raw free RAM. Free/available RAM is diagnostics-only and must not lower the
  baseline policy.
- When a valid Hub runtime profile is supplied, WSL sizing uses the lower of the
  machine capacity tier and the runtime profile envelope.
- Runtime profile provenance is part of WSL policy evidence. Explicit
  `-RuntimeProfileJson` input records `runtime_profile_source` as
  `explicit_runtime_profile_json` and must be valid. An auto-detected
  ProgramData profile records `default_persisted_config` plus its path and
  SHA-256. No profile records `machine_capacity`, `runtime_profile_status:
  missing`, and empty path/hash. Invalid or unsupported profiles make policy
  evidence `NO-GO`.

`scripts/managed_wsl2_runtime_policy.ps1` is the only WSL2 cap planning owner.
It outputs `immoapp_managed_wsl2_runtime_policy` evidence with
`agency_install_status=NO_GO`. `scripts/configure_managed_wsl2_runtime.ps1` is
the only `.wslconfig` writer and defaults to plan-only. Applying changes
requires both `-Apply` and `-ConfirmGlobalWslConfigChange`; existing unmanaged
settings are preserved/backed up and conflicts require
`-AllowMergeExistingWslConfig`. Ambiguous files with duplicate `[wsl2]` sections
or duplicate managed keys (`memory`, `processors`, `swap`, `autoMemoryReclaim`)
are not merged automatically; they return NO-GO and require manual cleanup.
`hub_manager.ps1 -Action install-runtime-candidate -ConfirmInstallRuntimeCandidate`
records both policy evidence and `.wslconfig` plan evidence, then registers the
proof-only WSL2 candidate provider. Provider detection validates both files,
their SHA-256 hashes, and their semantic sizing fields. Candidate evidence is
`proof_scope=registration_only`; `candidate_registration_status=GO` is not a
runtime artifact/start GO.

A valid WSL2 policy plus config plan can make
`managed_wsl2_container_runtime_candidate` internally useful for Hub runtime
planning and provider wiring, but it cannot satisfy agency readiness. Hub
Manager start refuses this candidate with
`managed_wsl2_runtime_artifact_missing` until a real ImmoApp-owned runtime
artifact is installed and verified. Agency GO still requires the real artifact,
provider detection, Hub startup, backup/restore, real LAN workstation proof,
install lifecycle, support bundle, signing, and HTTPS/certificate policy.

If this proof-only provider strands local development, remove only the provider
config with `hub_manager.ps1 -Action remove-runtime-candidate`. This cleanup
does not delete Hub data, backups, identity, logs, or runtime artifacts; after
removal, detection falls back to manual Docker/internal proof or unavailable
state.

Candidate install is deliberately conservative: it may refresh an existing
`managed_wsl2_container_runtime_candidate` provider, but it refuses to overwrite
any other provider mode with
`existing_managed_runtime_provider_refuses_candidate_overwrite`.

The WSL2 policy JSON is passive evidence. It must not change the active
`runtime_dependency_mode` by itself; only an explicit, verified provider config
may activate `managed_wsl2_container_runtime_candidate`.
