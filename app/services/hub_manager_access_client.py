"""Minimal no-persistence client for Hub Manager owner access."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

_TIMEOUT_SECONDS = 12.0


@dataclass(frozen=True)
class HubManagerAccessClientError(Exception):
    reason_code: str

    def __str__(self) -> str:
        return self.reason_code


def fetch_owner_state(base_url: str) -> dict[str, Any]:
    response = _request("GET", _url(base_url, "/api/v1/hub-manager/owner-state/"))
    payload = _json_object(response)
    if response.status_code != 200:
        raise HubManagerAccessClientError(
            str(payload.get("reason_code") or "owner_state_unavailable")
        )
    return payload


def request_owner_authorization(
    *,
    base_url: str,
    username: str,
    password: str,
    action: str,
    hub_binding: dict[str, str],
) -> dict[str, Any]:
    token_response = _request(
        "POST",
        _url(base_url, "/api/auth/token/"),
        json={"username": username, "password": password},
    )
    token_payload = _json_object(token_response)
    if token_response.status_code == 429:
        raise HubManagerAccessClientError("hub_owner_authorization_temporarily_locked")
    if token_response.status_code != 200:
        raise HubManagerAccessClientError("hub_owner_authorization_password_invalid")
    access_token = str(token_payload.get("access") or "")
    if not access_token:
        raise HubManagerAccessClientError("hub_owner_authorization_token_missing")

    issue_response = _request(
        "POST",
        _url(base_url, "/api/v1/hub-manager/authorizations/"),
        json={"action": action, **hub_binding},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    access_token = ""
    token_payload.clear()
    issue_payload = _json_object(issue_response)
    if issue_response.status_code != 201:
        raise HubManagerAccessClientError(
            str(issue_payload.get("reason_code") or "hub_owner_authorization_failed")
        )
    return issue_payload


def _request(method: str, url: str, **kwargs: Any) -> requests.Response:
    try:
        return requests.request(method, url, timeout=_TIMEOUT_SECONDS, **kwargs)
    except requests.RequestException as exc:
        raise HubManagerAccessClientError("hub_owner_authorization_unreachable") from exc


def _json_object(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise HubManagerAccessClientError("hub_owner_authorization_invalid_response") from exc
    if not isinstance(payload, dict):
        raise HubManagerAccessClientError("hub_owner_authorization_invalid_response")
    return payload


def _url(base_url: str, path: str) -> str:
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HubManagerAccessClientError("hub_owner_authorization_base_url_invalid")
    if parsed.username or parsed.password:
        raise HubManagerAccessClientError("hub_owner_authorization_base_url_invalid")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


__all__ = [
    "HubManagerAccessClientError",
    "fetch_owner_state",
    "request_owner_authorization",
]
