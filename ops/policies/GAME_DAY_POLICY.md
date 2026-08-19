# Game Day Policy

## Objective
Run periodic resilience drills and record measured recovery times.

## Scenarios
- DB connectivity loss/recovery validation
- Queue broker reachability validation
- Object storage reachability validation
- Combined DB+queue+storage outage/recovery validation
- Restore drill verification

## Cadence
- Run at least quarterly in production.
- Run on-demand before major releases.

## Automation
- Script: `scripts/run_game_day_drill.py`
- Enforce mode: `IMMOAPP_ENFORCE_GAME_DAY=1`
- Multi-failure mode: `IMMOAPP_GAME_DAY_MULTI_FAILURE=1`
- Report artifact: `IMMOAPP_GAME_DAY_REPORT=artifacts/game-day-report.json`
- CI workflow: `.github/workflows/game-day.yml` uploads quarterly report artifacts.

## Targets
- Baseline per-check budget (`IMMOAPP_GAME_DAY_BUDGET_MS`): 5000ms default.
- Scenario detection/recovery budget (`IMMOAPP_GAME_DAY_RTO_BUDGET_MS`): 8000ms default.
- RTO conformance is enforced in CI for scheduled game-day runs.

## Success Criteria
- Script exits with code 0.
- All scenario checks report `ok=true`.
- Measured durations remain below agreed SLO budgets.
- Quarterly report artifact is retained for operational review.
