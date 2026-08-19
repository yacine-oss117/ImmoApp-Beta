from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GIT_SH = Path("C:/Program Files/Git/usr/bin/sh.exe")


def _git_sh_path(path: Path) -> str:
    resolved = path.resolve()
    posix = resolved.as_posix()
    drive = resolved.drive.rstrip(":").lower()
    return f"/{drive}{posix[2:]}"


def test_managed_runtime_json_escape_removes_forbidden_control_bytes(
    tmp_path: Path,
) -> None:
    if not GIT_SH.is_file():
        pytest.skip("Git for Windows sh.exe is required for managed-runtime shell tests.")

    runtime_root = tmp_path / "runtime"
    runtime_bin = runtime_root / "bin"
    runtime_bin.mkdir(parents=True)
    common = runtime_bin / "managed-hub-common"
    common.write_text(
        (REPO_ROOT / "deployment/managed-runtime/bin/managed-hub-common").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    probe = tmp_path / "probe-json-escape.sh"
    probe.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "set -eu",
                '. "$IMMOAPP_RUNTIME_ROOT/bin/managed-hub-common"',
                r'''raw="$(printf 'prefix\033[0m\tline\nquote"slash\\suffix')"''',
                r'''printf '{"value":"%s"}\n' "$(json_escape "$raw")"''',
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = "/usr/bin:/bin"
    env["IMMOAPP_RUNTIME_ROOT"] = _git_sh_path(runtime_root)

    result = subprocess.run(
        [str(GIT_SH), _git_sh_path(probe)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {"value": 'prefix[0m line quote"slash\\suffix'}
    assert all(ord(character) >= 0x20 for character in result.stdout.rstrip("\r\n"))
