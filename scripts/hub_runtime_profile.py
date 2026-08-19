"""Generate, validate, and export the Hub runtime profile."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.runtime.hub_runtime_profile import (  # noqa: E402
    HubRuntimeProfileError,
    ensure_hub_runtime_profile,
    hub_runtime_profile_path,
    load_hub_runtime_profile,
    summarize_hub_runtime_profile,
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("generate", "print", "validate", "export-env"),
        help="Profile operation to run.",
    )
    parser.add_argument("--output", default="", help="Optional profile JSON path.")
    parser.add_argument("--format", choices=("json", "powershell", "dotenv"), default="json")
    parser.add_argument("--profile", default="", help="Temporary IMMOAPP_HUB_PROFILE override.")
    return parser.parse_args(argv)


def _with_profile_override(profile: str) -> None:
    if profile:
        os.environ["IMMOAPP_HUB_PROFILE"] = profile


def _profile_path(raw: str) -> Path | None:
    return Path(raw) if raw else None


def _print_env(profile_format: str, env_values: dict[str, str]) -> None:
    if profile_format == "json":
        print(json.dumps(env_values, indent=2, sort_keys=True))
        return
    for key, value in sorted(env_values.items()):
        if profile_format == "powershell":
            escaped = value.replace("'", "''")
            print(f"$env:{key} = '{escaped}'")
        else:
            print(f"{key}={value}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    _with_profile_override(str(args.profile or ""))
    path = _profile_path(str(args.output or ""))
    try:
        if args.action == "generate":
            profile = ensure_hub_runtime_profile(path)
            print(str(path or hub_runtime_profile_path()))
            print(json.dumps(summarize_hub_runtime_profile(profile), indent=2, sort_keys=True))
            return 0
        if args.action == "validate":
            loaded_profile = load_hub_runtime_profile(path)
            if loaded_profile is None:
                raise HubRuntimeProfileError("Hub runtime profile file is missing.")
            print(
                json.dumps(summarize_hub_runtime_profile(loaded_profile), indent=2, sort_keys=True)
            )
            return 0
        if args.action == "print":
            profile = ensure_hub_runtime_profile(path)
            print(json.dumps(profile.to_json_dict(), indent=2, sort_keys=True))
            return 0
        if args.action == "export-env":
            profile = ensure_hub_runtime_profile(path)
            _print_env(str(args.format), profile.to_env())
            return 0
    except HubRuntimeProfileError as exc:
        print(f"Hub runtime profile error: {exc}", file=sys.stderr)
        return 64
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
