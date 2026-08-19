"""Fail if any Python source file exceeds a tiered line-count limit.

This is a guardrail to keep modules small and maintainable while avoiding
navigation tax by allowing slightly larger "plumbing" modules.
"""

from __future__ import annotations

import argparse
import fnmatch
from pathlib import Path


def _iter_py_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if p.is_file()]


_TIERED_LIMITS: list[tuple[str, int]] = [
    # UI shell: keep tiny to force logic out of UI.
    ("app/views/**/*.py", 300),
    ("app/widgets/**/*.py", 300),
    ("app/workers/**/*.py", 300),
    ("app/delegates/**/*.py", 300),
    ("app/core_app/**/*.py", 300),
    # Client services: API calls + mapping only.
    ("app/services/**/*.py", 350),
    # Server API: validate -> call service -> respond.
    ("server/api/**/*.py", 300),
    # Server services: orchestration + business rules.
    ("server/services/**/*.py", 500),
    # Data + matcher: more complex, still bounded.
    ("core/matcher/**/*.py", 500),
    ("core/data/**/*.py", 500),
    ("server/pg/**/*.py", 500),
    # Django apps (models/admin) can be slightly larger.
    ("server/accounts/**/*.py", 500),
    ("server/imports/**/*.py", 500),
    # Tests can be a bit larger without risking prod complexity.
    ("app/tests/**/*.py", 500),
    ("server/api/tests/**/*.py", 500),
    ("tests/**/*.py", 500),
]


def _limit_for_path(path: Path, *, default_limit: int) -> int:
    rel = path.as_posix()
    for pattern, limit in _TIERED_LIMITS:
        if fnmatch.fnmatchcase(rel, pattern):
            return limit
    return default_limit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-lines",
        type=int,
        default=500,
        help="Fallback max lines for files not matched by tiered limits.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Glob pattern(s) to exclude.",
    )
    parser.add_argument("roots", nargs="+", help="Root directories to scan.")
    args = parser.parse_args()

    max_lines = args.max_lines
    excludes = args.exclude

    offenders: list[tuple[int, int, Path]] = []
    for root in [Path(r) for r in args.roots]:
        for path in _iter_py_files(root):
            rel = path.as_posix()
            if any(path.match(pattern) or rel.endswith(pattern) for pattern in excludes):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(encoding="latin-1")
            lines = len(text.splitlines())
            limit = _limit_for_path(path, default_limit=max_lines)
            if lines > limit:
                offenders.append((lines, limit, path))

    if offenders:
        offenders.sort(reverse=True)
        print("Files exceeding line limit:")
        for lines, limit, path in offenders:
            print(f"  {lines:5d} / {limit:<3d}  {path}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
