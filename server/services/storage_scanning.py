"""Virus scanning helpers for storage."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from .storage_config import get_storage_config
from .storage_errors import StorageError

logger = logging.getLogger(__name__)
_SCAN_BIN = os.environ.get("CLAMAV_BIN", "clamscan")


def scan_file(path: Path) -> None:
    config = get_storage_config()
    if not config.virus_scan:
        return
    if config.clamd_socket or config.clamd_host:
        scan_file_with_clamd(path)
        return
    try:
        result = subprocess.run(
            [_SCAN_BIN, "--no-summary", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        if config.virus_scan_required:
            raise StorageError("Virus scanner not available.") from exc
        logger.warning("Virus scanner missing; skipping scan.")
        return
    if result.returncode == 0:
        return
    if result.returncode == 1:
        raise StorageError("File failed virus scan.")
    if config.virus_scan_required:
        raise StorageError("Virus scan failed.")
    logger.warning("Virus scan error: %s", result.stderr or result.stdout)


def scan_bytes(content: bytes, filename: str | None) -> None:
    config = get_storage_config()
    if not config.virus_scan:
        return
    suffix = Path(filename or "").suffix
    temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = Path(temp.name)
    try:
        temp.write(content)
        temp.flush()
        temp.close()
        scan_file(temp_path)
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def scan_file_with_clamd(path: Path) -> None:
    import socket

    config = get_storage_config()
    cmd = f"SCAN {path}\n".encode()
    try:
        if config.clamd_socket:
            af_unix = getattr(socket, "AF_UNIX", None)
            if af_unix is None:
                raise OSError("AF_UNIX sockets are not available on this platform")
            sock = socket.socket(af_unix, socket.SOCK_STREAM)
            sock.settimeout(config.clamd_timeout)
            sock.connect(config.clamd_socket)
        else:
            host = config.clamd_host or "127.0.0.1"
            sock = socket.create_connection((host, config.clamd_port), config.clamd_timeout)
        with sock:
            sock.sendall(cmd)
            response = sock.recv(4096).decode("utf-8", errors="replace").strip()
    except OSError as exc:
        if config.virus_scan_required:
            raise StorageError("Virus scanner unavailable.") from exc
        logger.warning("ClamAV daemon unavailable; skipping scan.")
        return

    if response.endswith("OK"):
        return
    if response.endswith("FOUND"):
        raise StorageError("File failed virus scan.")
    if config.virus_scan_required:
        raise StorageError("Virus scan failed.")
    logger.warning("ClamAV scan error: %s", response)
