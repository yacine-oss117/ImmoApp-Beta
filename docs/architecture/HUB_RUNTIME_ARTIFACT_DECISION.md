# Hub Runtime Artifact Decision

Status: proposed next release lane

The Hub managed-runtime proof layer can validate a candidate artifact, but a candidate is not agency-ready until it is promoted and all release evidence gates pass. This document defines how the first hidden runtime artifact will be selected.

## Threat Model And Invariants

Candidate runtime evidence can be forged, stale, copied from another run, incomplete, or generated against a different provider. Provider config is a trust-root file: it can be corrupted, symlinked, partially written, or left in candidate state after an interrupted proof. Backup/restore evidence is security-critical because it gates agency readiness.

Hard invariants:

- Candidate validation `GO` is internal evidence only; it is not agency `GO`.
- Non-promoting candidate proofs must restore the previous provider config in all paths, including unexpected exceptions.
- Provider config snapshot/read/write/delete operations must reject reparse points and resolved-path escapes.
- Promotion requires final active provider detection from the promoted provider.
- Backup/restore evidence is not reusable across runtime/provider candidates. Promotion requires it to be bound to the candidate proof run ID, source commit, installer SHA-256, runtime mode, provider config path, provider config SHA-256, and provider mode.
- Inline vendor/license approval is internal validation only. It writes to the candidate proof directory, is marked proof-only, and must never overwrite the shared provenance manifest.
- Provider config mutation is serialized by the Hub provider mutation lock. Snapshot, write, detection, final-state verification, restore, and promotion must all happen while the lock is held by the same process; readable bearer-token lock inheritance is not an acceptable write authority.
- Backup/support/runtime package proof must verify the referenced artifact. Hash-only JSON is diagnostic metadata, not GO-bearing evidence.
- Hub M1 GO evidence without `schema_version`, `created_at_utc`, `machine_name`, `source_commit_sha`, and `installer_sha256` is replayable and must be treated as `NO-GO`.
- Vendor/license approval must come from a separate provenance artifact or explicit approval command fields; the candidate wrapper must not silently self-approve distribution.

## Decision Rule

The first managed runtime artifact is acceptable only if it can pass all existing gates:

- vendor/runtime provenance manifest
- deterministic package inventory and package hash verification
- provider registration and final runtime detection from canonical `C:\ProgramData\ImmoApp`
- Hub startup and status proof
- backup/restore proof
- real LAN workstation proof
- install/uninstall/reinstall lifecycle proof
- support bundle proof
- installer signing
- HTTPS/local certificate policy

Candidate validation without promotion is internal proof only. It must not produce agency `GO`.

## Options

| Option | License and distribution | Install and uninstall | Windows service ownership | Compose compatibility | Backup/restore fit | Update strategy | Operational risk | Decision |
|---|---|---|---|---|---|---|---|---|
| Manual Docker Desktop | User-visible third-party desktop product; approval source is developer/internal only. Artifact source is the user's installed Docker Desktop, not an ImmoApp artifact. | Requires manual install, user account/session behavior, and visible Docker controls. | Owned by Docker Desktop, not ImmoApp. | Good for current Compose stack. | Fits current bind-volume layout. | Outside ImmoApp control. | High support risk and not agency-ready. | Internal proof only. |
| Packaged Docker Engine/CLI | Candidate only with recorded license/distribution approval, exact artifact URL/source, SHA-256, byte size, and vendor provenance manifest. | Installer places runtime under `C:\ProgramData\ImmoApp\runtime`; uninstall removes runtime files only and preserves data/config by default. | ImmoApp-owned Windows service must manage engine lifecycle. | Best fit for current Compose stack if Compose support is packaged and verified. | Strong fit with existing bind-volume backup/restore model. | ImmoApp versions the runtime package, verifies hashes, and supports rollback to prior package/provider. | Medium risk around Windows service hardening, firewall scope, and runtime updates. | Primary candidate if proof commands pass. |
| Podman/Moby/other OCI runtime | Candidate only with license/distribution approval, artifact URL/source, SHA-256, byte size, and provenance manifest. | Hidden ProgramData install is required; uninstall preserves agency data and removes only runtime-owned files. | ImmoApp-owned service or documented service wrapper required. | Must prove Compose parity or provide a compatible compose-capable command without changing backend contracts. | Likely compatible, but volume/network semantics need proof. | Runtime package update/rollback must be controlled by ImmoApp. | Medium to high risk from Compose differences and Windows networking behavior. | Secondary candidate. |
| Native Windows services | No container artifact, but no approval source exists until backend deployment is decomposed from Compose. | Installer would own Postgres, object storage, queue/cache, workers, and web services separately. | ImmoApp owns all services. | Not Compose-compatible without a backend deployment rewrite. | Backup/restore would need new service-aware orchestration. | Higher app-specific update and rollback burden. | High migration and support risk for this release lane. | Deferred. |

## Proof Commands For Any Candidate

The first real artifact must run through the same lane:

1. `scripts/create_managed_runtime_vendor_provenance.ps1` with explicit approval fields or a separately supplied provenance JSON.
2. `scripts/build_managed_hub_runtime_package.ps1` against the staged runtime tree and provenance.
3. `scripts/register_managed_hub_runtime_provider.ps1` using canonical ProgramData roots.
4. `scripts/detect_hub_runtime.ps1` showing `managed_container_runtime` and agency `GO`.
5. `scripts/run_managed_runtime_candidate_proof.ps1` with `-PromoteCandidateProvider` only after Hub startup, network boundary, strict backup/restore, support bundle, lifecycle, LAN, signing, and HTTPS/cert policy evidence are ready.

## Next Action

Build the first candidate lane around a managed container runtime prototype under canonical ProgramData roots. The prototype must provide a real ZIP artifact, a vendor provenance manifest, package inventory, provider registration, and runtime detection evidence. If any proof is missing, the lane remains `NO-GO` with a precise reason.

No public or agency beta can use manual Docker Desktop, proof-only providers, non-promoted candidates, or unsigned/private-HTTP-only evidence as final readiness.
