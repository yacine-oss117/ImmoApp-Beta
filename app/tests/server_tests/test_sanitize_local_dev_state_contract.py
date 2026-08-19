from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = Path("scripts/sanitize_local_dev_state.py")
    spec = importlib.util.spec_from_file_location("sanitize_local_dev_state_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sanitize_local_dev_state_restores_runtime_primitives(monkeypatch) -> None:
    module = _load_module()
    calls: list[str] = []

    monkeypatch.setattr(module, "_configure_django", lambda: calls.append("configure"))
    monkeypatch.setattr(
        module, "_guard_local", lambda *, force_local: calls.append(f"guard:{force_local}")
    )
    monkeypatch.setattr(
        module,
        "_truncate_non_preserved_tables",
        lambda *, preserve_tables: calls.append("truncate") or 3,
    )
    monkeypatch.setattr(
        module,
        "_sanitize_accounts",
        lambda *, admin_username: calls.append("accounts")
        or {
            "deleted_users": 2,
            "deleted_agencies": 1,
            "remaining_admin_id": 1,
        },
    )
    monkeypatch.setattr(module, "_restore_runtime_primitives", lambda: calls.append("restore"))
    monkeypatch.setattr(module, "_purge_storage_bucket", lambda: 0)
    monkeypatch.setattr(module, "_clear_caches", lambda: 0)
    monkeypatch.setattr(module, "_purge_broker_queues", lambda: 0)

    monkeypatch.setattr("sys.argv", ["sanitize_local_dev_state.py", "--force-local"])

    assert module.main() == 0
    assert calls == ["configure", "guard:True", "truncate", "accounts", "restore"]
