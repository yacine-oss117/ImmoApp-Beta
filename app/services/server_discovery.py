"""LAN server discovery for first-launch setup."""

from __future__ import annotations

import json
import socket
import time
from typing import Any, cast
from urllib.parse import urlparse

from app.services.api_config import get_api_base_url, normalize_hub_front_door_url

_BEACON_PORT = 41900
_BEACON_PREFIX = "IMMOAPP_BEACON"
_DISCOVERY_KIND = "immoapp_hub_discovery"
_PUBLIC_JSON_FIELDS = {
    "kind",
    "schema_version",
    "hub_display_name",
    "front_door_url",
    "front_door_port",
    "protocol",
    "health_path",
    "app_version",
    "api_version",
    "machine_hostname_readonly",
}
_SECRET_KEY_PATTERNS = {
    "password",
    "passwd",
    "secret",
    "token",
    "apikey",
    "accesskey",
    "secretkey",
    "clientsecret",
    "privatekey",
    "credential",
    "authorization",
    "cookie",
    "session",
    "xamz",
    "signature",
    "databaseurl",
    "dburl",
    "miniosecret",
}


def _parse_beacon(message: str) -> dict[str, object] | None:
    parts = [part.strip() for part in message.split("|")]
    if len(parts) != 5:
        return None
    if parts[0] != _BEACON_PREFIX:
        return None
    ip = parts[1]
    try:
        port = int(parts[2])
    except ValueError:
        return None
    agency = parts[3]
    version = parts[4]
    if not ip or port <= 0 or port > 65535:
        return None
    return {
        "ip": ip,
        "port": port,
        "agency": agency,
        "version": version,
        "source": "legacy_internal",
        "proof_scope": "internal_only",
        "connectable": False,
    }


def _normalize_discovery_key(key: object) -> str:
    return str(key or "").replace("_", "").replace("-", "").strip().lower()


def _looks_like_secret_key(key: object) -> bool:
    normalized = _normalize_discovery_key(key)
    return any(pattern in normalized for pattern in _SECRET_KEY_PATTERNS)


def _url_contains_credentials(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.username or parsed.password)


def _contains_unsafe_discovery_value(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            _looks_like_secret_key(key) or _contains_unsafe_discovery_value(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_unsafe_discovery_value(item) for item in value)
    if isinstance(value, str):
        return _url_contains_credentials(value)
    return False


def _contains_unsafe_discovery_payload(payload: dict[str, object]) -> bool:
    for key, value in payload.items():
        if str(key) not in _PUBLIC_JSON_FIELDS:
            return True
        if _looks_like_secret_key(key):
            return True
        if _contains_unsafe_discovery_value(value):
            return True
    return False


def _parse_json_beacon(message: str) -> dict[str, object] | None:
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        schema_version = int(str(payload.get("schema_version") or "0"))
    except (TypeError, ValueError):
        return None
    if payload.get("kind") != _DISCOVERY_KIND or schema_version != 1:
        return None
    if _contains_unsafe_discovery_payload(payload):
        return None
    display_name = str(payload.get("hub_display_name") or "").strip()
    front_door_url = str(payload.get("front_door_url") or "").strip()
    if not display_name or not front_door_url:
        return None
    try:
        normalized = normalize_hub_front_door_url(front_door_url)
    except ValueError:
        return None
    try:
        port = int(payload.get("front_door_port") or 8000)
    except (TypeError, ValueError):
        return None
    if port <= 0 or port > 65535:
        return None
    return {
        "hub_display_name": display_name,
        "front_door_url": normalized,
        "port": port,
        "protocol": str(payload.get("protocol") or "http"),
        "health_path": str(payload.get("health_path") or "/api/v1/health/"),
        "app_version": str(payload.get("app_version") or ""),
        "api_version": str(payload.get("api_version") or ""),
        "machine_hostname_readonly": str(payload.get("machine_hostname_readonly") or ""),
        "online_status": "Online",
        "source": "hub_discovery_v1",
        "proof_scope": "front_door_discovery",
        "connectable": True,
    }


def discover_servers(timeout_seconds: float = 3.0) -> list[dict[str, Any]]:
    """Discover broadcasted servers on local network."""
    if get_api_base_url():
        return []
    timeout = max(0.5, min(float(timeout_seconds), 10.0))
    deadline = time.monotonic() + timeout
    found: dict[tuple[str, int], dict[str, Any]] = {}

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", _BEACON_PORT))
        sock.settimeout(0.2)
        while time.monotonic() < deadline:
            try:
                payload, _addr = sock.recvfrom(2048)
            except TimeoutError:
                continue
            except OSError:
                break
            try:
                text = payload.decode("utf-8", errors="ignore")
            except Exception:
                continue
            parsed = _parse_json_beacon(text) or _parse_beacon(text)
            if not parsed:
                continue
            key_url = str(parsed.get("front_door_url") or "")
            key = (key_url or str(parsed.get("ip") or ""), int(cast(int, parsed["port"])))
            found[key] = parsed
    finally:
        sock.close()
    return list(found.values())


__all__ = ["discover_servers"]
