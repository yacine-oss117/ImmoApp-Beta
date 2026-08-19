from __future__ import annotations

import logging
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_windows_runtime_permission_repair_is_wired_into_entrypoints() -> None:
    common = (ROOT / "scripts" / "common.ps1").read_text(encoding="utf-8")
    bootstrap = (ROOT / "scripts" / "bootstrap_local_runtime.ps1").read_text(
        encoding="utf-8"
    )
    quickstart = (ROOT / "quickstart.ps1").read_text(encoding="utf-8")
    client = (ROOT / "scripts" / "run_client.ps1").read_text(encoding="utf-8")
    stack = (ROOT / "scripts" / "stack.ps1").read_text(encoding="utf-8")
    repair = (ROOT / "scripts" / "repair_runtime_permissions.ps1").read_text(
        encoding="utf-8"
    )

    assert "function Repair-ImmoAppHostRuntimePermissions" in common
    assert "function Invoke-ImmoAppRuntimePermissionRepairIfNeeded" in common
    for name in (
        "ConfigRoot",
        "RuntimeRoot",
        "ToolsRoot",
        "CacheRoot",
        "LogsRoot",
        "MediaRoot",
        "TmpRoot",
        "BackupsRoot",
        "ImportsRoot",
        "OfflineSyncRoot",
        "ApiWriteQueueRoot",
    ):
        assert f"$paths.{name}" in common
    assert '"*$($sid):(OI)(CI)M"' in common
    assert '"*$($sid):(OI)(CI)RX"' in common
    assert "Repair-ImmoAppHostRuntimePermissions -DesktopUserSid $DesktopUserSid" in bootstrap
    assert '-DesktopUserSid `"$DesktopUserSid`"' in quickstart
    assert "Invoke-ImmoAppRuntimePermissionRepairIfNeeded -AutoRepair" in client
    assert "Invoke-ImmoAppRuntimePermissionRepairIfNeeded -AutoRepair" in stack
    assert "Repair-ImmoAppHostRuntimePermissions" in repair


def test_secret_acl_uses_localization_safe_sids() -> None:
    setup = (ROOT / "scripts" / "setup_openbao_identity.ps1").read_text(
        encoding="utf-8"
    )
    assert "Get-ImmoAppDesktopUserSid" in setup
    assert "*S-1-5-18:(F)" in setup
    assert "*S-1-5-32-544:(F)" in setup
    assert '"SYSTEM:(F)"' not in setup
    assert '"Administrators:(F)"' not in setup


def test_logging_falls_back_to_console_when_log_file_cannot_be_opened(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.utils import logging_config

    root_logger = logging.getLogger()
    old_handlers = list(root_logger.handlers)
    old_level = root_logger.level
    old_configured = logging_config._LOG_CONFIGURED

    def _raise_permission(*args: object, **kwargs: object) -> logging.Handler:
        raise PermissionError("denied")

    monkeypatch.setattr(logging_config, "logs_dir", lambda: tmp_path)
    monkeypatch.setattr(logging.handlers, "RotatingFileHandler", _raise_permission)

    try:
        root_logger.handlers.clear()
        logging_config._LOG_CONFIGURED = False
        logging_config.configure_logging()
        assert logging_config._LOG_CONFIGURED is True
        assert any(isinstance(handler, logging.StreamHandler) for handler in root_logger.handlers)
    finally:
        root_logger.handlers[:] = old_handlers
        root_logger.setLevel(old_level)
        logging_config._LOG_CONFIGURED = old_configured
