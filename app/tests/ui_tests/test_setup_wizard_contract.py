from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import Mock

import pytest

pytest.importorskip("PySide6")

from app.services.api_config import normalize_hub_front_door_url
from app.widgets import setup_wizard as module

pytestmark = pytest.mark.ui


def test_setup_wizard_discovery_success_updates_primary_action(
    monkeypatch: pytest.MonkeyPatch, qapp: Any
) -> None:
    monkeypatch.setattr(
        module,
        "run_background_result",
        lambda func, on_success, on_error: on_success(
            [
                {
                    "hub_display_name": "Main Office",
                    "front_door_url": "http://10.10.10.10:8000",
                    "port": 8000,
                    "online_status": "Online",
                    "proof_scope": "front_door_discovery",
                    "connectable": True,
                }
            ]
        ),
    )

    dialog = module.SetupWizardDialog()

    assert dialog._btn_use_found.isEnabled() is True
    assert "Main Office" in dialog._btn_use_found.text()
    assert "Verified ImmoApp Hub" in dialog._found_label.text()
    assert "10.10.10.10" not in dialog._found_label.text()
    assert "10.10.10.10" not in dialog._technical_label.text()
    assert dialog._manual_url.text() == ""
    dialog._toggle_technical_details()
    assert "10.10.10.10" in dialog._technical_label.text()
    assert "Front-door port: 8000" in dialog._technical_label.text()


def test_setup_wizard_troubleshooting_is_plain_and_safe(
    monkeypatch: pytest.MonkeyPatch, qapp: Any
) -> None:
    monkeypatch.setattr(
        module,
        "run_background_result",
        lambda func, on_success, on_error: on_success([]),
    )

    dialog = module.SetupWizardDialog()
    help_text = dialog._troubleshooting_label.text()

    for token in (
        "same office Wi-Fi",
        "Ethernet",
        "Guest Wi-Fi",
        "firewall",
        "VLAN/subnet",
        "backend/internal ports",
        "Hub Manager > Connection details",
    ):
        assert token in help_text


def test_setup_wizard_discovery_error_keeps_manual_path(
    monkeypatch: pytest.MonkeyPatch, qapp: Any
) -> None:
    monkeypatch.setattr(
        module,
        "run_background_result",
        lambda func, on_success, on_error: on_error(RuntimeError("down")),
    )

    dialog = module.SetupWizardDialog()

    assert dialog._btn_use_found.isEnabled() is False
    assert "automatic search" in dialog._status.text().lower()


def test_hub_front_door_url_rejects_workstation_localhost_and_backend_port() -> None:
    assert normalize_hub_front_door_url("http://10.10.10.10:8000") == "http://10.10.10.10:8000"
    assert normalize_hub_front_door_url("main-office.local:8000") == "http://main-office.local:8000"
    with pytest.raises(ValueError):
        normalize_hub_front_door_url("http://localhost:8000")
    with pytest.raises(ValueError):
        normalize_hub_front_door_url("http://10.10.10.10:18000")


def test_setup_wizard_manual_save_uses_verified_front_door_path(
    monkeypatch: pytest.MonkeyPatch, qapp: Any
) -> None:
    saved = Mock(
        return_value={
            "normalized_url": "http://10.10.10.10:8000",
            "hub_display_name": "Verified Office",
        }
    )
    monkeypatch.setattr(module, "set_verified_api_config", saved)
    monkeypatch.setattr(
        module,
        "run_background_result",
        lambda func, on_success, on_error: on_success([]),
    )
    dialog = module.SetupWizardDialog()
    dialog._manual_url.setText("http://10.10.10.10:8000")

    dialog._connect_manual()

    saved.assert_called_once_with(
        base_url="http://10.10.10.10:8000",
        allow_local_hub=False,
        connection_source="manual",
    )
    assert "Verified Office saved" in dialog._status.text()


def test_setup_wizard_failed_probe_does_not_accept_or_save(
    monkeypatch: pytest.MonkeyPatch, qapp: Any
) -> None:
    saved = Mock(side_effect=ValueError("not a hub"))
    monkeypatch.setattr(module, "set_verified_api_config", saved)
    monkeypatch.setattr(
        module,
        "run_background_result",
        lambda func, on_success, on_error: on_success([]),
    )
    dialog = module.SetupWizardDialog()
    accepted = Mock()
    monkeypatch.setattr(dialog, "accept", accepted)
    dialog._manual_url.setText("http://10.10.10.10:8000")

    dialog._connect_manual()

    saved.assert_called_once()
    accepted.assert_not_called()
    assert "does not look like an ImmoApp Hub" in dialog._status.text()


def test_setup_wizard_discovery_legacy_internal_beacon_cannot_connect(
    monkeypatch: pytest.MonkeyPatch, qapp: Any
) -> None:
    saved = Mock()
    monkeypatch.setattr(module, "set_verified_api_config", saved)
    monkeypatch.setattr(
        module,
        "run_background_result",
        lambda func, on_success, on_error: on_success(
            [
                {
                    "agency": "Legacy Office",
                    "ip": "10.10.10.10",
                    "port": 18000,
                    "source": "legacy_internal",
                    "proof_scope": "internal_only",
                    "connectable": False,
                }
            ]
        ),
    )

    dialog = module.SetupWizardDialog()
    dialog._connect_found()

    assert dialog._btn_use_found.isEnabled() is False
    assert "10.10.10.10" not in dialog._found_label.text()
    assert "Not available" in dialog._found_label.text()
    saved.assert_not_called()


def test_setup_wizard_found_save_uses_verified_identity_name(
    monkeypatch: pytest.MonkeyPatch, qapp: Any
) -> None:
    saved = Mock(
        return_value={
            "normalized_url": "http://10.10.10.10:8000",
            "hub_display_name": "Verified Office",
        }
    )
    monkeypatch.setattr(module, "set_verified_api_config", saved)
    monkeypatch.setattr(
        module,
        "run_background_result",
        lambda func, on_success, on_error: on_success(
            [
                {
                    "hub_display_name": "Untrusted Beacon Name",
                    "front_door_url": "http://10.10.10.10:8000",
                    "port": 8000,
                    "proof_scope": "front_door_discovery",
                    "connectable": True,
                }
            ]
        ),
    )

    dialog = module.SetupWizardDialog()
    dialog._connect_found()

    saved.assert_called_once_with(
        base_url="http://10.10.10.10:8000",
        allow_local_hub=False,
        connection_source="discovery",
    )
    assert "Verified Office saved" in dialog._status.text()


def test_setup_wizard_does_not_import_low_level_api_config_writer() -> None:
    source = inspect.getsource(module)

    assert "set_api_config" not in source
    assert "set_verified_api_config" in source
