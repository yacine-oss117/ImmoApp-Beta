"""Pure status normalization for the installed Hub Manager UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _is_go(value: object) -> bool:
    return str(value or "").strip().upper() == "GO"


def _is_positive_status(value: object) -> bool:
    return str(value or "").strip().lower() in {
        "go",
        "created",
        "already_present",
        "already_present_valid",
        "verified",
        "ok",
    }


def _nested_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _first_non_empty(payload: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        current: Any = payload
        for segment in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(segment)
        if current not in (None, ""):
            return current
    return ""


@dataclass(frozen=True)
class HubStatusSummary:
    hub_name: str
    front_door: str
    identity_ok: bool
    state_ok: bool
    runtime_artifact_ok: bool
    runtime_start_ok: bool
    raw_front_door_ok: bool
    front_door_ok: bool
    firewall_ok: bool
    backup_ok: bool
    lan_ok: bool

    @property
    def ready(self) -> bool:
        return self.runtime_artifact_ok and self.runtime_start_ok and self.front_door_ok


def normalize_hub_status(payload: dict[str, Any]) -> HubStatusSummary:
    runtime_detection = _nested_dict(payload, "runtime_detection")
    provider = _nested_dict(runtime_detection, "provider") or _nested_dict(payload, "provider")
    live_probe = _nested_dict(runtime_detection, "front_door_live_probe") or _nested_dict(
        payload, "front_door_live_probe"
    )
    hub_name = str(
        _first_non_empty(
            payload,
            ("hub_display_name",),
            ("connection_name",),
            ("hub_identity", "hub_display_name"),
            ("identity", "hub_display_name"),
        )
    ).strip()
    front_door = str(
        _first_non_empty(
            payload,
            ("front_door_url",),
            ("hub_url",),
            ("hub_base_url",),
            ("hub_address", "front_door_url"),
            ("runtime_detection", "front_door_live_probe", "front_door_url"),
            ("front_door_live_probe", "front_door_url"),
        )
    ).strip()
    identity_ok = bool(hub_name) or _is_go(payload.get("hub_identity_status"))
    state_ok = _is_go(payload.get("hub_state_manifest_status")) or _is_go(
        payload.get("state_manifest_status")
    )
    runtime_artifact_ok = (
        _is_go(runtime_detection.get("runtime_artifact_status"))
        or _is_go(provider.get("runtime_artifact_status"))
        or _is_go(payload.get("runtime_artifact_status"))
        or _is_go(payload.get("artifact_status"))
    )
    managed_runtime_status_ok = (
        str(payload.get("action") or "").strip().lower() in {"start", "status", "restart", "health"}
        and _is_go(payload.get("runtime_command_status"))
        and (_is_go(payload.get("service_status")) or _is_go(payload.get("compose_service_status")))
        and _is_go(payload.get("front_door_health_status"))
        and _is_go(payload.get("proof_result"))
    )
    runtime_start_ok = (
        _is_go(runtime_detection.get("runtime_start_status"))
        or _is_go(provider.get("runtime_start_status"))
        or _is_go(payload.get("runtime_start_status"))
        or managed_runtime_status_ok
    )
    raw_front_door_ok = (
        _is_go(live_probe.get("front_door_health_status"))
        or _is_go(payload.get("front_door_health_status"))
        or _is_go(payload.get("web_api_health_status"))
        or str(payload.get("health_status") or "") == "200"
        or str(live_probe.get("health_status") or "") == "200"
    )
    front_door_ok = runtime_start_ok and raw_front_door_ok
    firewall_ok = _is_positive_status(
        payload.get("firewall_rule_status") or payload.get("firewall_status")
    )
    backup_ok = _is_go(payload.get("backup_status")) or _is_go(payload.get("backup_restore_status"))
    lan_ok = _is_go(payload.get("lan_workstation_status")) or (
        _is_go(payload.get("network_boundary_status"))
        and bool(payload.get("external_lan_probe_performed"))
    )
    return HubStatusSummary(
        hub_name=hub_name,
        front_door=front_door,
        identity_ok=identity_ok,
        state_ok=state_ok,
        runtime_artifact_ok=runtime_artifact_ok,
        runtime_start_ok=runtime_start_ok,
        raw_front_door_ok=raw_front_door_ok,
        front_door_ok=front_door_ok,
        firewall_ok=firewall_ok,
        backup_ok=backup_ok,
        lan_ok=lan_ok,
    )
