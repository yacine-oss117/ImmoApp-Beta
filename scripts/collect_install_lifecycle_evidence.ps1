param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("post_install", "post_uninstall", "post_reinstall", "combined_manual")]
    [string]$Mode,
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [Parameter(Mandatory = $true)][string]$InstallerSha256,
    [Parameter(Mandatory = $true)][string]$SourceCommitSha,
    [string]$BackendUrl = "",
    [Parameter(Mandatory = $true)][string]$OutputJson,
    [string]$InstallLocation = "",
    [string]$InstallLogPath = "",
    [string]$InstalledInventoryJson = "",
    [string]$SupportBundlePath = "",
    [string]$PostInstallEvidenceJson = "",
    [string]$PostUninstallEvidenceJson = "",
    [string]$PostReinstallEvidenceJson = "",
    [string]$InstalledFrontDoorEvidenceJson = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-LocalhostUrl {
    param([string]$Url)
    if ([string]::IsNullOrWhiteSpace($Url)) { return $false }
    try { $uri = [Uri]$Url } catch { return $false }
    return $uri.Host.Trim().ToLowerInvariant() -in @("localhost", "127.0.0.1", "::1")
}

function Join-UrlPath {
    param([string]$BaseUrl, [string]$Path)
    return $BaseUrl.TrimEnd("/") + "/" + $Path.TrimStart("/")
}

function Get-ObjectPropertyString {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value) {
        return ""
    }
    return [string]$property.Value
}

function Find-ImmoAppUninstallEntry {
    param([string]$ResolvedInstallLocation = "")
    $roots = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    )
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        foreach ($key in Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue) {
            $props = Get-ItemProperty -LiteralPath $key.PSPath -ErrorAction SilentlyContinue
            if (-not $props) { continue }
            $displayName = Get-ObjectPropertyString -Object $props -Name "DisplayName"
            $installLocation = Get-ObjectPropertyString -Object $props -Name "InstallLocation"
            $sameLocation = $false
            if ($ResolvedInstallLocation -and $installLocation) {
                $sameLocation = [System.IO.Path]::GetFullPath($installLocation).TrimEnd("\", "/").Equals($ResolvedInstallLocation.TrimEnd("\", "/"), [System.StringComparison]::OrdinalIgnoreCase)
            }
            if ($displayName -eq "ImmoApp Beta" -or $displayName -eq "ImmoApp Beta version 1.0.0" -or $sameLocation) {
                return [ordered]@{
                    registry_path = $key.Name
                    display_name = $displayName
                    display_version = Get-ObjectPropertyString -Object $props -Name "DisplayVersion"
                    install_location = $installLocation
                    uninstall_string = Get-ObjectPropertyString -Object $props -Name "UninstallString"
                }
            }
        }
    }
    return $null
}

function Resolve-ObservedInstallLocation {
    param($UninstallEntry)
    if ($InstallLocation) {
        return [System.IO.Path]::GetFullPath($InstallLocation)
    }
    if ($UninstallEntry -and $UninstallEntry.install_location) {
        return [System.IO.Path]::GetFullPath([string]$UninstallEntry.install_location)
    }
    throw "InstallLocation is required when no uninstall registry entry is present."
}

function Get-ShortcutState {
    $desktopShortcut = Join-Path $env:USERPROFILE "Desktop\ImmoApp Beta.lnk"
    $startMenuShortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\ImmoApp Beta.lnk"
    return [ordered]@{
        desktop_shortcut_path = $desktopShortcut
        desktop_shortcut_present = (Test-Path -LiteralPath $desktopShortcut)
        start_menu_shortcut_path = $startMenuShortcut
        start_menu_shortcut_present = (Test-Path -LiteralPath $startMenuShortcut)
    }
}

function Get-BackendHealthStatus {
    if ([string]::IsNullOrWhiteSpace($BackendUrl)) { return $null }
    try {
        $health = Invoke-WebRequest -Method Get -Uri (Join-UrlPath -BaseUrl $BackendUrl -Path "/api/v1/health/") -TimeoutSec 8 -UseBasicParsing
        return [int]$health.StatusCode
    }
    catch {
        throw "Backend health check failed for install lifecycle evidence: $($_.Exception.Message)"
    }
}

function New-PhaseObservation {
    param([Parameter(Mandatory = $true)][string]$PhaseName)
    $registryBeforeLocation = if ($InstallLocation) { [System.IO.Path]::GetFullPath($InstallLocation) } else { "" }
    $uninstallEntry = Find-ImmoAppUninstallEntry -ResolvedInstallLocation $registryBeforeLocation
    $resolvedInstallLocation = Resolve-ObservedInstallLocation -UninstallEntry $uninstallEntry
    $installedExePath = Join-Path $resolvedInstallLocation "ImmoApp.exe"
    $installDirExists = Test-Path -LiteralPath $resolvedInstallLocation
    $installFiles = @()
    if ($installDirExists) {
        $installFiles = @(Get-ChildItem -LiteralPath $resolvedInstallLocation -Recurse -File -Force -ErrorAction SilentlyContinue)
    }
    $shortcuts = Get-ShortcutState
    $backendHealthStatus = Get-BackendHealthStatus
    if ($null -ne $backendHealthStatus -and $backendHealthStatus -ne 200) {
        throw "Backend health status was $backendHealthStatus, expected 200."
    }
    $phase = [ordered]@{
        observed_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        uninstall_registry_present = ($null -ne $uninstallEntry)
        uninstall_registry_entry = $uninstallEntry
        installed_exe_present = (Test-Path -LiteralPath $installedExePath)
        installed_exe_path = $installedExePath
        install_location = $resolvedInstallLocation
        install_directory_present = $installDirExists
        install_directory_file_count = $installFiles.Count
        install_directory_allowed_empty_residue = ($installDirExists -and $installFiles.Count -eq 0)
        desktop_shortcut_present = $shortcuts.desktop_shortcut_present
        desktop_shortcut_path = $shortcuts.desktop_shortcut_path
        start_menu_shortcut_present = $shortcuts.start_menu_shortcut_present
        start_menu_shortcut_path = $shortcuts.start_menu_shortcut_path
        backend_health_status = $backendHealthStatus
    }
    if ($PhaseName -eq "post_install") {
        if (-not $phase.uninstall_registry_present) { throw "post_install requires uninstall registry present." }
        if (-not $phase.installed_exe_present) { throw "post_install requires installed ImmoApp.exe present." }
    }
    elseif ($PhaseName -eq "post_reinstall") {
        if (-not $phase.uninstall_registry_present) { throw "post_reinstall requires uninstall registry present." }
        if (-not $phase.installed_exe_present) { throw "post_reinstall requires installed ImmoApp.exe present." }
    }
    elseif ($PhaseName -eq "post_uninstall") {
        if ($phase.uninstall_registry_present) { throw "post_uninstall requires uninstall registry absent." }
        if ($phase.installed_exe_present) { throw "post_uninstall requires installed ImmoApp.exe absent." }
        if ($phase.install_directory_present -and $phase.install_directory_file_count -gt 0) {
            throw "post_uninstall requires install directory absent or empty; found $($phase.install_directory_file_count) file(s)."
        }
    }
    return $phase
}

function Import-LifecyclePhase {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$PhaseName
    )
    if (-not (Test-Path -LiteralPath $Path)) { throw "Lifecycle phase evidence not found: $Path" }
    $data = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ([string]$data.kind -ne "immoapp_install_lifecycle_evidence") { throw "Lifecycle phase evidence has wrong kind: $Path" }
    if ([int]$data.schema_version -notin @(2, 3)) { throw "Lifecycle phase evidence schema_version must be 2 or 3: $Path" }
    if (-not ($data.phases.PSObject.Properties.Name -contains $PhaseName)) {
        throw "Lifecycle phase evidence missing $PhaseName phase: $Path"
    }
    if ([string]$data.source_commit_sha -ne $SourceCommitSha) { throw "Lifecycle phase evidence source_commit_sha mismatch: $Path" }
    if (([string]$data.installer_sha256).ToLowerInvariant() -ne $InstallerSha256.ToLowerInvariant()) {
        throw "Lifecycle phase evidence installer_sha256 mismatch: $Path"
    }
    return [ordered]@{
        path = (Resolve-Path -LiteralPath $Path).Path
        sha256 = Get-FileSha256 -Path $Path
        phase = $data.phases.PSObject.Properties[$PhaseName].Value
    }
}

function Import-InstalledFrontDoorEvidence {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return [ordered]@{
            status = "NOT_PROVEN"
            path = ""
            sha256 = ""
            reason = "installed_app_front_door_evidence_not_supplied"
            data = $null
        }
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Installed front-door evidence JSON does not exist: $Path"
    }
    $data = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ([string]$data.kind -ne "immoapp_installed_desktop_front_door_evidence") {
        throw "Installed front-door evidence has wrong kind: $Path"
    }
    if ([int]$data.schema_version -ne 1) {
        throw "Installed front-door evidence schema_version must be 1: $Path"
    }
    if ([string]$data.source_commit_sha -ne $SourceCommitSha) {
        throw "Installed front-door evidence source_commit_sha mismatch: $Path"
    }
    if (([string]$data.installer_sha256).ToLowerInvariant() -ne $InstallerSha256.ToLowerInvariant()) {
        throw "Installed front-door evidence installer_sha256 mismatch: $Path"
    }
    $proof = [string]$data.proof_result
    $reason = if ($proof -eq "GO") { "" } else { "installed_app_front_door_evidence_not_go" }
    return [ordered]@{
        status = if ($proof -eq "GO") { "GO" } else { "NO-GO" }
        path = (Resolve-Path -LiteralPath $Path).Path
        sha256 = Get-FileSha256 -Path $Path
        reason = $reason
        data = $data
    }
}

if (-not (Test-Path -LiteralPath $InstallerPath)) {
    throw "Installer path not found: $InstallerPath"
}
$actualInstallerSha = Get-FileSha256 -Path $InstallerPath
if ($actualInstallerSha -ne $InstallerSha256.ToLowerInvariant()) {
    throw "Installer SHA-256 mismatch. expected=$InstallerSha256 actual=$actualInstallerSha"
}
if ($InstallLogPath -and -not (Test-Path -LiteralPath $InstallLogPath)) { throw "Install log path does not exist: $InstallLogPath" }
if ($InstalledInventoryJson -and -not (Test-Path -LiteralPath $InstalledInventoryJson)) { throw "Installed inventory JSON does not exist: $InstalledInventoryJson" }
if ($SupportBundlePath -and -not (Test-Path -LiteralPath $SupportBundlePath)) { throw "Support bundle path does not exist: $SupportBundlePath" }
if ($InstalledFrontDoorEvidenceJson -and -not (Test-Path -LiteralPath $InstalledFrontDoorEvidenceJson)) { throw "Installed front-door evidence JSON does not exist: $InstalledFrontDoorEvidenceJson" }

$phaseMap = [ordered]@{}
$phaseEvidenceFiles = [ordered]@{}
$installMechanicsStatus = "PHASE_ONLY"
$uninstallStatus = "NOT_RUN"
$reinstallStatus = "NOT_RUN"
$installedAppFrontDoorConnectivityStatus = "NOT_PROVEN"
$desktopInstallerReleaseProofStatus = "NO-GO"
$lifecycleStatus = "NO-GO"
$installedFrontDoorEvidence = [ordered]@{
    status = "NOT_PROVEN"
    path = ""
    sha256 = ""
    reason = "installed_app_front_door_evidence_not_supplied"
    data = $null
}
if ($Mode -eq "combined_manual") {
    $postInstall = Import-LifecyclePhase -Path $PostInstallEvidenceJson -PhaseName "post_install"
    $postUninstall = Import-LifecyclePhase -Path $PostUninstallEvidenceJson -PhaseName "post_uninstall"
    $postReinstall = Import-LifecyclePhase -Path $PostReinstallEvidenceJson -PhaseName "post_reinstall"
    $phaseMap.post_install = $postInstall.phase
    $phaseMap.post_uninstall = $postUninstall.phase
    $phaseMap.post_reinstall = $postReinstall.phase
    $phaseEvidenceFiles.post_install = [ordered]@{ path = $postInstall.path; sha256 = $postInstall.sha256 }
    $phaseEvidenceFiles.post_uninstall = [ordered]@{ path = $postUninstall.path; sha256 = $postUninstall.sha256 }
    $phaseEvidenceFiles.post_reinstall = [ordered]@{ path = $postReinstall.path; sha256 = $postReinstall.sha256 }
    $installMechanicsStatus = "GO"
    $uninstallStatus = "GO"
    $reinstallStatus = "GO"
    $installedFrontDoorEvidence = Import-InstalledFrontDoorEvidence -Path $InstalledFrontDoorEvidenceJson
    $installedAppFrontDoorConnectivityStatus = [string]$installedFrontDoorEvidence.status
    if ($installedAppFrontDoorConnectivityStatus -eq "GO") {
        $desktopInstallerReleaseProofStatus = "GO"
        $lifecycleStatus = "GO"
    }
}
else {
    $phaseMap[$Mode] = New-PhaseObservation -PhaseName $Mode
    if ($Mode -eq "post_install") { $installMechanicsStatus = "GO" }
    if ($Mode -eq "post_uninstall") { $uninstallStatus = "GO" }
    if ($Mode -eq "post_reinstall") { $reinstallStatus = "GO" }
}

$evidence = [ordered]@{
    kind = "immoapp_install_lifecycle_evidence"
    schema_version = 3
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    mode = $Mode
    machine_name = $env:COMPUTERNAME
    windows_user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    installer_path = (Resolve-Path -LiteralPath $InstallerPath).Path
    installer_sha256 = $actualInstallerSha
    source_commit_sha = $SourceCommitSha
    backend_url = $BackendUrl
    backend_url_is_localhost = Test-LocalhostUrl -Url $BackendUrl
    install_log_path = $InstallLogPath
    installed_inventory_path = $InstalledInventoryJson
    installed_inventory_sha256 = if ($InstalledInventoryJson) { Get-FileSha256 -Path $InstalledInventoryJson } else { "" }
    support_bundle_path = $SupportBundlePath
    support_bundle_sha256 = if ($SupportBundlePath) { Get-FileSha256 -Path $SupportBundlePath } else { "" }
    installed_front_door_evidence_path = [string]$installedFrontDoorEvidence.path
    installed_front_door_evidence_sha256 = [string]$installedFrontDoorEvidence.sha256
    install_mechanics_status = $installMechanicsStatus
    uninstall_status = $uninstallStatus
    reinstall_status = $reinstallStatus
    installed_app_front_door_connectivity_status = $installedAppFrontDoorConnectivityStatus
    desktop_installer_release_proof_status = $desktopInstallerReleaseProofStatus
    desktop_installer_release_proof_reason = if ($desktopInstallerReleaseProofStatus -eq "GO") { "" } else { [string]$installedFrontDoorEvidence.reason }
    phases = $phaseMap
    phase_evidence_files = $phaseEvidenceFiles
    lifecycle_status = $lifecycleStatus
    limitation = if (Test-LocalhostUrl -Url $BackendUrl) { "localhost backend URL is Hub/local-machine proof only, not workstation proof" } else { $null }
    mutation_routes_used = $false
}

$outputDir = Split-Path -Parent $OutputJson
if ($outputDir -and -not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}
$evidence | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $OutputJson -Encoding UTF8
Write-Host "Install lifecycle evidence JSON: $OutputJson"
Write-Host "Install lifecycle mode=$Mode"
Write-Host "Install lifecycle status=$lifecycleStatus"
Write-Host "Install mechanics status=$installMechanicsStatus"
Write-Host "Installed app front-door connectivity status=$installedAppFrontDoorConnectivityStatus"
Write-Host "Desktop installer release proof status=$desktopInstallerReleaseProofStatus"
Write-Host "Install lifecycle mutation_routes_used=false"
