# Backend Risk Register (Current State)

## Scope

- Backend/API/services/DB/ops only.
- Represents remaining backend and control-plane risks after current guardrails.
- Last reviewed: 2026-03-19.

## Priority Model

- `P0`: release-blocking trust risk
- `P1`: high-leverage reliability/security hardening
- `P2`: scale and operability maturity

## Current Residual Risks

### `P1-IMP-001` Ugly real-world importer heuristics

- Status: **Open residual risk**.
- Current protection:
  - truth matrix
  - replay corpus
  - grouped review
  - `recovery_union` mapping palette
- Remaining risk:
  - ugly real-world files can still over-review or block conservatively
  - weak same-side bundle recovery is intentionally conservative

### `P1-IMP-002` Distributed stalled/orphaned importer recovery

- Status: **Open residual risk**.
- Current protection:
  - queue wait-state diagnostics
  - phase lease expiry repair
  - stalled-job watchdog
  - cancellation path
- Remaining risk:
  - repeated worker pickup failures or orphaned execution slots still need
    ongoing observation during canary

### `P2-DOC-001` Importer documentation drift

- Status: **Mitigated but still monitored**.
- Current protection:
  - importer docs contract test
  - architecture/runbook/reference truth pass
- Remaining risk:
  - code can still outrun docs if new importer states or routes are added
    without updating the contract tests

## Closed Controls (keep enforced)

- dependency CVE gate
- authenticated DAST coverage
- auth security event audit logging
- nightly formal verification
- API and queue baseline guardrails
- OpenBao HA readiness gate
- monitoring policy drift check
- domain critical-path integration depth
- multi-failure game-day automation

## Execution Order (Remaining)

1. Expand importer ugly-file truth matrix and replay corpus before canary.
2. Watch importer stalled/orphaned recovery metrics during controlled rollout.
3. Keep importer doc contract coverage updated as importer control-plane fields evolve.

## How To Use This File

- Treat this as the single source of backend residual risk.
- On each risk closure:
  - link PR or test evidence
  - move the item to closed controls or remove it
  - keep execution order updated
