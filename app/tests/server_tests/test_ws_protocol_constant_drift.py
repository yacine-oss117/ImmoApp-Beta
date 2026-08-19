from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

SHARED_CONSTANTS_FILE = "core/contracts/ws_protocol.py"
TARGET_FILES = (
    "server/api/ws_auth.py",
    "server/api/ws_notifications.py",
    "server/api/ws_tasks.py",
    "server/api/ws_protocol.py",
    "app/widgets/notification_hub.py",
    "app/utils/task_push.py",
)
FORBIDDEN_VALUES: set[object] = {
    "control",
    "ping",
    "pong",
    "heartbeat",
    "auth_expiring",
    4400,
    4401,
    4403,
}


def _assigned_literal_values(tree: ast.AST) -> list[object]:
    values: list[object] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            value = node.value
        else:
            continue
        if isinstance(value, ast.Constant):
            values.append(value.value)
    return values


def test_ws_protocol_literals_live_only_in_shared_contract() -> None:
    violations: list[str] = []
    for rel in TARGET_FILES:
        if rel == SHARED_CONSTANTS_FILE:
            continue
        path = REPO_ROOT / rel
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
        for value in _assigned_literal_values(tree):
            if value in FORBIDDEN_VALUES:
                violations.append(f"{rel}: {value!r}")

    assert not violations, (
        "WS control/close-code literals must come from core/contracts/ws_protocol.py.\n"
        + "\n".join(sorted(violations))
    )
