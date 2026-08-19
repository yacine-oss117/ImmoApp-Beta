from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _ratio(new_value: float, old_value: float) -> float:
    if old_value <= 0:
        return 0.0
    return max(0.0, (new_value - old_value) / old_value)


def _degradation(last_value: float, first_value: float) -> float:
    if first_value <= 0:
        return 0.0
    return max(0.0, (first_value - last_value) / first_value)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare soak-run latency, pulse drift, and count-integrity results."
    )
    parser.add_argument("--k6-summary", required=True)
    parser.add_argument("--pulse-jsonl", required=True)
    parser.add_argument("--health-jsonl", required=True)
    parser.add_argument("--count-jsonl", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    k6_summary = _load_json(Path(args.k6_summary))
    pulse_rows = _load_jsonl(Path(args.pulse_jsonl))
    health_rows = _load_jsonl(Path(args.health_jsonl))
    count_rows = _load_jsonl(Path(args.count_jsonl))

    first_pulse = pulse_rows[0] if pulse_rows else {}
    last_pulse = pulse_rows[-1] if pulse_rows else {}
    throughput_first = float(first_pulse.get("throughput_work_items_per_second") or 0.0)
    throughput_last = float(last_pulse.get("throughput_work_items_per_second") or 0.0)
    pulse_p95_first = float(first_pulse.get("latency_p95_seconds") or 0.0)
    pulse_p95_last = float(last_pulse.get("latency_p95_seconds") or 0.0)

    count_failures = [row for row in count_rows if not bool(row.get("ok", False))]
    settle_values = [
        float(row.get("settle_seconds") or 0.0) for row in count_rows if bool(row.get("ok", False))
    ]

    result = {
        "k6_summary": k6_summary,
        "pulse_count": len(pulse_rows),
        "health_sample_count": len(health_rows),
        "throughput_first": throughput_first,
        "throughput_last": throughput_last,
        "throughput_degradation_ratio": _degradation(throughput_last, throughput_first),
        "pulse_p95_first": pulse_p95_first,
        "pulse_p95_last": pulse_p95_last,
        "pulse_p95_degradation_ratio": _ratio(pulse_p95_last, pulse_p95_first),
        "count_integrity_checks_total": len(count_rows),
        "count_integrity_failures_total": len(count_failures),
        "count_integrity_failure_examples": count_failures[:10],
        "count_integrity_max_settle_seconds": max(settle_values) if settle_values else 0.0,
        "count_integrity_avg_settle_seconds": mean(settle_values) if settle_values else 0.0,
        "count_integrity_last_success_at": next(
            (row.get("checked_at") for row in reversed(count_rows) if bool(row.get("ok", False))),
            None,
        ),
    }
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
