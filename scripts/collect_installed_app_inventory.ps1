param(
    [Parameter(Mandatory = $true)][string]$InstallLocation,
    [Parameter(Mandatory = $true)][string]$OutputJson,
    [string]$InstallerPath = "",
    [string]$ExpectedInstallerSha256 = "",
    [string]$ExpectedSourceCommitSha = "",
    [string]$BuildSummaryJson = "",
    [switch]$AllowMissingBuildIdentityForDebug
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-RelativePathSafe {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd("\", "/")
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    if (-not $pathFull.StartsWith($rootFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Installed inventory path escaped install root: $pathFull"
    }
    return $pathFull.Substring($rootFull.Length + 1).Replace("\", "/")
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

function Get-InstallerHubPayloadFiles {
    return @(
        "scripts/common.ps1",
        "scripts/setup_office_hub.ps1",
        "scripts/hub_manager.ps1",
        "scripts/set_hub_identity.ps1",
        "scripts/get_hub_identity.ps1",
        "scripts/detect_hub_runtime.ps1",
        "scripts/hub_runtime_profile.py",
        "scripts/collect_hub_status_evidence.ps1",
        "scripts/collect_hub_install_evidence.ps1",
        "scripts/collect_managed_wsl2_runtime_start_evidence.ps1",
        "scripts/collect_desktop_support_bundle.ps1",
        "scripts/managed_wsl2_runtime_policy.ps1",
        "scripts/configure_managed_wsl2_runtime.ps1",
        "scripts/register_managed_hub_runtime_provider.ps1",
        "scripts/uninstall_managed_hub_runtime_provider.ps1",
        "scripts/bootstrap_managed_wsl2_runtime.ps1",
        "scripts/import_managed_wsl2_runtime_distro.ps1",
        "core/__init__.py",
        "core/env_files.py",
        "core/env_flags.py",
        "core/paths.py",
        "core/runtime/__init__.py",
        "core/runtime/hub_runtime_profile.py",
        "scripts/set_client_api_endpoint.ps1",
        "scripts/verify_lan_workstation_reachability.ps1",
        "scripts/verify_hub_network_boundary.ps1",
        "deployment/env/.env.example",
        "core/models_audit.py",
        "deployment/managed-runtime/rootfs/ImmoAppRuntime.rootfs.tar",
        "deployment/managed-runtime/config/managed_wsl2_runtime_rootfs_inventory.json",
        "deployment/managed-runtime/images/immoapp-runtime-images.tar",
        "deployment/managed-runtime/config/managed_wsl2_runtime_image_bundle_inventory.json",
        "deployment/managed-runtime/config/managed_wsl2_runtime_artifact_inventory.json"
    )
}

function Test-InstallerHubPayloadPathAllowed {
    param([Parameter(Mandatory = $true)][string]$RelativePath)
    $normalized = $RelativePath.Replace("\", "/").Trim("/").ToLowerInvariant()
    if ($normalized -like "core/*") {
        return $true
    }
    if ($normalized -like "deployment/managed-runtime/artifact/managed-wsl2-artifact/*") {
        return $true
    }
    return (@(Get-InstallerHubPayloadFiles) | ForEach-Object { $_.ToLowerInvariant() }) -contains $normalized
}

function Get-ForbiddenInstalledPathMatches {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$FileName
    )
    $lower = $RelativePath.Replace("\", "/").Trim("/").ToLowerInvariant()
    $name = $FileName.ToLowerInvariant()
    if (Test-InstallerHubPayloadPathAllowed -RelativePath $lower) {
        return @()
    }
    $segments = @($lower.Split("/", [System.StringSplitOptions]::RemoveEmptyEntries))
    $violations = New-Object System.Collections.Generic.List[string]
    foreach ($segment in @(".git", ".tmp", "tests", "scripts", "server", "deployment", "docs", "__pycache__", ".pytest_cache", ".hypothesis")) {
        if ($segments -contains $segment) { $violations.Add("forbidden segment '$segment'") }
    }
    if ($lower -like "app/tests/*" -or $lower -eq "app/tests") { $violations.Add("app/tests") }
    if ($name -in @(".env", ".env.local", ".env.production", "immoapp-dev-secrets.json", "openbao.token", "openbao.unseal")) {
        $violations.Add("local env or secret file")
    }
    if ($name -match "(secret|password|token|credential|private_key)") { $violations.Add("secret-like filename") }
    if ($name -match "\.(sqlite|sqlite3|db|dump|bak)$") { $violations.Add("database or dump file") }
    if ($name -match "\.(zip|7z|tar|gz)$" -and ($lower -match "(backup|release|bundle|artifact)")) {
        $violations.Add("backup or release archive")
    }
    if ($lower -match "(^|/)(docker-compose|compose)\.ya?ml$" -or $name -eq "dockerfile") {
        $violations.Add("Docker/backend deployment file")
    }
    foreach ($token in @("release_backup", "release_artifacts", "minio", "postgres", "pgdata")) {
        if ($lower.Contains($token)) { $violations.Add("local artifact/data token '$token'") }
    }
    return @($violations.ToArray())
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
    param([Parameter(Mandatory = $true)][string]$ResolvedInstallLocation)
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
            if ($installLocation) {
                $sameLocation = [System.IO.Path]::GetFullPath($installLocation).TrimEnd("\", "/").Equals($ResolvedInstallLocation.TrimEnd("\", "/"), [System.StringComparison]::OrdinalIgnoreCase)
            }
            if ($displayName -eq "ImmoApp Beta" -or $displayName -eq "ImmoApp Beta version 1.0.0" -or $sameLocation) {
                return [ordered]@{
                    registry_path = $key.Name
                    display_name = $displayName
                    display_version = Get-ObjectPropertyString -Object $props -Name "DisplayVersion"
                    publisher = Get-ObjectPropertyString -Object $props -Name "Publisher"
                    install_location = $installLocation
                    uninstall_string = Get-ObjectPropertyString -Object $props -Name "UninstallString"
                }
            }
        }
    }
    return $null
}

if (-not (Test-Path -LiteralPath $InstallLocation)) {
    throw "Install location does not exist: $InstallLocation"
}
$resolvedInstall = (Resolve-Path -LiteralPath $InstallLocation).Path
$exePath = Join-Path $resolvedInstall "ImmoApp.exe"
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "Installed ImmoApp.exe not found at: $exePath"
}
$uninstaller = @(Get-ChildItem -LiteralPath $resolvedInstall -Filter "unins*.exe" -File -ErrorAction SilentlyContinue | Select-Object -First 1)
if ($uninstaller.Count -lt 1) {
    throw "Inno uninstaller executable was not found under install location: $resolvedInstall"
}
$uninstallEntry = Find-ImmoAppUninstallEntry -ResolvedInstallLocation $resolvedInstall
if (-not $uninstallEntry) {
    throw "Windows uninstall registry entry for ImmoApp Beta was not found."
}

$files = New-Object System.Collections.Generic.List[object]
$forbidden = New-Object System.Collections.Generic.List[object]
$totalBytes = [int64]0
foreach ($file in Get-ChildItem -LiteralPath $resolvedInstall -Recurse -File -Force | Sort-Object FullName) {
    $relative = Get-RelativePathSafe -Root $resolvedInstall -Path $file.FullName
    $totalBytes += [int64]$file.Length
    $files.Add([ordered]@{
            path = $relative
            bytes = [int64]$file.Length
            sha256 = Get-FileSha256 -Path $file.FullName
        })
    foreach ($match in @(Get-ForbiddenInstalledPathMatches -RelativePath $relative -FileName $file.Name)) {
        $forbidden.Add([ordered]@{ path = $relative; reason = $match })
    }
}
if ($forbidden.Count -gt 0) {
    $details = @($forbidden | ForEach-Object { "$($_.path) [$($_.reason)]" })
    throw "Installed app inventory found forbidden source/backend/test/artifact paths: $($details -join '; ')"
}

$identity = $null
foreach ($candidate in @(
        (Join-Path $resolvedInstall "_internal\app\build_identity.json"),
        (Join-Path $resolvedInstall "app\build_identity.json")
    )) {
    if (Test-Path -LiteralPath $candidate) {
        $identity = Get-Content -LiteralPath $candidate -Raw | ConvertFrom-Json
        break
    }
}
$installerBuildIdentity = $null
foreach ($candidate in @(
        (Join-Path $resolvedInstall "_internal\app\installer_build_identity.json"),
        (Join-Path $resolvedInstall "app\installer_build_identity.json")
    )) {
    if (Test-Path -LiteralPath $candidate) {
        $installerBuildIdentity = Get-Content -LiteralPath $candidate -Raw | ConvertFrom-Json
        break
    }
}
if (-not $identity -and -not $installerBuildIdentity -and -not $AllowMissingBuildIdentityForDebug.IsPresent) {
    throw "Installed app build identity is required. Use -AllowMissingBuildIdentityForDebug only for non-release troubleshooting."
}
if ($ExpectedSourceCommitSha) {
    $identityMatches = ($identity -and [string]$identity.git_sha -eq $ExpectedSourceCommitSha)
    $installerIdentityMatches = ($installerBuildIdentity -and [string]$installerBuildIdentity.source_commit_sha -eq $ExpectedSourceCommitSha)
    if (-not ($identityMatches -or $installerIdentityMatches)) {
        throw "Installed build identity does not match expected source commit SHA."
    }
}

$buildSummary = $null
if ($BuildSummaryJson) {
    if (-not (Test-Path -LiteralPath $BuildSummaryJson)) { throw "Build summary JSON does not exist: $BuildSummaryJson" }
    $buildSummary = Get-Content -LiteralPath $BuildSummaryJson -Raw | ConvertFrom-Json
    if ([string]$buildSummary.kind -ne "immoapp_desktop_installer_build_summary") { throw "Build summary JSON has wrong kind." }
    if ($installerBuildIdentity -and [string]$buildSummary.source_commit_sha -ne [string]$installerBuildIdentity.source_commit_sha) {
        throw "Installed installer_build_identity source commit does not match build summary."
    }
    if ($installerBuildIdentity -and [string]$buildSummary.version -ne [string]$installerBuildIdentity.installer_version) {
        throw "Installed installer_build_identity version does not match build summary."
    }
    $expectedIdentityInventoryHash = Get-JsonPropertyValue -Data $buildSummary -Name "installer_identity_bundle_inventory_sha256"
    if ($installerBuildIdentity -and $expectedIdentityInventoryHash -and [string]$expectedIdentityInventoryHash -ne [string]$installerBuildIdentity.bundle_inventory_sha256) {
        throw "Installed installer_build_identity bundle inventory hash does not match build summary."
    }
}

$topLevelEntries = @(Get-ChildItem -LiteralPath $resolvedInstall -Force | Sort-Object Name | ForEach-Object { $_.Name })
$buildSummarySha256 = ""
if ($BuildSummaryJson) {
    $buildSummarySha256 = Get-FileSha256 -Path $BuildSummaryJson
}
$buildIdentityRequired = (-not $AllowMissingBuildIdentityForDebug.IsPresent)
$debugMissingBuildIdentityAllowed = $AllowMissingBuildIdentityForDebug.IsPresent
$installedSourceCommitSha = ""
if ($installerBuildIdentity) {
    $installedSourceCommitSha = [string]$installerBuildIdentity.source_commit_sha
}
elseif ($identity) {
    $installedSourceCommitSha = [string]$identity.git_sha
}
$installedExeSha256 = Get-FileSha256 -Path $exePath
$uninstallerPath = $uninstaller[0].FullName
$fileEntries = @($files.ToArray())
$forbiddenEntries = @($forbidden.ToArray())
$installerSha256 = ""
$installerSha256Verified = $false
$installerSha256ClaimedOnly = $false
$installerSha256Actual = ""
$resolvedInstallerPath = ""
if (-not [string]::IsNullOrWhiteSpace($InstallerPath)) {
    if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
        throw "InstallerPath does not exist: $InstallerPath"
    }
    $resolvedInstallerPath = (Resolve-Path -LiteralPath $InstallerPath).Path
    $installerSha256Actual = Get-FileSha256 -Path $resolvedInstallerPath
    if (-not [string]::IsNullOrWhiteSpace($ExpectedInstallerSha256) -and $installerSha256Actual -ne $ExpectedInstallerSha256.ToLowerInvariant()) {
        throw "InstallerPath SHA-256 does not match ExpectedInstallerSha256."
    }
    $installerSha256 = $installerSha256Actual
    $installerSha256Verified = $true
}
elseif (-not [string]::IsNullOrWhiteSpace($ExpectedInstallerSha256)) {
    $installerSha256 = $ExpectedInstallerSha256.ToLowerInvariant()
    $installerSha256ClaimedOnly = $true
}

$inventory = [ordered]@{
    kind = "immoapp_installed_app_inventory"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    proof_result = "GO"
    source_commit_sha = $installedSourceCommitSha
    installer_sha256 = $installerSha256
    machine_name = $env:COMPUTERNAME
    windows_user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    install_location = $resolvedInstall
    installed_exe_path = $exePath
    installed_exe_sha256 = $installedExeSha256
    uninstall_exe_path = $uninstallerPath
    uninstall_registry_entry = $uninstallEntry
    display_name = $uninstallEntry.display_name
    display_version = $uninstallEntry.display_version
    publisher = $uninstallEntry.publisher
    installer_sha256_claimed_by_operator = $ExpectedInstallerSha256
    installer_sha256_verified = $installerSha256Verified
    installer_sha256_claimed_only = $installerSha256ClaimedOnly
    installer_path = $resolvedInstallerPath
    installer_sha256_actual = $installerSha256Actual
    installer_sha256_verification = if ($installerSha256Verified) { "verified_from_installer_file" } elseif ($installerSha256ClaimedOnly) { "claimed_only_by_operator" } else { "missing" }
    expected_source_commit_sha = $ExpectedSourceCommitSha
    build_summary_path = $BuildSummaryJson
    build_summary_sha256 = $buildSummarySha256
    total_file_count = $files.Count
    total_byte_size = $totalBytes
    forbidden_path_count = $forbiddenEntries.Count
    top_level_entries = $topLevelEntries
    files = $fileEntries
    forbidden_path_matches = $forbiddenEntries
    build_identity = $identity
    installer_build_identity = $installerBuildIdentity
    build_identity_required = $buildIdentityRequired
    debug_missing_build_identity_allowed = $debugMissingBuildIdentityAllowed
}

$outputDir = Split-Path -Parent $OutputJson
if ($outputDir -and -not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}
$inventory | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputJson -Encoding UTF8
Write-Host "Installed app inventory JSON: $OutputJson"
Write-Host "Installed app inventory file_count=$($files.Count)"
Write-Host "Installed app inventory forbidden_path_matches=0"
