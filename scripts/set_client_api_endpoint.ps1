param(
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,
    [Parameter(Mandatory = $false)]
    [string]$Username = "",
    [Parameter(Mandatory = $false)]
    [string]$Schema = "",
    [Parameter(Mandatory = $false)]
    [switch]$RememberSession,
    [Parameter(Mandatory = $false)]
    [switch]$AllowLocalHub,
    [Parameter(Mandatory = $false)]
    [string]$HubDisplayName = "",
    [Parameter(Mandatory = $false)]
    [string]$ConnectionSource = "manual",
    [Parameter(Mandatory = $false)]
    [switch]$DevBypassFrontDoorVerification
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

function Normalize-ClientEndpointUrl {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [switch]$AllowLocalHubForEndpoint
    )
    $text = $Url.Trim()
    if ([string]::IsNullOrWhiteSpace($text)) {
        throw "BaseUrl is required."
    }
    if ($text -notmatch "^(?i)https?://") {
        $text = "http://$text"
    }
    try {
        $uri = [Uri]$text
    }
    catch {
        throw "BaseUrl must be a valid HTTP(S) URL."
    }
    if ($uri.Scheme -notin @("http", "https")) {
        throw "BaseUrl must use HTTP or HTTPS."
    }
    $hostName = $uri.Host.Trim().ToLowerInvariant()
    $isLocalHost = ($hostName -eq "localhost" -or $hostName -eq "127.0.0.1" -or $hostName.StartsWith("127."))
    if ($isLocalHost -and -not $AllowLocalHubForEndpoint.IsPresent) {
        throw "Workstation mode requires an office Hub front-door URL, not localhost."
    }
    if ([int]$uri.Port -in @(18000, 2019, 3310, 5432, 5672, 6379, 8200, 9000, 9001, 15672)) {
        throw "Client endpoint cannot use an internal Hub service port."
    }
    return $uri.AbsoluteUri.TrimEnd("/")
}

function Get-ClientConfigPath {
    $appDataRoot = $env:IMMOAPP_APPDATA_ROOT
    if ([string]::IsNullOrWhiteSpace($appDataRoot)) {
        $base = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } elseif ($env:APPDATA) { $env:APPDATA } else { $env:PROGRAMDATA }
        $appDataRoot = Join-Path $base "ImmoApp"
    }
    return (Join-Path (Join-Path $appDataRoot "config") "client_api.json")
}

function Read-ClientConfigPayload {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{}
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $Path) {
        throw "Client API config path contains a reparse point, symlink, or junction: $Path"
    }
    try {
        $payload = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "Existing client API config is not valid JSON: $Path"
    }
    $result = [ordered]@{}
    foreach ($property in $payload.PSObject.Properties) {
        if ($null -ne $property.Value) {
            $result[$property.Name] = [string]$property.Value
        }
    }
    return $result
}

function Write-ClientConfigPayload {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Payload
    )
    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    if (Test-ImmoAppPathHasReparsePoint -Path $directory) {
        throw "Client API config directory contains a reparse point, symlink, or junction: $directory"
    }
    $tmp = Join-Path $directory ("client_api." + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $json = $Payload | ConvertTo-Json -Depth 8
        [System.IO.File]::WriteAllText($tmp, $json, (New-Object System.Text.UTF8Encoding($false)))
        $null = Get-Content -LiteralPath $tmp -Raw -Encoding UTF8 | ConvertFrom-Json
        Move-Item -LiteralPath $tmp -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $tmp -PathType Leaf) {
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        }
    }
}

function Set-ClientApiEndpointWithPowerShell {
    $normalized = Normalize-ClientEndpointUrl -Url $BaseUrl -AllowLocalHubForEndpoint:$AllowLocalHub
    $hubDisplayName = $HubDisplayName
    if (-not $DevBypassFrontDoorVerification.IsPresent) {
        try {
            $health = Invoke-WebRequest -Method Get -Uri ($normalized + "/api/v1/health/") -TimeoutSec 8 -UseBasicParsing
            if ([int]$health.StatusCode -ne 200) {
                throw "health_status_not_200"
            }
            $identity = Invoke-WebRequest -Method Get -Uri ($normalized + "/api/v1/hub/front-door/identity/") -TimeoutSec 8 -UseBasicParsing
            $frontDoorHeader = [string]$identity.Headers["X-ImmoApp-Front-Door"]
            $identityPayload = $identity.Content | ConvertFrom-Json
            if ([int]$identity.StatusCode -ne 200 -or $frontDoorHeader.ToLowerInvariant() -ne "caddy") {
                throw "front_door_marker_missing"
            }
            if ([string]$identityPayload.kind -ne "immoapp_hub_front_door_identity" -or [int]$identityPayload.schema_version -ne 1) {
                throw "front_door_identity_invalid"
            }
            if ([string]::IsNullOrWhiteSpace($hubDisplayName)) {
                $hubDisplayName = [string]$identityPayload.hub_display_name
                if ([string]::IsNullOrWhiteSpace($hubDisplayName)) { $hubDisplayName = [string]$identityPayload.display_name }
                if ([string]::IsNullOrWhiteSpace($hubDisplayName)) { $hubDisplayName = [string]$identityPayload.hub_name }
            }
        }
        catch {
            throw "Hub front-door verification failed: $($_.Exception.Message)"
        }
    }

    $configPath = Get-ClientConfigPath
    $data = Read-ClientConfigPayload -Path $configPath
    $data["base_url"] = $normalized
    if ($Username) { $data["username"] = $Username } else { $data.Remove("username") }
    if ($Schema) { $data["schema"] = $Schema.Trim().ToLowerInvariant() } else { $data.Remove("schema") }
    if ($RememberSession.IsPresent) { $data["remember_session"] = "1" } else { $data.Remove("remember_session") }
    if ($hubDisplayName) { $data["hub_display_name"] = $hubDisplayName }
    $data["connection_source"] = if ($DevBypassFrontDoorVerification.IsPresent) { "local_dev_unverified" } elseif ($AllowLocalHub.IsPresent) { "local_hub" } else { $ConnectionSource }
    $data.Remove("password")
    $data.Remove("token")
    Write-ClientConfigPayload -Path $configPath -Payload $data
    if ($DevBypassFrontDoorVerification.IsPresent) {
        Write-Warning "Configured unverified local/dev endpoint. connection_source=local_dev_unverified cannot satisfy agency or LAN workstation GO."
    }
    else {
        Write-Host "Client API endpoint verified through Hub front door and updated."
    }
}

$clientPython = Get-ImmoAppVenvPython -Kind client
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonApiConfigModule = Join-Path $repoRoot "app\services\api_config.py"
if (-not (Test-Path $clientPython) -or -not (Test-Path -LiteralPath $pythonApiConfigModule -PathType Leaf)) {
    Set-ClientApiEndpointWithPowerShell
    Write-Host "Configured client base URL: $BaseUrl" -ForegroundColor Green
    if ($Username) {
        Write-Host "Configured username: $Username" -ForegroundColor Green
    }
    if ($Schema) {
        Write-Host "Configured schema: $Schema" -ForegroundColor Green
    }
    return
}

$rememberFlag = if ($RememberSession.IsPresent) { "True" } else { "False" }
$allowLocalHubFlag = if ($AllowLocalHub.IsPresent) { "True" } else { "False" }
$devBypassFlag = if ($DevBypassFrontDoorVerification.IsPresent) { "True" } else { "False" }

$py = @"
from app.services.api_config import normalize_api_base_url, set_api_config, set_verified_api_config

base_url = r'''$BaseUrl'''
username = r'''$Username'''
schema = r'''$Schema'''
hub_display_name = r'''$HubDisplayName'''
connection_source = r'''$ConnectionSource'''
dev_bypass = $devBypassFlag

if dev_bypass:
    normalized = normalize_api_base_url(base_url)
    if not normalized:
        raise RuntimeError("BaseUrl is required for dev/proof-only endpoint bypass.")
    set_api_config(
        base_url=normalized,
        username=username,
        schema=schema,
        remember_session=$rememberFlag,
        hub_display_name=hub_display_name,
        connection_source="local_dev_unverified",
    )
    print("WARNING: dev/proof-only endpoint configured without Hub front-door verification.")
else:
    set_verified_api_config(
        base_url=base_url,
        allow_local_hub=$allowLocalHubFlag,
        connection_source=connection_source,
        username=username,
        schema=schema,
        remember_session=$rememberFlag,
    )
    print("Client API endpoint verified through Hub front door and updated.")
"@

try {
    $oldPyPath = $env:PYTHONPATH
    $env:PYTHONPATH = $repoRoot
    $tmpPy = Join-Path $env:TEMP ("immoapp_set_api_" + [Guid]::NewGuid().ToString("N") + ".py")
    Set-Content -Path $tmpPy -Value $py -Encoding UTF8
    & $clientPython $tmpPy
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to update client API endpoint."
    }
}
finally {
    if ($null -ne $oldPyPath) {
        $env:PYTHONPATH = $oldPyPath
    }
    else {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
    if ($tmpPy -and (Test-Path $tmpPy)) {
        Remove-Item -Path $tmpPy -Force -ErrorAction SilentlyContinue
    }
}

if ($DevBypassFrontDoorVerification.IsPresent) {
    Write-Warning "Configured unverified local/dev endpoint. connection_source=local_dev_unverified cannot satisfy agency or LAN workstation GO."
}
Write-Host "Configured client base URL: $BaseUrl" -ForegroundColor Green
if ($Username) {
    Write-Host "Configured username: $Username" -ForegroundColor Green
}
if ($Schema) {
    Write-Host "Configured schema: $Schema" -ForegroundColor Green
}
