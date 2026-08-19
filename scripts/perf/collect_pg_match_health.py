from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _bootstrap_django() -> None:
    repo_root = _repo_root()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django

    django.setup()


def _collect_via_db() -> dict[str, object]:
    _bootstrap_django()
    from server.services import match_runtime_profile, postgres_match_health

    snapshot = postgres_match_health.collect_match_artifact_health_snapshot()
    profile = match_runtime_profile.effective_profile_state()
    return {
        "match_artifact_health": asdict(snapshot),
        "match_runtime_profile": profile.profile,
        "match_runtime_profile_reason": profile.reason,
        "match_runtime_profile_sample_age_seconds": profile.sample_age_seconds,
    }


def _collect_via_api(*, base_url: str, token: str, timeout: float) -> dict[str, object]:
    request = Request(
        url=f"{base_url.rstrip('/')}/api/v1/health/snapshot/",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    return {
        "match_artifact_health": payload.get("match_artifact_health") or {},
        "match_runtime_profile": payload.get("match_runtime_profile"),
        "match_runtime_profile_reason": payload.get("match_runtime_profile_reason"),
        "match_runtime_profile_sample_age_seconds": payload.get(
            "match_runtime_profile_sample_age_seconds"
        ),
    }


def _write_payload(*, output: Path | None, payload: dict[str, object], jsonl: bool) -> None:
    if output is None:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    if jsonl:
        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True))
            handle.write("\n")
        return
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect match-artifact Postgres health snapshots."
    )
    parser.add_argument("--mode", choices=("db", "api"), default="db")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default="")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output", default="")
    parser.add_argument("--jsonl", action="store_true")
    args = parser.parse_args()

    try:
        if args.mode == "db":
            payload = _collect_via_db()
        else:
            if not args.token.strip():
                raise ValueError("--token is required in api mode")
            payload = _collect_via_api(
                base_url=str(args.base_url),
                token=str(args.token),
                timeout=float(args.timeout),
            )
    except (RuntimeError, ValueError, HTTPError, URLError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    payload["ok"] = True
    _write_payload(
        output=Path(args.output) if str(args.output).strip() else None,
        payload=payload,
        jsonl=bool(args.jsonl),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
