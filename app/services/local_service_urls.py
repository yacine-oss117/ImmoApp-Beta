"""Helpers for rewriting stack-internal service URLs for host-local clients."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from app.services.api_config import get_api_base_url

_LOCAL_HTTP_SERVICE_HOST_OVERRIDES = {
    # MinIO presigned URLs are generated inside the Docker network with host
    # "minio". The desktop app runs on the host, so it must connect through
    # loopback while preserving the signed Host header.
    "minio": "127.0.0.1",
}


def _is_local_host(host: str) -> bool:
    return host in {"localhost", "127.0.0.1"} or host.startswith("127.")


def _is_local_api_runtime() -> bool:
    base_url = str(get_api_base_url() or "").strip()
    if not base_url:
        return False
    host = urlsplit(base_url).hostname or ""
    return _is_local_host(host)


def rewrite_local_service_url(url: str) -> str:
    """Rewrite Docker-internal service hosts to localhost for host-local clients."""
    if not _is_local_api_runtime():
        return url
    parts = urlsplit(str(url or ""))
    host = parts.hostname or ""
    override = _LOCAL_HTTP_SERVICE_HOST_OVERRIDES.get(host)
    if not override:
        return url
    netloc = override
    if parts.port is not None:
        netloc = f"{override}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def rewrite_local_service_request(url: str) -> tuple[str, dict[str, str]]:
    """Rewrite a Docker-internal URL while preserving the original signed Host value."""
    original = str(url or "")
    rewritten = rewrite_local_service_url(original)
    if rewritten == original:
        return rewritten, {}
    original_netloc = urlsplit(original).netloc
    if not original_netloc:
        return rewritten, {}
    return rewritten, {"Host": original_netloc}


__all__ = ["rewrite_local_service_request", "rewrite_local_service_url"]
