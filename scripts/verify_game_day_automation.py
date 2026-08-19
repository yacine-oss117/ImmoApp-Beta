from __future__ import annotations

from pathlib import Path


def _require(path: str) -> Path:
    target = Path(path)
    if not target.exists():
        raise SystemExit(f"verify_game_day_automation: missing required file {path}")
    return target


def _assert_contains(text: str, token: str) -> None:
    if token not in text:
        raise SystemExit(f"verify_game_day_automation: missing token '{token}'")


def main() -> None:
    workflow = _require(".github/workflows/game-day.yml").read_text(encoding="utf-8")
    policy = _require("ops/GAME_DAY_POLICY.md").read_text(encoding="utf-8")
    script = _require("scripts/run_game_day_drill.py").read_text(encoding="utf-8")

    required_workflow_tokens = (
        "cron:",
        "scripts/run_game_day_drill.py",
        "IMMOAPP_ENFORCE_GAME_DAY",
        "IMMOAPP_GAME_DAY_MULTI_FAILURE",
        "actions/upload-artifact",
        "game-day-report",
    )
    for token in required_workflow_tokens:
        _assert_contains(workflow, token)

    required_policy_tokens = (
        "Combined DB+queue+storage outage/recovery validation",
        "IMMOAPP_GAME_DAY_MULTI_FAILURE",
        "IMMOAPP_GAME_DAY_REPORT",
        "RTO",
        "quarterly",
    )
    for token in required_policy_tokens:
        _assert_contains(policy, token)

    required_script_tokens = (
        "_scenario_multi_failure",
        "IMMOAPP_GAME_DAY_REPORT",
        "IMMOAPP_GAME_DAY_RTO_BUDGET_MS",
        "report written to",
    )
    for token in required_script_tokens:
        _assert_contains(script, token)

    print("verify_game_day_automation: OK")


if __name__ == "__main__":
    main()
