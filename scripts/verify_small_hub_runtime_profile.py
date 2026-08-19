"""Simulated small-Hub proof for runtime profile adaptation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(args: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True, env=env)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("tiny", "small"), default="tiny")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    env["IMMOAPP_HUB_PROFILE"] = args.profile
    env["IMMOAPP_APPDATA_ROOT"] = tempfile.mkdtemp(prefix="immoapp-small-hub-proof-")
    profile_path = Path(env["IMMOAPP_APPDATA_ROOT"]) / "config" / "hub_runtime_profile.json"

    generate = _run(
        [
            sys.executable,
            str(repo_root / "scripts" / "hub_runtime_profile.py"),
            "generate",
            "--output",
            str(profile_path),
        ],
        env=env,
    )
    if generate.returncode != 0:
        print(generate.stderr or generate.stdout, file=sys.stderr)
        return generate.returncode

    data = json.loads(profile_path.read_text(encoding="utf-8"))
    limits = data["final_resolved_limits"]
    selected = str(data["selected_profile_name"])
    if data.get("schema_version") != 2:
        raise AssertionError("generated profile did not use schema_version=2")
    if not data.get("capacity_fingerprint"):
        raise AssertionError("generated profile did not include capacity fingerprint")
    if selected != args.profile:
        raise AssertionError(f"expected {args.profile}, got {selected}")
    if limits["worker_concurrency"] > 2:
        raise AssertionError("worker concurrency was not reduced")
    if limits["import_concurrency"] > 1:
        raise AssertionError("import concurrency was not reduced")
    if limits["match_concurrency"] > 1:
        raise AssertionError("match concurrency was not reduced")
    if limits["db_pool_size"] > 4:
        raise AssertionError("DB pool size was not reduced")
    if limits["web_concurrency"] > 2:
        raise AssertionError("web concurrency was not reduced")

    export = _run(
        [
            sys.executable,
            str(repo_root / "scripts" / "hub_runtime_profile.py"),
            "export-env",
            "--output",
            str(profile_path),
            "--format",
            "dotenv",
        ],
        env=env,
    )
    if export.returncode != 0:
        print(export.stderr or export.stdout, file=sys.stderr)
        return export.returncode
    generated = profile_path.read_text(encoding="utf-8") + "\n" + export.stdout
    if (
        "12-core" in generated.lower()
        or "workers = 12" in generated
        or "concurrency = 12" in generated
    ):
        raise AssertionError("generated config contains a 12-core assumption")
    if f"IMMOAPP_HUB_RESOLVED_PROFILE={args.profile}" not in export.stdout:
        raise AssertionError("startup export did not report forced small/tiny profile")
    if "GUNICORN_WORKERS_DOCKER=" not in export.stdout:
        raise AssertionError("startup export did not include profile-derived gunicorn workers")
    if "ASGI_THREADS_DOCKER=" not in export.stdout:
        raise AssertionError("startup export did not include profile-derived ASGI threads")
    if "IMMOAPP_HUB_DB_POOL_MAX=" not in export.stdout:
        raise AssertionError("startup export did not include canonical DB pool limit")
    print(
        json.dumps(
            {
                "status": "ok",
                "profile": selected,
                "worker_concurrency": limits["worker_concurrency"],
                "import_concurrency": limits["import_concurrency"],
                "match_concurrency": limits["match_concurrency"],
                "db_pool_size": limits["db_pool_size"],
                "web_concurrency": limits["web_concurrency"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
