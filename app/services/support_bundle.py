"""Local desktop support bundle collection with strict secret redaction."""

from __future__ import annotations

import json
import os
import platform
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
from urllib import error, request

from app.core_app.paths import config_path, logs_dir, tmp_dir
from app.services.api_config import get_api_config
from app.services.build_identity import get_build_identity
from core.runtime.hub_runtime_profile import (
    HubRuntimeProfileError,
    hub_runtime_profile_path,
    load_hub_runtime_profile,
    summarize_hub_runtime_profile,
)

_SECRET_KEY_RE = re.compile(
    r"(authorization|password|passwd|secret|token|nonce|refresh|access|access_token|accessToken|"
    r"refresh_token|refreshToken|idToken|id_token|sessionToken|session_token|client_secret|"
    r"clientSecret|credential|presigned|signature|api[_-]?key|apiKey|xApiKey|private[_-]?key|"
    r"privateKey|certificate|cert|key_material|x-api-key|token[_-]?(?:file|path)|"
    r"secret[_-]?(?:file|path|id)|password[_-]?(?:file|path)|credential[_-]?(?:file|path)|"
    r"private[_-]?key[_-]?(?:file|path)|\.env)",
    re.IGNORECASE,
)
_PRESIGNED_RE = re.compile(r"([?&]X-Amz-[^=]+)=([^&\s]+)", re.IGNORECASE)
_QUERY_SECRET_RE = re.compile(
    r"([?&](?:api[_-]?key|apiKey|xApiKey|token|access[_-]?token|accessToken|"
    r"refresh[_-]?token|refreshToken|id[_-]?token|idToken|session[_-]?token|"
    r"sessionToken|client[_-]?secret|clientSecret|signature)=)([^&\s]+)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_AUTH_HEADER_RE = re.compile(r"(?im)^(\s*Authorization\s*:\s*)(Basic|Token|Bearer)\s+[^\r\n]+")
_API_KEY_HEADER_RE = re.compile(
    r"(?im)^(\s*(?:X-Api-Key|X-API-KEY|api-key|api_key|apiKey|xApiKey)\s*:\s*)[^\r\n]+"
)
_KV_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|nonce|access_token|accessToken|refresh_token|refreshToken|"
    r"id_token|idToken|session_token|sessionToken|client_secret|clientSecret|apiKey|api_key|"
    r"xApiKey|privateKey|private_key|key_material|credential|certificate|cert|"
    r"signature|x-api-key|api-key|token[_-]?(?:file|path)|secret[_-]?(?:file|path|id)|"
    r"password[_-]?(?:file|path)|credential[_-]?(?:file|path)|"
    r"private[_-]?key[_-]?(?:file|path))\s*=\s*([^\s&;]+)"
)
_COLON_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|nonce|access_token|accessToken|refresh_token|refreshToken|"
    r"id_token|idToken|session_token|sessionToken|client_secret|clientSecret|apiKey|api_key|"
    r"xApiKey|privateKey|private_key|key_material|credential|certificate|cert|"
    r"signature|x-api-key|api-key|token[_-]?(?:file|path)|secret[_-]?(?:file|path|id)|"
    r"password[_-]?(?:file|path)|credential[_-]?(?:file|path)|"
    r"private[_-]?key[_-]?(?:file|path))\s*:\s*([^\s&;]+)"
)
_JSON_SECRET_RE = re.compile(
    r'(?i)("(?:authorization|password|passwd|secret|token|nonce|access_token|accessToken|'
    r"refresh_token|refreshToken|id_token|idToken|session_token|sessionToken|client_secret|"
    r"clientSecret|apiKey|api_key|xApiKey|privateKey|private_key|key_material|credential|certificate|cert|"
    r"x-api-key|api-key|signature|token[_-]?(?:file|path)|secret[_-]?(?:file|path|id)|"
    r"password[_-]?(?:file|path)|credential[_-]?(?:file|path)|"
    r'private[_-]?key[_-]?(?:file|path))"\s*:\s*")([^"]*)(")'
)
_SQL_PASSWORD_RE = re.compile(r"(?i)\b(WITH\s+PASSWORD\s+)'[^']*'")
_QUOTED_PASSWORD_RE = re.compile(r"(?i)\b(password\s+)'[^']*'")
_PEM_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.DOTALL,
)
_PEM_CERTIFICATE_RE = re.compile(
    r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
    re.DOTALL,
)
_NON_SECRET_AUTH_SUMMARY_KEYS = {
    "hub_owner_authorization_evidence",
    "authorization_scope",
}


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _redact_text(value: str) -> str:
    text = _AUTH_HEADER_RE.sub(r"\1\2 [REDACTED]", str(value))
    text = _API_KEY_HEADER_RE.sub(r"\1[REDACTED]", text)
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _PRESIGNED_RE.sub(r"\1=[REDACTED]", text)
    text = _QUERY_SECRET_RE.sub(r"\1[REDACTED]", text)
    text = _PEM_PRIVATE_KEY_RE.sub("[REDACTED PRIVATE KEY]", text)
    text = _PEM_CERTIFICATE_RE.sub("[REDACTED CERTIFICATE]", text)
    text = _SQL_PASSWORD_RE.sub(r"\1'[REDACTED]'", text)
    text = _QUOTED_PASSWORD_RE.sub(r"\1'[REDACTED]'", text)
    text = _JSON_SECRET_RE.sub(r"\1[REDACTED]\3", text)
    text = _KV_SECRET_RE.sub(r"\1=[REDACTED]", text)
    return _COLON_SECRET_RE.sub(r"\1: [REDACTED]", text)


def _sanitize_mapping(data: Mapping[str, object]) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    for key, raw_value in data.items():
        name = str(key)
        if name in _NON_SECRET_AUTH_SUMMARY_KEYS:
            if isinstance(raw_value, Mapping):
                sanitized[name] = _sanitize_mapping(raw_value)
            else:
                sanitized[name] = _redact_text(str(raw_value))
        elif _SECRET_KEY_RE.search(name):
            sanitized[name] = "[REDACTED]"
        elif isinstance(raw_value, Mapping):
            sanitized[name] = _sanitize_mapping(raw_value)
        elif isinstance(raw_value, list):
            sanitized[name] = [
                _sanitize_mapping(item) if isinstance(item, Mapping) else _redact_text(str(item))
                for item in raw_value
            ]
        else:
            sanitized[name] = _redact_text(str(raw_value))
    return sanitized


def _read_sanitized_client_config() -> dict[str, object]:
    path = config_path("client_api.json")
    if not path.exists():
        return {"exists": False}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"exists": True, "read_error": exc.__class__.__name__}
    if not isinstance(raw, dict):
        return {"exists": True, "read_error": "invalid_shape"}
    allowed = {
        "base_url": raw.get("base_url", ""),
        "username": raw.get("username", ""),
        "schema": raw.get("schema", ""),
        "remember_session": raw.get("remember_session", ""),
    }
    return {"exists": True, **_sanitize_mapping(allowed)}


def _health_probe(base_url: str | None, timeout_seconds: float) -> dict[str, object]:
    if not base_url:
        return {"checked": False, "reason": "base_url_not_configured"}
    url = f"{base_url.rstrip('/')}/api/v1/health/"
    try:
        with request.urlopen(url, timeout=max(0.5, timeout_seconds)) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            return {
                "checked": True,
                "url": url,
                "status": int(response.status),
                "body_preview": _redact_text(body[:1000]),
            }
    except error.HTTPError as exc:
        return {"checked": True, "url": url, "status": int(exc.code), "error": exc.reason}
    except Exception as exc:
        return {"checked": True, "url": url, "status": None, "error": exc.__class__.__name__}


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _add_log_files(bundle: zipfile.ZipFile) -> list[str]:
    added: list[str] = []
    for path in sorted(logs_dir().glob("app.log*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        bundle.writestr(f"logs/{path.name}", _redact_text(text))
        added.append(path.name)
    return added


def _read_hub_runtime_profile_summary() -> dict[str, object]:
    try:
        profile = load_hub_runtime_profile()
    except HubRuntimeProfileError as exc:
        return {
            "exists": True,
            "path": str(hub_runtime_profile_path()),
            "read_error": str(exc),
        }
    if profile is None:
        return {"exists": False, "path": str(hub_runtime_profile_path())}
    return {
        "exists": True,
        "path": str(hub_runtime_profile_path()),
        **summarize_hub_runtime_profile(profile),
    }


def _read_hub_status_evidence_summary() -> dict[str, object]:
    path = logs_dir() / "hub_status_evidence.json"
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"exists": True, "path": str(path), "read_error": exc.__class__.__name__}
    if not isinstance(raw, dict):
        return {"exists": True, "path": str(path), "read_error": "invalid_shape"}
    allowed = {
        "kind": raw.get("kind", ""),
        "schema_version": raw.get("schema_version", ""),
        "created_at_utc": raw.get("created_at_utc", ""),
        "proof_result": raw.get("proof_result", ""),
        "failure_reason": raw.get("failure_reason", ""),
        "hub_status": raw.get("hub_status", ""),
        "hub_base_url": raw.get("hub_base_url", ""),
        "hub_address": raw.get("hub_address", {}),
        "runtime_dependency_mode": raw.get("runtime_dependency_mode", ""),
        "agency_install_status": raw.get("agency_install_status", ""),
        "internal_proof_status": raw.get("internal_proof_status", ""),
        "runtime_user_visible": raw.get("runtime_user_visible", ""),
        "provider_validation_status": raw.get("provider_validation_status", ""),
        "runtime_state": raw.get("runtime_state", ""),
        "compose_state": raw.get("compose_state", ""),
        "status_reason_code": raw.get("status_reason_code", ""),
        "transport_security": raw.get("transport_security", ""),
        "database_health": raw.get("database_health", ""),
        "storage_photos_health": raw.get("storage_photos_health", ""),
        "worker_health": raw.get("worker_health", ""),
        "backup_status": raw.get("backup_status", {}),
        "managed_runtime_log_retention": raw.get("managed_runtime_log_retention", {}),
        "runtime_detection": raw.get("runtime_detection", {}),
        "runtime_provider_proof": raw.get("runtime_provider_proof", {}),
        "failing_services": raw.get("failing_services", []),
        "missing_services": raw.get("missing_services", []),
        "starting_services": raw.get("starting_services", []),
        "windows_firewall_rule_status": raw.get("windows_firewall_rule_status", ""),
    }
    return {"exists": True, "path": str(path), **_sanitize_mapping(allowed)}


def _read_managed_runtime_log_retention_summary() -> dict[str, object]:
    path = logs_dir() / "managed_runtime_log_retention.json"
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"exists": True, "path": str(path), "read_error": exc.__class__.__name__}
    if not isinstance(raw, dict):
        return {"exists": True, "path": str(path), "read_error": "invalid_shape"}
    allowed = {
        "kind": raw.get("kind", ""),
        "schema_version": raw.get("schema_version", ""),
        "created_at_utc": raw.get("created_at_utc", ""),
        "proof_result": raw.get("proof_result", ""),
        "reason_code": raw.get("reason_code", ""),
        "retention_days": raw.get("retention_days", ""),
        "max_total_bytes": raw.get("max_total_bytes", ""),
        "scanned_file_count": raw.get("scanned_file_count", ""),
        "deleted_file_count": raw.get("deleted_file_count", ""),
        "deleted_bytes": raw.get("deleted_bytes", ""),
        "retained_bytes": raw.get("retained_bytes", ""),
        "skipped_file_count": raw.get("skipped_file_count", ""),
        "skipped_reasons": raw.get("skipped_reasons", []),
        "agency_install_status": raw.get("agency_install_status", ""),
    }
    return {"exists": True, "path": str(path), **_sanitize_mapping(allowed)}


def _read_hub_install_evidence_summary() -> dict[str, object]:
    path = logs_dir() / "hub_install_evidence.json"
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"exists": True, "path": str(path), "read_error": exc.__class__.__name__}
    if not isinstance(raw, dict):
        return {"exists": True, "path": str(path), "read_error": "invalid_shape"}
    allowed = {
        "kind": raw.get("kind", ""),
        "schema_version": raw.get("schema_version", ""),
        "created_at_utc": raw.get("created_at_utc", ""),
        "proof_result": raw.get("proof_result", ""),
        "failure_reason": raw.get("failure_reason", ""),
        "install_role": raw.get("install_role", ""),
        "hub_base_url": raw.get("hub_base_url", ""),
        "backend_url_is_localhost": raw.get("backend_url_is_localhost", ""),
        "runtime_dependency_mode": raw.get("runtime_dependency_mode", ""),
        "agency_install_status": raw.get("agency_install_status", ""),
        "internal_proof_status": raw.get("internal_proof_status", ""),
        "runtime_user_visible": raw.get("runtime_user_visible", ""),
        "hub_manager_script_path": raw.get("hub_manager_script_path", ""),
        "hub_manager_script_source": raw.get("hub_manager_script_source", ""),
        "desktop_exe_path": raw.get("desktop_exe_path", ""),
        "desktop_exe_source": raw.get("desktop_exe_source", ""),
        "proof_scope": raw.get("proof_scope", ""),
        "runtime_detection": raw.get("runtime_detection", {}),
        "runtime_provider_proof": raw.get("runtime_provider_proof", {}),
        "transport_security": raw.get("transport_security", ""),
    }
    return {"exists": True, "path": str(path), **_sanitize_mapping(allowed)}


def _read_hub_runtime_detection_summary() -> dict[str, object]:
    path = logs_dir() / "hub_runtime_detection.json"
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"exists": True, "path": str(path), "read_error": exc.__class__.__name__}
    if not isinstance(raw, dict):
        return {"exists": True, "path": str(path), "read_error": "invalid_shape"}
    allowed = {
        "kind": raw.get("kind", ""),
        "schema_version": raw.get("schema_version", ""),
        "created_at_utc": raw.get("created_at_utc", ""),
        "runtime_dependency_mode": raw.get("runtime_dependency_mode", ""),
        "docker_cli_available": raw.get("docker_cli_available", ""),
        "docker_engine_reachable": raw.get("docker_engine_reachable", ""),
        "docker_desktop_detected": raw.get("docker_desktop_detected", ""),
        "compose_available": raw.get("compose_available", ""),
        "runtime_version": raw.get("runtime_version", ""),
        "runtime_install_path": raw.get("runtime_install_path", ""),
        "runtime_command": raw.get("runtime_command", ""),
        "compose_command": raw.get("compose_command", ""),
        "compose_arguments_prefix": raw.get("compose_arguments_prefix", []),
        "runtime_is_user_visible": raw.get("runtime_is_user_visible", ""),
        "agency_install_status": raw.get("agency_install_status", ""),
        "internal_proof_status": raw.get("internal_proof_status", ""),
        "runtime_artifact_status": raw.get("runtime_artifact_status", ""),
        "runtime_start_status": raw.get("runtime_start_status", ""),
        "runtime_start_reason_code": raw.get("runtime_start_reason_code", ""),
        "runtime_start_evidence_path": raw.get("runtime_start_evidence_path", ""),
        "runtime_start_evidence_sha256": raw.get("runtime_start_evidence_sha256", ""),
        "front_door_health_status": raw.get("front_door_health_status", ""),
        "front_door_live_probe": raw.get("front_door_live_probe", {}),
        "reason_code": raw.get("reason_code", ""),
        "reason": raw.get("reason", ""),
        "recommended_next_action": raw.get("recommended_next_action", ""),
        "provider_config_path": raw.get("provider_config_path", ""),
        "provider_config_present": raw.get("provider_config_present", ""),
        "provider_config_valid": raw.get("provider_config_valid", ""),
        "provider_config_error": raw.get("provider_config_error", ""),
        "provider_validation_status": raw.get("provider_validation_status", ""),
        "provider": raw.get("provider", {}),
    }
    return {"exists": True, "path": str(path), **_sanitize_mapping(allowed)}


def _read_runtime_candidate_evidence_summary(file_name: str) -> dict[str, object]:
    path = logs_dir() / file_name
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"exists": True, "path": str(path), "read_error": exc.__class__.__name__}
    if not isinstance(raw, dict):
        return {"exists": True, "path": str(path), "read_error": "invalid_shape"}
    return {"exists": True, "path": str(path), **_sanitize_mapping(raw)}


def _read_managed_runtime_package_inventory_summary() -> dict[str, object]:
    detection = _read_hub_runtime_detection_summary()
    if detection.get("provider_validation_status") != "valid":
        return {
            "exists": False,
            "provider_validation_status": detection.get("provider_validation_status", ""),
        }
    provider = detection.get("provider", {})
    if not isinstance(provider, Mapping):
        return {"exists": False}
    inventory_path = str(provider.get("package_inventory_path") or "")
    if not inventory_path:
        return {"exists": False}
    path = Path(inventory_path)
    if not path.exists():
        return {"exists": False, "path": inventory_path}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"exists": True, "path": inventory_path, "read_error": exc.__class__.__name__}
    if not isinstance(raw, dict):
        return {"exists": True, "path": inventory_path, "read_error": "invalid_shape"}
    allowed = {
        "kind": raw.get("kind", ""),
        "schema_version": raw.get("schema_version", ""),
        "created_at_utc": raw.get("created_at_utc", ""),
        "proof_result": raw.get("proof_result", ""),
        "reason_code": raw.get("reason_code", ""),
        "failure_reason": raw.get("failure_reason", ""),
        "package_path": raw.get("package_path", ""),
        "package_sha256": raw.get("package_sha256", ""),
        "package_bytes": raw.get("package_bytes", ""),
        "package_file_count": raw.get("package_file_count", ""),
        "file_count": raw.get("file_count", ""),
        "total_bytes": raw.get("total_bytes", ""),
        "source_commit_sha": raw.get("source_commit_sha", ""),
        "source_tree_clean": raw.get("source_tree_clean", ""),
        "source_commit_override": raw.get("source_commit_override", ""),
        "runtime_source_origin": raw.get("runtime_source_origin", ""),
        "dirty_files_summary_count": raw.get("dirty_files_summary_count", ""),
        "critical_executables": raw.get("critical_executables", {}),
        "forbidden_matches": raw.get("forbidden_matches", []),
        "proof_only": raw.get("proof_only", ""),
    }
    return {"exists": True, "path": inventory_path, **_sanitize_mapping(allowed)}


def _read_managed_wsl2_runtime_artifact_inventory_summary() -> dict[str, object]:
    detection = _read_hub_runtime_detection_summary()
    provider_validation_status = detection.get("provider_validation_status", "")
    inventory_path = ""
    provider = detection.get("provider", {})
    if isinstance(provider, Mapping):
        inventory_path = str(provider.get("runtime_artifact_inventory_path") or "")
    if not inventory_path:
        default_path = config_path("managed_wsl2_runtime_artifact_inventory.json")
        inventory_path = str(default_path) if default_path.exists() else ""
    if not inventory_path:
        return {
            "exists": False,
            "provider_validation_status": provider_validation_status,
        }
    path = Path(inventory_path)
    if not path.exists():
        return {"exists": False, "path": inventory_path}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"exists": True, "path": inventory_path, "read_error": exc.__class__.__name__}
    if not isinstance(raw, dict):
        return {"exists": True, "path": inventory_path, "read_error": "invalid_shape"}
    allowed = {
        "kind": raw.get("kind", ""),
        "schema_version": raw.get("schema_version", ""),
        "created_at_utc": raw.get("created_at_utc", ""),
        "source_commit_sha": raw.get("source_commit_sha", ""),
        "artifact_root": raw.get("artifact_root", ""),
        "artifact_tree_sha256": raw.get("artifact_tree_sha256", ""),
        "file_count": raw.get("file_count", ""),
        "total_bytes": raw.get("total_bytes", ""),
        "required_entries": raw.get("required_entries", {}),
        "forbidden_path_count": raw.get("forbidden_path_count", ""),
        "forbidden_path_matches": raw.get("forbidden_path_matches", []),
        "runtime_dependency_mode": raw.get("runtime_dependency_mode", ""),
        "runtime_artifact_status": raw.get("runtime_artifact_status", ""),
        "runtime_start_status": raw.get("runtime_start_status", ""),
        "internal_proof_status": raw.get("internal_proof_status", ""),
        "agency_install_status": raw.get("agency_install_status", ""),
        "proof_result": raw.get("proof_result", ""),
        "reason_code": raw.get("reason_code", ""),
    }
    return {"exists": True, "path": inventory_path, **_sanitize_mapping(allowed)}


def _read_managed_wsl2_runtime_image_bundle_inventory_summary() -> dict[str, object]:
    path = config_path("managed_wsl2_runtime_image_bundle_inventory.json")
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"exists": True, "path": str(path), "read_error": exc.__class__.__name__}
    if not isinstance(raw, dict):
        return {"exists": True, "path": str(path), "read_error": "invalid_shape"}
    allowed = {
        "kind": raw.get("kind", ""),
        "schema_version": raw.get("schema_version", ""),
        "created_at_utc": raw.get("created_at_utc", ""),
        "source_commit_sha": raw.get("source_commit_sha", ""),
        "image_archive_path": raw.get("image_archive_path", ""),
        "image_archive_sha256": raw.get("image_archive_sha256", ""),
        "image_archive_bytes": raw.get("image_archive_bytes", ""),
        "image_count": raw.get("image_count", ""),
        "images": raw.get("images", []),
        "docker_save_invoked": raw.get("docker_save_invoked", ""),
        "docker_pull_invoked": raw.get("docker_pull_invoked", ""),
        "package_manager_install_invoked": raw.get("package_manager_install_invoked", ""),
        "compose_pull_policy_required": raw.get("compose_pull_policy_required", ""),
        "proof_result": raw.get("proof_result", ""),
        "reason_code": raw.get("reason_code", ""),
    }
    return {"exists": True, "path": str(path), **_sanitize_mapping(allowed)}


def _read_hub_network_boundary_summary() -> dict[str, object]:
    path = logs_dir() / "hub_network_boundary_evidence.json"
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"exists": True, "path": str(path), "read_error": exc.__class__.__name__}
    if not isinstance(raw, dict):
        return {"exists": True, "path": str(path), "read_error": "invalid_shape"}
    allowed = {
        "kind": raw.get("kind", ""),
        "schema_version": raw.get("schema_version", ""),
        "created_at_utc": raw.get("created_at_utc", ""),
        "proof_result": raw.get("proof_result", ""),
        "failure_reason": raw.get("failure_reason", ""),
        "proof_scope": raw.get("proof_scope", ""),
        "external_lan_probe_performed": raw.get("external_lan_probe_performed", ""),
        "external_lan_probe_required_for_real_lan_go": raw.get(
            "external_lan_probe_required_for_real_lan_go", ""
        ),
        "agency_install_status": raw.get("agency_install_status", ""),
        "reason_code": raw.get("reason_code", ""),
        "boundary_result": raw.get("boundary_result", ""),
        "hub_base_url": raw.get("hub_base_url", ""),
        "web_api_health_status": raw.get("web_api_health_status", ""),
        "web_api_lan_bind_status": raw.get("web_api_lan_bind_status", ""),
        "infra_exposure_status": raw.get("infra_exposure_status", ""),
        "exposed_infra_services": raw.get("exposed_infra_services", []),
        "firewall_status": raw.get("firewall_status", ""),
        "approved_lan_facing_service": raw.get("approved_lan_facing_service", ""),
        "approved_lan_facing_port": raw.get("approved_lan_facing_port", ""),
        "infra_ports_policy": raw.get("infra_ports_policy", ""),
        "unsafe_publishers": raw.get("unsafe_publishers", []),
    }
    return {"exists": True, "path": str(path), **_sanitize_mapping(allowed)}


def _read_hub_identity_summary() -> dict[str, object]:
    path = config_path("hub_identity.json")
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"exists": True, "path": str(path), "read_error": exc.__class__.__name__}
    if not isinstance(raw, dict):
        return {"exists": True, "path": str(path), "read_error": "invalid_shape"}
    allowed = {
        "kind": raw.get("kind", ""),
        "schema_version": raw.get("schema_version", ""),
        "hub_display_name": raw.get("hub_display_name", ""),
        "created_at_utc": raw.get("created_at_utc", ""),
        "updated_at_utc": raw.get("updated_at_utc", ""),
        "machine_hostname_readonly": raw.get("machine_hostname_readonly", ""),
        "source": raw.get("source", ""),
    }
    return {"exists": True, "path": str(path), **_sanitize_mapping(allowed)}


def _read_hub_state_manifest_summary() -> dict[str, object]:
    path = config_path("hub_state_manifest.json")
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"exists": True, "path": str(path), "read_error": exc.__class__.__name__}
    if not isinstance(raw, dict):
        return {"exists": True, "path": str(path), "read_error": "invalid_shape"}
    allowed = {
        "kind": raw.get("kind", ""),
        "schema_version": raw.get("schema_version", ""),
        "hub_id": raw.get("hub_id", ""),
        "hub_display_name": raw.get("hub_display_name", ""),
        "friendly_name": raw.get("friendly_name", ""),
        "config_root": raw.get("config_root", ""),
        "data_root": raw.get("data_root", ""),
        "runtime_root": raw.get("runtime_root", ""),
        "logs_root": raw.get("logs_root", ""),
        "install_lineage": raw.get("install_lineage", ""),
        "runtime_provider_mode": raw.get("runtime_provider_mode", ""),
        "created_at_utc": raw.get("created_at_utc", ""),
        "updated_at_utc": raw.get("updated_at_utc", ""),
        "machine_hostname_readonly": raw.get("machine_hostname_readonly", ""),
    }
    return {"exists": True, "path": str(path), **_sanitize_mapping(allowed)}


def _read_hub_owner_authorization_summary() -> dict[str, object]:
    path = logs_dir() / "hub_owner_authorization.json"
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"exists": True, "path": str(path), "read_error": exc.__class__.__name__}
    if not isinstance(raw, dict):
        return {"exists": True, "path": str(path), "read_error": "invalid_shape"}
    allowed = {
        "kind": raw.get("kind", ""),
        "schema_version": raw.get("schema_version", ""),
        "created_at_utc": raw.get("created_at_utc", ""),
        "expires_at_utc": raw.get("expires_at_utc", ""),
        "proof_result": raw.get("proof_result", ""),
        "approval_status": raw.get("owner_authorization_status", ""),
        "reason_code": raw.get("reason_code", ""),
        "action": raw.get("action", ""),
        "authorization_scope": raw.get("authorization_scope", ""),
        "source": raw.get("source", ""),
        "actor_role": raw.get("actor_role", ""),
        "actor_is_owner": raw.get("actor_is_owner", ""),
        "actor_can_hard_delete": raw.get("actor_can_hard_delete", ""),
        "actor_is_superuser": raw.get("actor_is_superuser", ""),
        "authorized_role": raw.get("authorized_role", ""),
        "hub_id": raw.get("hub_id", ""),
        "hub_state_install_lineage": raw.get("hub_state_install_lineage", ""),
        "password_hash_present": raw.get("password_hash_present", ""),
        "password_hash_algorithm": raw.get("password_hash_algorithm", ""),
        "plaintext_password_written": raw.get("plaintext_password_written", ""),
    }
    return {"exists": True, "path": str(path), **_sanitize_mapping(allowed)}


def _read_hub_delete_approval_summary() -> dict[str, object]:
    return _read_hub_owner_authorization_summary()


def _read_hub_discovery_summary() -> dict[str, object]:
    path = logs_dir() / "hub_discovery_evidence.json"
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"exists": True, "path": str(path), "read_error": exc.__class__.__name__}
    if not isinstance(raw, dict):
        return {"exists": True, "path": str(path), "read_error": "invalid_shape"}
    allowed = {
        "kind": raw.get("kind", ""),
        "schema_version": raw.get("schema_version", ""),
        "created_at_utc": raw.get("created_at_utc", ""),
        "proof_result": raw.get("proof_result", ""),
        "reason_code": raw.get("reason_code", ""),
        "proof_scope": raw.get("proof_scope", ""),
        "advertised_display_name": raw.get("advertised_display_name", ""),
        "advertised_front_door_url": raw.get("advertised_front_door_url", ""),
        "secrets_advertised": raw.get("secrets_advertised", ""),
        "internal_ports_advertised": raw.get("internal_ports_advertised", ""),
    }
    return {"exists": True, "path": str(path), **_sanitize_mapping(allowed)}


def create_support_bundle(
    *,
    output_dir: str | os.PathLike[str] | None = None,
    health_timeout_seconds: float = 3.0,
) -> Path:
    """Create a zip bundle with logs and sanitized runtime metadata."""

    target_dir = Path(output_dir) if output_dir is not None else tmp_dir() / "support_bundles"
    target_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = target_dir / f"immoapp_support_{_utc_stamp()}.zip"
    config = get_api_config()
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "backend_url": config.base_url or "",
        "configured_username": config.username or "",
        "remember_session": bool(config.remember_session),
        "build_identity": get_build_identity(),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "pid": os.getpid(),
        },
        "client_config": _read_sanitized_client_config(),
        "hub_runtime_profile": _read_hub_runtime_profile_summary(),
        "hub_runtime_detection": _read_hub_runtime_detection_summary(),
        "managed_wsl2_runtime_candidate_install": _read_runtime_candidate_evidence_summary(
            "managed_wsl2_runtime_candidate_install.json"
        ),
        "managed_wsl2_runtime_candidate_remove": _read_runtime_candidate_evidence_summary(
            "managed_wsl2_runtime_candidate_remove.json"
        ),
        "managed_runtime_package_inventory": _read_managed_runtime_package_inventory_summary(),
        "managed_wsl2_runtime_artifact_inventory": (
            _read_managed_wsl2_runtime_artifact_inventory_summary()
        ),
        "managed_wsl2_runtime_image_bundle_inventory": (
            _read_managed_wsl2_runtime_image_bundle_inventory_summary()
        ),
        "managed_wsl2_runtime_bootstrap_evidence": _read_runtime_candidate_evidence_summary(
            "managed_wsl2_runtime_bootstrap_evidence.json"
        ),
        "managed_wsl2_runtime_start_evidence": _read_runtime_candidate_evidence_summary(
            "managed_wsl2_runtime_start_evidence.json"
        ),
        "managed_wsl2_runtime_status_evidence": _read_runtime_candidate_evidence_summary(
            "managed_wsl2_runtime_status_evidence.json"
        ),
        "managed_runtime_log_retention": _read_managed_runtime_log_retention_summary(),
        "hub_identity": _read_hub_identity_summary(),
        "hub_state_manifest": _read_hub_state_manifest_summary(),
        "hub_owner_authorization_evidence": _read_hub_owner_authorization_summary(),
        "hub_delete_approval_evidence": _read_hub_delete_approval_summary(),
        "hub_install_evidence": _read_hub_install_evidence_summary(),
        "hub_status_evidence": _read_hub_status_evidence_summary(),
        "hub_network_boundary_evidence": _read_hub_network_boundary_summary(),
        "hub_discovery_evidence": _read_hub_discovery_summary(),
        "backend_health": _health_probe(config.base_url, health_timeout_seconds),
    }
    manifest = _sanitize_mapping(manifest)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=True))
        added_logs = _add_log_files(bundle)
        profile_path = hub_runtime_profile_path()
        if profile_path.exists():
            bundle.write(profile_path, "config/hub_runtime_profile.json")
        provider_config_path = config_path("hub_runtime_provider.json")
        if provider_config_path.exists():
            try:
                provider_payload = json.loads(provider_config_path.read_text(encoding="utf-8-sig"))
            except Exception:
                provider_payload = {"read_error": "invalid_hub_runtime_provider"}
            if isinstance(provider_payload, Mapping):
                provider_payload = _sanitize_mapping(provider_payload)
            bundle.writestr(
                "config/hub_runtime_provider.json",
                json.dumps(provider_payload, indent=2, ensure_ascii=True),
            )
        hub_identity_path = config_path("hub_identity.json")
        if hub_identity_path.exists():
            try:
                identity_payload = json.loads(hub_identity_path.read_text(encoding="utf-8-sig"))
            except Exception:
                identity_payload = {"read_error": "invalid_hub_identity"}
            if isinstance(identity_payload, Mapping):
                identity_payload = _sanitize_mapping(identity_payload)
            bundle.writestr(
                "config/hub_identity.json",
                json.dumps(identity_payload, indent=2, ensure_ascii=True),
            )
        hub_state_manifest_path = config_path("hub_state_manifest.json")
        if hub_state_manifest_path.exists():
            try:
                manifest_payload = json.loads(
                    hub_state_manifest_path.read_text(encoding="utf-8-sig")
                )
            except Exception:
                manifest_payload = {"read_error": "invalid_hub_state_manifest"}
            if isinstance(manifest_payload, Mapping):
                manifest_payload = _sanitize_mapping(manifest_payload)
            bundle.writestr(
                "config/hub_state_manifest.json",
                json.dumps(manifest_payload, indent=2, ensure_ascii=True),
            )
        bundle.writestr(
            "evidence/managed_runtime_package_inventory_summary.json",
            json.dumps(
                manifest["managed_runtime_package_inventory"],
                indent=2,
                ensure_ascii=True,
            ),
        )
        bundle.writestr(
            "evidence/managed_wsl2_runtime_artifact_inventory_summary.json",
            json.dumps(
                manifest["managed_wsl2_runtime_artifact_inventory"],
                indent=2,
                ensure_ascii=True,
            ),
        )
        bundle.writestr(
            "evidence/managed_wsl2_runtime_image_bundle_inventory_summary.json",
            json.dumps(
                manifest["managed_wsl2_runtime_image_bundle_inventory"],
                indent=2,
                ensure_ascii=True,
            ),
        )
        for evidence_name in (
            "hub_install_evidence.json",
            "hub_status_evidence.json",
            "hub_runtime_detection.json",
            "managed_wsl2_runtime_candidate_install.json",
            "managed_wsl2_runtime_candidate_remove.json",
            "managed_wsl2_runtime_artifact_install.json",
            "managed_wsl2_runtime_bootstrap_evidence.json",
            "managed_wsl2_runtime_start_evidence.json",
            "managed_wsl2_runtime_status_evidence.json",
            "managed_wsl2_runtime_health_evidence.json",
            "managed_wsl2_runtime_logs_evidence.json",
            "managed_runtime_log_retention.json",
            "hub_network_boundary_evidence.json",
            "hub_discovery_evidence.json",
        ):
            status_path = logs_dir() / evidence_name
            if not status_path.exists():
                continue
            try:
                status_payload = json.loads(status_path.read_text(encoding="utf-8-sig"))
            except Exception:
                status_payload = {"read_error": f"invalid_{status_path.stem}"}
            if isinstance(status_payload, Mapping):
                status_payload = _sanitize_mapping(status_payload)
            bundle.writestr(
                f"evidence/{evidence_name}",
                json.dumps(status_payload, indent=2, ensure_ascii=True),
            )
        bundle.writestr(
            "README.txt",
            "ImmoApp support bundle. Manifest values are sanitized; raw tokens, passwords, "
            "presigned URLs, and credentials are intentionally omitted.\n",
        )
    summary_path = target_dir / f"{bundle_path.stem}.json"
    _write_json(summary_path, {**manifest, "bundle_path": str(bundle_path), "logs": added_logs})
    return bundle_path


__all__ = ["create_support_bundle"]
