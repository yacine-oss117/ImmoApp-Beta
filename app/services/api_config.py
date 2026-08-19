"""API configuration management for the desktop client."""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

from app.core_app.paths import config_path

logger = logging.getLogger(__name__)

_CONFIG_FILE = "client_api.json"
_HUB_INTERNAL_PORTS = {
    18000,  # backend direct dev/internal host port
    2019,  # Caddy admin API
    3310,  # ClamAV
    5432,  # Postgres
    5672,  # RabbitMQ
    6379,  # Valkey
    8200,  # OpenBao
    9000,  # MinIO API
    9001,  # MinIO console
    15672,  # RabbitMQ management
}


@dataclass(frozen=True)
class ApiConfig:
    """Immutable API configuration loaded from environment or config file."""

    base_url: str | None
    username: str | None
    password: str | None
    token: str | None
    schema: str | None
    remember_session: bool


def _is_local_address(host: str) -> bool:
    return host in {"localhost", "127.0.0.1"} or host.startswith("127.")


def _is_private_lan_host(host: str) -> bool:
    if not host:
        return False
    lowered = host.strip().lower()
    if lowered.endswith(".local") or "." not in lowered:
        return True
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return bool(address.is_private or address.is_link_local)


def _normalize_url(value: str | None, *, allow_private_http: bool = False) -> str | None:
    """Normalize a URL, defaulting to HTTP for local hosts and HTTPS elsewhere."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None

    parsed = urlparse(text)
    # urlparse("localhost:8000") treats "localhost" as a scheme, so detect
    # explicit HTTP(S) prefixes directly instead of relying on parsed.scheme.
    if not text.startswith(("http://", "https://")):
        provisional = urlparse(f"http://{text}")
        host = provisional.hostname or text.split("/", 1)[0]
        scheme = (
            "http"
            if (_is_local_address(host) or (allow_private_http and _is_private_lan_host(host)))
            else "https"
        )
        text = f"{scheme}://{text}"
        parsed = urlparse(text)

    has_scheme = bool(re.match(r"^https?://", text, re.IGNORECASE))
    if not has_scheme:
        # Assume host[:port] and default to https (http for localhost).
        host = text.split("/", 1)[0]
        scheme = (
            "http"
            if (_is_local_address(host) or (allow_private_http and _is_private_lan_host(host)))
            else "https"
        )
        text = f"{scheme}://{text}"

    parsed = urlparse(text)
    host = parsed.hostname or ""
    if parsed.scheme == "http" and not (
        _is_local_address(host) or (allow_private_http and _is_private_lan_host(host))
    ):
        # Force https for non-local hosts.
        text = text.replace("http://", "https://", 1)

    return text.rstrip("/")


def normalize_api_base_url(value: str | None) -> str | None:
    """Public normalizer for API base URLs."""
    return _normalize_url(value)


def normalize_hub_front_door_url(value: str | None, *, allow_local_hub: bool = False) -> str | None:
    """Normalize a Hub front-door URL while allowing private-LAN HTTP."""
    normalized = _normalize_url(value, allow_private_http=True)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    host = (parsed.hostname or "").strip().lower()
    if _is_local_address(host) and not allow_local_hub:
        raise ValueError("Workstation mode requires an office Hub front-door URL, not localhost.")
    if parsed.port in _HUB_INTERNAL_PORTS:
        raise ValueError("Workstation mode cannot use an internal Hub service port.")
    return normalized


def probe_hub_front_door(
    base_url: str,
    *,
    require_caddy_header: bool = True,
    timeout_seconds: float = 4.0,
) -> dict[str, object]:
    """Validate that a URL reaches the Hub front door and safe identity endpoints."""
    normalized = normalize_hub_front_door_url(base_url, allow_local_hub=True)
    if not normalized:
        raise ValueError("Please type a valid Hub address.")
    from app.services.api_client_requests import get_session

    session = get_session()
    health = session.get(f"{normalized.rstrip('/')}/api/v1/health/", timeout=timeout_seconds)
    health.raise_for_status()
    if int(health.status_code) != 200:
        raise ValueError("The Hub health check did not return OK.")
    identity = session.get(
        f"{normalized.rstrip('/')}/api/v1/hub/front-door/identity/",
        timeout=timeout_seconds,
    )
    identity.raise_for_status()
    if require_caddy_header and identity.headers.get("X-ImmoApp-Front-Door", "").lower() != "caddy":
        raise ValueError("The address did not respond through the ImmoApp Hub front door.")
    payload = identity.json()
    if not isinstance(payload, dict) or payload.get("kind") != "immoapp_hub_front_door_identity":
        raise ValueError("The Hub identity response was not recognized.")
    return {
        "base_url": normalized,
        "health_status": int(health.status_code),
        "identity": payload,
    }


def verify_hub_front_door_url(
    url: str,
    *,
    allow_local_hub: bool = False,
    timeout_seconds: float = 4.0,
) -> dict[str, object]:
    """Verify a workstation Hub URL through the Caddy/front-door proof path."""
    normalized = normalize_hub_front_door_url(url, allow_local_hub=allow_local_hub)
    if not normalized:
        raise ValueError("Please type a valid Hub address.")
    proof = probe_hub_front_door(
        normalized,
        require_caddy_header=True,
        timeout_seconds=timeout_seconds,
    )
    identity = proof.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("The Hub identity response was not recognized.")
    try:
        schema_version = int(str(identity.get("schema_version") or "0"))
    except ValueError as exc:
        raise ValueError("The Hub identity response was not recognized.") from exc
    if identity.get("kind") != "immoapp_hub_front_door_identity" or schema_version != 1:
        raise ValueError("The Hub identity response was not recognized.")
    display_name = str(
        identity.get("hub_display_name")
        or identity.get("display_name")
        or identity.get("hub_name")
        or "Office Hub"
    ).strip()
    health_status = int(str(proof.get("health_status") or "0"))
    return {
        "normalized_url": normalized,
        "hub_display_name": display_name,
        "identity_kind": str(identity.get("kind") or ""),
        "identity_schema_version": schema_version,
        "api_version": str(identity.get("api_version") or ""),
        "proof_timestamp_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "identity": identity,
        "health_status": health_status,
    }


def _read_config_file() -> dict[str, str]:
    """Read the API config from disk, returning empty dict on error."""
    path = config_path(_CONFIG_FILE)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Invalid API config file: %s", path, exc_info=True)
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v is not None}


def _write_config_file(data: dict[str, str]) -> None:
    """Persist API config data to disk."""
    path = config_path(_CONFIG_FILE)
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to write API config file: %s", path, exc_info=True)
        raise RuntimeError("Failed to write API config file") from exc


def get_api_config() -> ApiConfig:
    """Load the complete API configuration from environment and config file."""
    file_data = _read_config_file()
    env_base_url = os.environ.get("IMMOAPP_API_BASE_URL")
    file_base_url = file_data.get("base_url")
    connection_source = str(file_data.get("connection_source") or "")
    if env_base_url:
        base_url = normalize_api_base_url(env_base_url)
    elif file_base_url and connection_source in {"manual", "discovery", "local_hub"}:
        base_url = normalize_hub_front_door_url(
            file_base_url,
            allow_local_hub=connection_source == "local_hub",
        )
    else:
        base_url = _normalize_url(file_base_url)
    username = os.environ.get("IMMOAPP_API_USERNAME") or file_data.get("username")
    # Never persist secrets to disk; only allow explicit env overrides.
    password = os.environ.get("IMMOAPP_API_PASSWORD")
    token = os.environ.get("IMMOAPP_API_TOKEN")
    schema = os.environ.get("IMMOAPP_API_SCHEMA") or file_data.get("schema")
    remember_raw = file_data.get("remember_session", "")
    remember_session = str(remember_raw).strip().lower() in {"1", "true", "yes"}
    return ApiConfig(
        base_url=base_url,
        username=username,
        password=password,
        token=token,
        schema=schema.strip().lower() if isinstance(schema, str) and schema.strip() else None,
        remember_session=remember_session,
    )


def set_api_config(
    *,
    base_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    token: str | None = None,
    schema: str | None = None,
    remember_session: bool | None = None,
    hub_display_name: str | None = None,
    connection_source: str | None = None,
) -> None:
    """Persist API configuration to disk."""
    data = _read_config_file()
    if base_url is not None:
        normalized = _normalize_url(base_url)
        if normalized:
            data["base_url"] = normalized
        else:
            data.pop("base_url", None)
    if username is not None:
        if username:
            data["username"] = username
        else:
            data.pop("username", None)
    if password is not None:
        data.pop("password", None)
    if token is not None:
        data.pop("token", None)
    if schema is not None:
        normalized = schema.strip().lower() if isinstance(schema, str) else ""
        if normalized:
            data["schema"] = normalized
        else:
            data.pop("schema", None)
    if remember_session is not None:
        if remember_session:
            data["remember_session"] = "1"
        else:
            data.pop("remember_session", None)
    if hub_display_name is not None:
        if hub_display_name:
            data["hub_display_name"] = hub_display_name
        else:
            data.pop("hub_display_name", None)
    if connection_source is not None:
        if connection_source:
            data["connection_source"] = connection_source
        else:
            data.pop("connection_source", None)
    _write_config_file(data)


def set_verified_api_config(
    *,
    base_url: str,
    allow_local_hub: bool = False,
    connection_source: str = "manual",
    username: str | None = None,
    schema: str | None = None,
    remember_session: bool | None = None,
    timeout_seconds: float = 4.0,
) -> dict[str, object]:
    """Verify and persist a Hub front-door endpoint for workstation setup."""
    if connection_source == "local_dev_unverified":
        raise ValueError("Unverified dev endpoint sources cannot use the verified Hub save path.")
    verified = verify_hub_front_door_url(
        base_url,
        allow_local_hub=allow_local_hub,
        timeout_seconds=timeout_seconds,
    )
    data = _read_config_file()
    data["base_url"] = str(verified["normalized_url"])
    data["hub_display_name"] = str(verified["hub_display_name"])
    data["connection_source"] = "local_hub" if allow_local_hub else connection_source
    if username is not None:
        if username:
            data["username"] = username
        else:
            data.pop("username", None)
    if schema is not None:
        normalized_schema = schema.strip().lower() if isinstance(schema, str) else ""
        if normalized_schema:
            data["schema"] = normalized_schema
        else:
            data.pop("schema", None)
    if remember_session is not None:
        if remember_session:
            data["remember_session"] = "1"
        else:
            data.pop("remember_session", None)
    _write_config_file(data)
    return verified


def clear_api_token() -> None:
    """Remove any stored API token."""
    data = _read_config_file()
    data.pop("token", None)
    _write_config_file(data)


def get_api_base_url() -> str | None:
    """Get the configured API base URL, or None if not configured."""
    return get_api_config().base_url


def get_api_schema() -> str | None:
    """Return the active API schema override (if any)."""
    return get_api_config().schema


def set_api_schema(schema: str | None) -> None:
    """Persist the API schema override to disk."""
    data = _read_config_file()
    normalized = schema.strip().lower() if isinstance(schema, str) else ""
    if normalized:
        data["schema"] = normalized
    else:
        data.pop("schema", None)
    _write_config_file(data)
