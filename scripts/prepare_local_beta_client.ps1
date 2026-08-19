param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$Username = "owner",
    [switch]$RememberSession,
    [switch]$AllowAdmin
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

if ($Username.Trim().ToLowerInvariant() -eq "admin" -and -not $AllowAdmin.IsPresent) {
    throw "Local beta product-flow validation must use owner/admin. Pass -AllowAdmin only for explicit superuser tests."
}

$clientPython = Get-ImmoAppVenvPython -Kind client
if (-not (Test-Path $clientPython)) {
    throw "Client venv python not found at $clientPython"
}

$repoRoot = (Get-ImmoAppRepoRoot).Path
$runtimePaths = Get-ImmoAppRuntimePaths
$oldPyPath = $env:PYTHONPATH
$oldAppDataRoot = $env:IMMOAPP_APPDATA_ROOT
$oldBaseUrl = $env:IMMOAPP_BETA_BASE_URL
$oldUsername = $env:IMMOAPP_BETA_USERNAME
$oldRemember = $env:IMMOAPP_BETA_REMEMBER_SESSION
$tmpPy = $null

try {
    $env:PYTHONPATH = $repoRoot
    $env:IMMOAPP_APPDATA_ROOT = $runtimePaths.AppDataRoot
    $env:IMMOAPP_BETA_BASE_URL = $BaseUrl
    $env:IMMOAPP_BETA_USERNAME = $Username
    $env:IMMOAPP_BETA_REMEMBER_SESSION = if ($RememberSession.IsPresent) { "1" } else { "0" }
    $tmpPy = Join-Path $env:TEMP ("immoapp_prepare_beta_client_" + [Guid]::NewGuid().ToString("N") + ".py")
    @'
import os

from app.services.api_client import (
    clear_persisted_session,
    clear_session_credentials,
    reset_api_session,
)
from app.services.api_config import clear_api_token, get_api_config, set_api_config

base_url = os.environ["IMMOAPP_BETA_BASE_URL"].strip()
username = os.environ["IMMOAPP_BETA_USERNAME"].strip()
remember_session = os.environ.get("IMMOAPP_BETA_REMEMBER_SESSION") == "1"

for candidate in {"admin", "owner", username}:
    clear_persisted_session(candidate)
clear_session_credentials()
reset_api_session()
clear_api_token()
set_api_config(base_url=base_url, username=username, remember_session=remember_session)

config = get_api_config()
if (config.username or "").strip().lower() == "admin":
    raise SystemExit("Refusing to leave local beta client configured as platform admin.")
if config.base_url != base_url.rstrip("/"):
    raise SystemExit(f"Unexpected configured base_url: {config.base_url!r}")
if (config.username or "") != username:
    raise SystemExit(f"Unexpected configured username: {config.username!r}")
if bool(config.remember_session) != remember_session:
    raise SystemExit("Unexpected remember_session state.")
print("Local beta client prepared.")
print(f"base_url={config.base_url}")
print(f"username={config.username}")
print(f"remember_session={int(config.remember_session)}")
'@ | Set-Content -Path $tmpPy -Encoding UTF8

    & $clientPython $tmpPy
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to prepare local beta client."
    }
}
finally {
    if ($null -ne $oldPyPath) { $env:PYTHONPATH = $oldPyPath } else { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    if ($null -ne $oldAppDataRoot) { $env:IMMOAPP_APPDATA_ROOT = $oldAppDataRoot } else { Remove-Item Env:IMMOAPP_APPDATA_ROOT -ErrorAction SilentlyContinue }
    if ($null -ne $oldBaseUrl) { $env:IMMOAPP_BETA_BASE_URL = $oldBaseUrl } else { Remove-Item Env:IMMOAPP_BETA_BASE_URL -ErrorAction SilentlyContinue }
    if ($null -ne $oldUsername) { $env:IMMOAPP_BETA_USERNAME = $oldUsername } else { Remove-Item Env:IMMOAPP_BETA_USERNAME -ErrorAction SilentlyContinue }
    if ($null -ne $oldRemember) { $env:IMMOAPP_BETA_REMEMBER_SESSION = $oldRemember } else { Remove-Item Env:IMMOAPP_BETA_REMEMBER_SESSION -ErrorAction SilentlyContinue }
    if ($tmpPy -and (Test-Path $tmpPy)) {
        Remove-Item -Path $tmpPy -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Configured local beta client for $Username at $BaseUrl" -ForegroundColor Green
