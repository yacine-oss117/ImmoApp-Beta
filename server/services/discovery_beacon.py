"""LAN discovery beacon broadcaster."""

from __future__ import annotations

import os
import socket
import time

_PORT = 41900
_INTERVAL_SECONDS = 5.0


def discovery_enabled() -> bool:
    return os.environ.get("IMMOAPP_DISCOVERY_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _server_ip() -> str:
    value = (os.environ.get("IMMOAPP_DISCOVERY_IP") or "").strip()
    if value:
        return value
    host = socket.gethostname()
    try:
        return socket.gethostbyname(host)
    except OSError:
        return "127.0.0.1"


def _server_port() -> int:
    raw = (os.environ.get("IMMOAPP_DISCOVERY_PORT") or os.environ.get("PORT") or "8000").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 8000
    return max(1, min(65535, value))


def _agency_name() -> str:
    env_value = (os.environ.get("IMMOAPP_DISCOVERY_AGENCY_NAME") or "").strip()
    if env_value:
        return env_value
    return "ImmoApp"


def beacon_payload() -> str:
    return f"IMMOAPP_BEACON|{_server_ip()}|{_server_port()}|{_agency_name()}|v1"


def run_beacon_loop(*, stop_after_seconds: float | None = None) -> None:
    if not discovery_enabled():
        return
    end_at = time.monotonic() + float(stop_after_seconds) if stop_after_seconds else None
    payload = beacon_payload().encode("utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while True:
            if end_at is not None and time.monotonic() >= end_at:
                return
            try:
                sock.sendto(payload, ("255.255.255.255", _PORT))
            except OSError:
                return
            time.sleep(_INTERVAL_SECONDS)
    finally:
        sock.close()


__all__ = ["beacon_payload", "discovery_enabled", "run_beacon_loop"]
