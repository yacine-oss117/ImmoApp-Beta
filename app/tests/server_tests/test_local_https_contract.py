from __future__ import annotations

from pathlib import Path


def test_hub_caddy_front_door_proxies_to_backend_without_admin_api() -> None:
    text = Path("deployment/proxy/Caddyfile").read_text(encoding="utf-8")
    assert "admin off" in text
    assert ":8000" in text
    assert 'X-ImmoApp-Front-Door "caddy"' in text
    assert "reverse_proxy {$IMMOAPP_UPSTREAM:web:8000}" in text
    assert "tls internal" not in text


def test_local_caddy_trust_helper_targets_current_user_root_store() -> None:
    text = Path("scripts/trust_local_caddy_ca.ps1").read_text(encoding="utf-8")
    assert "Cert:\\CurrentUser\\Root" in text
    assert "Import-Certificate" in text
    assert "root.crt" in text


def test_run_client_supports_explicit_base_url_override() -> None:
    text = Path("scripts/run_client.ps1").read_text(encoding="utf-8")
    assert '[string]$BaseUrl = ""' in text
    assert "$env:IMMOAPP_API_BASE_URL = $BaseUrl.Trim()" in text
