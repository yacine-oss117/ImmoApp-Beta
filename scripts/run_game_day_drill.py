from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import redis

from repo_layout import OPS_RUNBOOK_ROOT


@dataclass
class CheckResult:
    name: str
    ok: bool
    duration_ms: float
    detail: str


@dataclass
class ScenarioResult:
    name: str
    ok: bool
    detection_ms: float
    recovery_ms: float
    detail: str


@contextmanager
def _temporary_env(overrides: dict[str, str]) -> object:
    original: dict[str, str | None] = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for key, old_value in original.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _check_db() -> CheckResult:
    start = time.perf_counter()
    try:
        host = os.environ.get("POSTGRES_HOST", "localhost")
        port = os.environ.get("POSTGRES_PORT", "5432")
        dbname = os.environ.get("POSTGRES_DB", "")
        user = os.environ.get("POSTGRES_ADMIN_USER", os.environ.get("POSTGRES_USER", ""))
        password = os.environ.get(
            "POSTGRES_ADMIN_PASSWORD",
            os.environ.get("POSTGRES_PASSWORD", ""),
        )
        if not dbname or not user or not password:
            duration = (time.perf_counter() - start) * 1000.0
            return CheckResult("db", False, duration, "db env missing")
        conn = psycopg.connect(
            f"host={host} port={port} dbname={dbname} user={user} password={password} connect_timeout=3"
        )
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        ok = True
        detail = "db query ok"
    except Exception as exc:
        ok = False
        detail = str(exc)
    duration = (time.perf_counter() - start) * 1000.0
    return CheckResult("db", ok, duration, detail)


def _check_queue() -> CheckResult:
    start = time.perf_counter()
    url = os.environ.get("VALKEY_URL", "redis://localhost:6379/1")
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        ok = True
        detail = "redis ping ok"
    except Exception as exc:
        ok = False
        detail = str(exc)
    duration = (time.perf_counter() - start) * 1000.0
    return CheckResult("queue", ok, duration, detail)


def _check_storage() -> CheckResult:
    start = time.perf_counter()
    endpoint = os.environ.get("STORAGE_ENDPOINT_URL", "http://localhost:9000").rstrip("/")
    url = f"{endpoint}/minio/health/live"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            code = int(resp.status)
        ok = code == 200
        detail = f"http {code}"
    except urllib.error.HTTPError as exc:
        ok = False
        detail = f"http {exc.code}"
    except Exception as exc:
        ok = False
        detail = str(exc)
    duration = (time.perf_counter() - start) * 1000.0
    return CheckResult("storage", ok, duration, detail)


def _check_restore_assets() -> CheckResult:
    start = time.perf_counter()
    required = (
        "scripts/db_restore_drill.ps1",
        "scripts/verify_restore_drill_assets.py",
        "scripts/verify_restore_drill_execution.py",
        str(OPS_RUNBOOK_ROOT / "RESTORE_DRILL_RUNBOOK.md"),
    )
    missing = [path for path in required if not os.path.exists(path)]
    ok = not missing
    detail = "assets ok" if ok else "missing: " + ", ".join(missing)
    duration = (time.perf_counter() - start) * 1000.0
    return CheckResult("restore_assets", ok, duration, detail)


def _scenario_single_outage(
    *,
    name: str,
    check_fn,
    overrides: dict[str, str],
    baseline_ok: bool,
) -> ScenarioResult:
    if not baseline_ok:
        return ScenarioResult(
            name=name,
            ok=False,
            detection_ms=0.0,
            recovery_ms=0.0,
            detail="baseline unavailable; scenario skipped",
        )
    with _temporary_env(overrides):
        failed_probe = check_fn()
    recovered_probe = check_fn()
    return ScenarioResult(
        name=name,
        ok=(not failed_probe.ok) and recovered_probe.ok,
        detection_ms=failed_probe.duration_ms,
        recovery_ms=recovered_probe.duration_ms,
        detail=f"detect={failed_probe.detail}; recover={recovered_probe.detail}",
    )


def _scenario_multi_failure(*, baseline_ok: bool) -> ScenarioResult:
    if not baseline_ok:
        return ScenarioResult(
            name="combined_outage_recovery",
            ok=False,
            detection_ms=0.0,
            recovery_ms=0.0,
            detail="baseline unavailable; scenario skipped",
        )
    with _temporary_env(
        {
            "POSTGRES_PORT": "1",
            "VALKEY_URL": "redis://127.0.0.1:1/1",
            "STORAGE_ENDPOINT_URL": "http://127.0.0.1:1",
        }
    ):
        start_detection = time.perf_counter()
        db_down = _check_db()
        queue_down = _check_queue()
        storage_down = _check_storage()
        detection_ms = (time.perf_counter() - start_detection) * 1000.0

    start_recovery = time.perf_counter()
    db_up = _check_db()
    queue_up = _check_queue()
    storage_up = _check_storage()
    recovery_ms = (time.perf_counter() - start_recovery) * 1000.0

    ok = (not db_down.ok) and (not queue_down.ok) and (not storage_down.ok)
    ok = ok and db_up.ok and queue_up.ok and storage_up.ok
    detail = (
        f"down(db={db_down.detail},queue={queue_down.detail},storage={storage_down.detail}); "
        f"up(db={db_up.detail},queue={queue_up.detail},storage={storage_up.detail})"
    )
    return ScenarioResult(
        name="combined_outage_recovery",
        ok=ok,
        detection_ms=detection_ms,
        recovery_ms=recovery_ms,
        detail=detail,
    )


def _enforce_budget(result: CheckResult, *, budget_ms: float) -> None:
    if result.duration_ms > budget_ms:
        raise SystemExit(
            f"run_game_day_drill: {result.name} exceeded budget {budget_ms:.2f}ms "
            f"(actual {result.duration_ms:.2f}ms)"
        )


def _enforce_rto(result: ScenarioResult, *, budget_ms: float) -> None:
    if result.detection_ms > budget_ms or result.recovery_ms > budget_ms:
        raise SystemExit(
            f"run_game_day_drill: {result.name} exceeded RTO budget {budget_ms:.2f}ms "
            f"(detect={result.detection_ms:.2f}ms, recover={result.recovery_ms:.2f}ms)"
        )


def main() -> None:
    enforce = os.environ.get("IMMOAPP_ENFORCE_GAME_DAY", "0") == "1"
    budget_ms = float(os.environ.get("IMMOAPP_GAME_DAY_BUDGET_MS", "5000"))
    rto_budget_ms = float(os.environ.get("IMMOAPP_GAME_DAY_RTO_BUDGET_MS", "8000"))
    run_multi_failure = os.environ.get("IMMOAPP_GAME_DAY_MULTI_FAILURE", "1") == "1"
    report_path = Path(os.environ.get("IMMOAPP_GAME_DAY_REPORT", "artifacts/game_day_report.json"))
    checks = [_check_db(), _check_queue(), _check_storage(), _check_restore_assets()]
    baseline = {item.name: item.ok for item in checks}
    baseline_data_services_ok = (
        baseline.get("db", False)
        and baseline.get("queue", False)
        and baseline.get("storage", False)
    )

    scenarios: list[ScenarioResult] = [
        _scenario_single_outage(
            name="db_outage_recovery",
            check_fn=_check_db,
            overrides={"POSTGRES_PORT": "1"},
            baseline_ok=baseline.get("db", False),
        ),
        _scenario_single_outage(
            name="queue_outage_recovery",
            check_fn=_check_queue,
            overrides={"VALKEY_URL": "redis://127.0.0.1:1/1"},
            baseline_ok=baseline.get("queue", False),
        ),
        _scenario_single_outage(
            name="storage_outage_recovery",
            check_fn=_check_storage,
            overrides={"STORAGE_ENDPOINT_URL": "http://127.0.0.1:1"},
            baseline_ok=baseline.get("storage", False),
        ),
    ]
    if run_multi_failure:
        scenarios.append(_scenario_multi_failure(baseline_ok=baseline_data_services_ok))

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "enforce_mode": enforce,
        "budget_ms": budget_ms,
        "rto_budget_ms": rto_budget_ms,
        "baseline_results": [asdict(item) for item in checks],
        "scenarios": [asdict(item) for item in scenarios],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"run_game_day_drill: report written to {report_path}")

    if enforce:
        failed = [item for item in checks if not item.ok]
        if failed:
            raise SystemExit(
                "run_game_day_drill: failures: "
                + ", ".join(f"{item.name} ({item.detail})" for item in failed)
            )
        for item in checks:
            _enforce_budget(item, budget_ms=budget_ms)
        failed_scenarios = [item for item in scenarios if not item.ok]
        if failed_scenarios:
            raise SystemExit(
                "run_game_day_drill: scenario failures: "
                + ", ".join(f"{item.name} ({item.detail})" for item in failed_scenarios)
            )
        for item in scenarios:
            _enforce_rto(item, budget_ms=rto_budget_ms)

    if any(not item.ok for item in checks) or any(not item.ok for item in scenarios):
        print("run_game_day_drill: completed with warnings")
    else:
        print("run_game_day_drill: OK")


if __name__ == "__main__":
    main()
