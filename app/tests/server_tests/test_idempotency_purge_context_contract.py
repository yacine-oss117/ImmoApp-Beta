from __future__ import annotations

import ast
from pathlib import Path


def test_purge_expired_idempotency_records_uses_admin_transaction() -> None:
    source = Path("server/api/idempotency_engine.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="server/api/idempotency_engine.py")
    target_fn = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "purge_expired_idempotency_records":
            target_fn = node
            break
    assert target_fn is not None, "purge_expired_idempotency_records() must exist"

    calls_admin_transaction = False
    for node in ast.walk(target_fn):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            ctx = item.context_expr
            if (
                isinstance(ctx, ast.Call)
                and isinstance(ctx.func, ast.Name)
                and ctx.func.id == "admin_transaction"
            ):
                calls_admin_transaction = True
                break
        if calls_admin_transaction:
            break

    assert calls_admin_transaction, (
        "purge_expired_idempotency_records() must run under admin_transaction() "
        "to avoid tenant-context runtime failures in maintenance tasks."
    )
