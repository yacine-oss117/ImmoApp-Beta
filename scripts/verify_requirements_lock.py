from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_FILES = (
    REPO_ROOT / "requirements" / "server.txt",
    REPO_ROOT / "requirements" / "client.txt",
)

_PIN_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?)==(?P<version>[^\s;]+)(?:\s*;.+)?$"
)


def _normalize_name(raw: str) -> str:
    base = raw.split("[", 1)[0]
    return base.replace("_", "-").lower()


def _iter_requirement_lines(path: Path) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append((lineno, line))
    return out


def _verify_single_file(path: Path, seen: dict[str, str]) -> list[str]:
    errors: list[str] = []
    rel = path.relative_to(REPO_ROOT).as_posix()
    if not path.exists():
        return [f"{rel}: file not found"]

    for lineno, line in _iter_requirement_lines(path):
        if line.startswith("-r "):
            errors.append(
                f"{rel}:{lineno}: nested include is not allowed; pin directly in this file"
            )
            continue
        if line.startswith(("-e ", "--editable", "--index-url", "--extra-index-url")):
            errors.append(
                f"{rel}:{lineno}: editable/index directives are forbidden in locked requirements"
            )
            continue
        if "@" in line or "git+" in line or "://" in line:
            errors.append(
                f"{rel}:{lineno}: URL/source requirements are forbidden in locked requirements"
            )
            continue

        match = _PIN_RE.match(line)
        if not match:
            errors.append(
                f"{rel}:{lineno}: requirement must be strictly pinned with '==' (got {line!r})"
            )
            continue
        raw_name = match.group("name")
        version = match.group("version")
        if "*" in version:
            errors.append(f"{rel}:{lineno}: wildcard versions are forbidden (got {version!r})")
            continue
        name = _normalize_name(raw_name)
        previous = seen.get(name)
        if previous is None:
            seen[name] = version
            continue
        if previous != version:
            errors.append(
                f"{rel}:{lineno}: version conflict for {name!r}: saw {previous!r} earlier, now {version!r}"
            )

    return errors


def main() -> int:
    errors: list[str] = []
    seen: dict[str, str] = {}
    for path in REQUIREMENTS_FILES:
        errors.extend(_verify_single_file(path, seen))

    if errors:
        print("verify_requirements_lock: FAIL")
        for item in errors:
            print(f" - {item}")
        return 1

    print("verify_requirements_lock: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
