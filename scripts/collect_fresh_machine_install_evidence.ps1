param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [Parameter(Mandatory = $true)][string]$InstallerSha256,
    [Parameter(Mandatory = $true)][string]$SourceCommitSha,
    [Parameter(Mandatory = $true)][string]$BackendUrl,
    [Parameter(Mandatory = $true)][string]$OutputJson,
    [string]$InstalledInventoryJson = "",
    [string]$InstalledExePath = "",
    [string]$InstallLifecycleEvidenceJson = "",
    [string]$SupportBundlePath = "",
    [string]$ManualProofNotes = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Join-UrlPath {
    param([string]$BaseUrl, [string]$Path)
    return $BaseUrl.TrimEnd("/") + "/" + $Path.TrimStart("/")
}

function Test-LocalhostUrl {
    param([string]$Url)
    if ([string]::IsNullOrWhiteSpace($Url)) { return $false }
    try { $uri = [Uri]$Url } catch { return $false }
    return $uri.Host.Trim().ToLowerInvariant() -in @("localhost", "127.0.0.1", "::1")
}

function Get-JsonPropertyValue {
    param(
        [Parameter(Mandatory = $true)]$Data,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $property = $Data.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

if (-not (Test-Path -LiteralPath $InstallerPath)) {
    throw "Installer path does not exist: $InstallerPath"
}
$actualInstallerSha = Get-FileSha256 -Path $InstallerPath
if ($actualInstallerSha -ne $InstallerSha256.ToLowerInvariant()) {
    throw "Installer SHA-256 mismatch. expected=$InstallerSha256 actual=$actualInstallerSha"
}
if ([string]::IsNullOrWhiteSpace($SupportBundlePath) -or -not (Test-Path -LiteralPath $SupportBundlePath)) {
    throw "Fresh-machine evidence requires an existing support bundle path for local evidence."
}

$inventory = $null
$installedInventoryStatus = "missing"
if ($InstalledInventoryJson) {
    if (-not (Test-Path -LiteralPath $InstalledInventoryJson)) { throw "Installed inventory JSON not found: $InstalledInventoryJson" }
    $inventory = Get-Content -LiteralPath $InstalledInventoryJson -Raw | ConvertFrom-Json
    if ([string]$inventory.kind -ne "immoapp_installed_app_inventory") { throw "Installed inventory evidence has wrong kind." }
    if ([int]$inventory.schema_version -lt 1) { throw "Installed inventory evidence schema_version must be positive." }
    $inventorySourceCommit = Get-JsonPropertyValue -Data $inventory -Name "source_commit_sha"
    $inventoryExpectedCommit = Get-JsonPropertyValue -Data $inventory -Name "expected_source_commit_sha"
    if ($inventorySourceCommit -and [string]$inventorySourceCommit -ne $SourceCommitSha) { throw "Installed inventory evidence source commit mismatch." }
    if ($inventoryExpectedCommit -and [string]$inventoryExpectedCommit -ne $SourceCommitSha) { throw "Installed inventory expected source commit mismatch." }
    if (@($inventory.forbidden_path_matches).Count -gt 0) { throw "Installed inventory contains forbidden path matches." }
    if ((Get-JsonPropertyValue -Data $inventory -Name "debug_missing_build_identity_allowed") -eq $true) { throw "Fresh-machine evidence cannot use debug installed inventory without build identity." }
    if (-not (Get-JsonPropertyValue -Data $inventory -Name "build_identity") -and -not (Get-JsonPropertyValue -Data $inventory -Name "installer_build_identity")) { throw "Installed inventory lacks required build identity." }
    $installedInventoryStatus = "verified"
}
$lifecycle = $null
if ($InstallLifecycleEvidenceJson) {
    if (-not (Test-Path -LiteralPath $InstallLifecycleEvidenceJson)) { throw "Install lifecycle evidence JSON not found: $InstallLifecycleEvidenceJson" }
    $lifecycle = Get-Content -LiteralPath $InstallLifecycleEvidenceJson -Raw | ConvertFrom-Json
    if ([string]$lifecycle.kind -ne "immoapp_install_lifecycle_evidence") { throw "Install lifecycle evidence has wrong kind." }
    if ([int]$lifecycle.schema_version -notin @(2, 3)) { throw "Install lifecycle evidence schema_version must be 2 or 3." }
    if ([int]$lifecycle.schema_version -eq 3) {
        if ([string]$lifecycle.desktop_installer_release_proof_status -ne "GO") { throw "Install lifecycle evidence must have desktop_installer_release_proof_status=GO." }
    }
    elseif ([string]$lifecycle.lifecycle_status -ne "GO") { throw "Install lifecycle evidence must have lifecycle_status=GO." }
    if ([string]$lifecycle.source_commit_sha -ne $SourceCommitSha) { throw "Install lifecycle source commit mismatch." }
    if (([string]$lifecycle.installer_sha256).ToLowerInvariant() -ne $InstallerSha256.ToLowerInvariant()) { throw "Install lifecycle installer SHA mismatch." }
}

$installedExePath = if ($inventory -and $inventory.installed_exe_path) {
    [string]$inventory.installed_exe_path
}
elseif ($InstalledExePath) {
    $installedInventoryStatus = "missing_explicit_exe_only"
    $InstalledExePath
}
else {
    throw "Fresh-machine evidence requires -InstalledInventoryJson or explicit -InstalledExePath; install path guessing is not allowed."
}
if (-not (Test-Path -LiteralPath $installedExePath)) {
    throw "Installed app executable not found: $installedExePath"
}

$backendHealthStatus = $null
try {
    $health = Invoke-WebRequest -Method Get -Uri (Join-UrlPath -BaseUrl $BackendUrl -Path "/api/v1/health/") -TimeoutSec 8 -UseBasicParsing
    $backendHealthStatus = [int]$health.StatusCode
}
catch {
    throw "Backend health check failed for fresh-machine evidence: $($_.Exception.Message)"
}
if ($backendHealthStatus -ne 200) {
    throw "Backend health status was $backendHealthStatus, expected 200."
}

$shortcutCandidates = @(
    (Join-Path $env:USERPROFILE "Desktop\ImmoApp Beta.lnk"),
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\ImmoApp Beta.lnk")
)
$shortcutPath = @($shortcutCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1)
$identity = $null
foreach ($candidate in @(
        (Join-Path (Split-Path -Parent $installedExePath) "_internal\app\build_identity.json"),
        (Join-Path (Split-Path -Parent $installedExePath) "app\build_identity.json")
    )) {
    if (Test-Path -LiteralPath $candidate) {
        $identity = Get-Content -LiteralPath $candidate -Raw | ConvertFrom-Json
        break
    }
}
if ($identity -and [string]$identity.git_sha -ne $SourceCommitSha) {
    throw "Installed app build identity source commit does not match expected source commit."
}

$programDataRoot = "C:\ProgramData\ImmoApp"
$logCandidates = @(
    (Join-Path $env:LOCALAPPDATA "ImmoApp\logs\app.log"),
    (Join-Path $programDataRoot "logs\app.log")
)
$appLogPath = @($logCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1)

$evidence = [ordered]@{
    kind = "immoapp_fresh_machine_install_evidence"
    schema_version = 2
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    windows_user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    installer_path = (Resolve-Path -LiteralPath $InstallerPath).Path
    installer_sha256 = $actualInstallerSha
    source_commit_sha = $SourceCommitSha
    installed_shortcut_path = if ($shortcutPath.Count -gt 0) { $shortcutPath[0] } else { "" }
    installed_app_launch_path = (Resolve-Path -LiteralPath $installedExePath).Path
    desktop_backend_url = $BackendUrl
    backend_url_is_localhost = Test-LocalhostUrl -Url $BackendUrl
    support_bundle_path = (Resolve-Path -LiteralPath $SupportBundlePath).Path
    support_bundle_sha256 = Get-FileSha256 -Path $SupportBundlePath
    installed_exe_sha256 = Get-FileSha256 -Path $installedExePath
    installed_exe_build_identity = $identity
    backend_health_status = $backendHealthStatus
    os_version = [System.Environment]::OSVersion.VersionString
    programdata_immoapp_path_exists = (Test-Path -LiteralPath $programDataRoot)
    app_log_path = if ($appLogPath.Count -gt 0) { $appLogPath[0] } else { "" }
    app_log_path_exists = ($appLogPath.Count -gt 0)
    installed_inventory_path = $InstalledInventoryJson
    installed_inventory_sha256 = if ($InstalledInventoryJson) { Get-FileSha256 -Path $InstalledInventoryJson } else { "" }
    installed_inventory_status = $installedInventoryStatus
    install_lifecycle_evidence_path = $InstallLifecycleEvidenceJson
    install_lifecycle_evidence_sha256 = if ($InstallLifecycleEvidenceJson) { Get-FileSha256 -Path $InstallLifecycleEvidenceJson } else { "" }
    install_lifecycle_status = if ($lifecycle) { [string]$lifecycle.lifecycle_status } else { "missing" }
    desktop_installer_release_proof_status = if ($lifecycle -and $lifecycle.PSObject.Properties.Name -contains "desktop_installer_release_proof_status") { [string]$lifecycle.desktop_installer_release_proof_status } else { "" }
    manual_proof_notes = $ManualProofNotes
    limitation = if (Test-LocalhostUrl -Url $BackendUrl) { "localhost backend URL is Hub/local-machine proof only, not workstation proof" } else { $null }
    mutation_routes_used = $false
}

if ([string]::IsNullOrWhiteSpace([string]$evidence.installed_shortcut_path)) {
    throw "Installed shortcut path was not found for fresh-machine evidence."
}

$outputDir = Split-Path -Parent $OutputJson
if ($outputDir -and -not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}
$evidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputJson -Encoding UTF8
Write-Host "Fresh-machine install evidence JSON: $OutputJson"
Write-Host "Fresh-machine backend_health_status=$backendHealthStatus"
Write-Host "Fresh-machine mutation_routes_used=false"
