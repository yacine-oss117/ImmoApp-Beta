"""Authoritative assignment of Hub Manager controls to real-effect E2E journeys."""

from __future__ import annotations

ACTION_REAL_EFFECT_TESTS = {
    "status": "test_hub_manager_safe_controls.py::test_safe_controls_execute_real_effects",
    "runtime-status": "test_hub_manager_safe_controls.py::test_safe_controls_execute_real_effects",
    "connection-details": "test_hub_manager_safe_controls.py::test_safe_controls_execute_real_effects",
    "firewall-status": "test_hub_manager_safe_controls.py::test_safe_controls_execute_real_effects",
    "start": "test_installed_hub_manager_runtime.py::test_installed_managed_runtime_lifecycle",
    "stop": "test_installed_hub_manager_runtime.py::test_installed_managed_runtime_lifecycle",
    "restart": "test_installed_hub_manager_runtime.py::test_installed_managed_runtime_lifecycle",
    "health": "test_installed_hub_manager_runtime.py::test_installed_managed_runtime_lifecycle",
    "finish-hub-setup": "test_installed_hub_manager_setup.py::test_installed_finish_setup",
    "rename-hub": "test_hub_manager_maintenance.py::test_owner_maintenance_controls_execute_real_effects",
    "install-runtime-artifact": (
        "test_installed_hub_manager_setup.py::test_installed_runtime_artifact_reinstall"
    ),
    "cleanup-runtime-logs": (
        "test_hub_manager_maintenance.py::test_owner_maintenance_controls_execute_real_effects"
    ),
    "delete-hub-data": "test_hub_manager_delete_data.py::test_ui_deletes_disposable_hub_data",
    "backup-now": (
        "test_installed_hub_manager_runtime.py::test_installed_managed_runtime_lifecycle"
    ),
    "support": "test_hub_manager_safe_controls.py::test_safe_controls_execute_real_effects",
    "logs": "test_installed_hub_manager_runtime.py::test_installed_managed_runtime_lifecycle",
    "copy-url": "test_hub_manager_safe_controls.py::test_safe_controls_execute_real_effects",
    "open-desktop": "test_installed_hub_manager_utilities.py::test_installed_windows_utilities",
}

NON_ACTION_CONTROL_REAL_EFFECT_TESTS = {
    "create-owner": (
        "test_hub_manager_owner_lifecycle.py::"
        "test_hub_manager_drives_real_first_owner_lifecycle_and_protected_action"
    ),
    "activate-owner": (
        "test_hub_manager_owner_lifecycle.py::"
        "test_hub_manager_drives_real_first_owner_lifecycle_and_protected_action"
    ),
    "primary-action": (
        "test_installed_hub_manager_runtime.py::test_installed_managed_runtime_lifecycle"
    ),
    "secondary-action": "test_hub_manager_safe_controls.py::test_safe_controls_execute_real_effects",
    "technical-details": "test_hub_manager_safe_controls.py::test_safe_controls_execute_real_effects",
    "open-evidence-folder": (
        "test_hub_manager_safe_controls.py::test_safe_controls_execute_real_effects"
    ),
}
