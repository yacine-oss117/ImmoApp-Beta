"""Requests session helpers for the API client."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast
from urllib.parse import urlparse

from app.core_app.paths import get_app_data_dir
from app.services.api_config import get_api_base_url

if TYPE_CHECKING:
    from requests import RequestException, Session

logger = logging.getLogger(__name__)


class RequestsModule(Protocol):
    """Protocol for the subset of requests APIs we use."""

    Session: type[Session]
    RequestException: type[RequestException]


_logged_verify_path: str | None = None
_session_lock = threading.Lock()
_sessions_by_thread: dict[int, Session] = {}


def _is_local_https_api() -> bool:
    base_url = str(get_api_base_url() or "").strip()
    if not base_url:
        return False
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").strip().lower()
    return parsed.scheme == "https" and (host == "localhost" or host.startswith("127."))


def _local_ca_candidates() -> list[Path]:
    candidates: list[Path] = []
    roots = [get_app_data_dir()]
    program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData").strip()
    if program_data:
        roots.append(Path(program_data) / "ImmoApp")

    seen: set[str] = set()
    for root in roots:
        candidate = (
            root
            / "data"
            / "caddy"
            / "data"
            / "caddy"
            / "pki"
            / "authorities"
            / "local"
            / "root.crt"
        )
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def _resolve_session_verify() -> str | bool:
    for env_name in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
        configured = str(os.environ.get(env_name) or "").strip()
        if configured:
            return configured
    if not _is_local_https_api():
        return True
    for candidate in _local_ca_candidates():
        if candidate.exists():
            return str(candidate)
    return True


def _apply_tls_policy(session: Session) -> None:
    global _logged_verify_path
    verify = _resolve_session_verify()
    session.verify = verify
    if isinstance(verify, str):
        normalized = verify.strip()
        if normalized and normalized != _logged_verify_path:
            logger.info("Using local CA bundle for desktop API session: %s", verify)
            _logged_verify_path = normalized


def get_requests() -> RequestsModule:
    """Lazily import the requests library."""
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests is required for API client usage") from exc
    return cast(RequestsModule, requests)


def get_session() -> Session:
    """Get or create a requests session scoped to the current thread."""
    thread_id = threading.get_ident()
    with _session_lock:
        session = _sessions_by_thread.get(thread_id)
        if session is None:
            requests = get_requests()
            session = requests.Session()
            _sessions_by_thread[thread_id] = session
    _apply_tls_policy(session)
    return session


def close_session() -> None:
    """Close the current thread's session if it exists."""
    thread_id = threading.get_ident()
    with _session_lock:
        session = _sessions_by_thread.pop(thread_id, None)
    if session is None:
        return
    try:
        session.close()
    except Exception:
        pass


__all__ = ["RequestsModule", "get_requests", "get_session", "close_session"]
