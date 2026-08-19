param(
    [string]$Version = "",
    [string]$GitExe = "",
    [string]$InnoSetupCompiler = "",
    [string]$OutputRoot = "",
    [switch]$AllowDirty,
    [switch]$WhatIfToolCheckOnly,
    [switch]$KeepPyInstallerOutput,
    [switch]$InspectBundleOnly,
    [switch]$AllowRepoLocalReleaseArtifacts,
    [string]$ManagedWslRootfsTarPath = "",
    [string]$ManagedWslRootfsInventoryPath = "",
    [string]$ManagedWslImageBundleArchivePath = "",
    [string]$ManagedWslImageBundleInventoryPath = "",
    [string]$ManagedWslArtifactRoot = "",
    [string]$ManagedWslArtifactInventoryPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

$script:BuildRootForCleanup = ""
$script:PreserveBuildRoot = $false
$script:OutputFilesForCleanup = @()

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Command,
        [Parameter(Mandatory = $true)][string]$Label
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Resolve-InnoSetupCompiler {
    param([string]$ExplicitPath)
    $candidates = @()
    if ($ExplicitPath) { $candidates += $ExplicitPath }
    if ($env:INNO_SETUP_ISCC) { $candidates += $env:INNO_SETUP_ISCC }
    $userInnoEnv = [Environment]::GetEnvironmentVariable("INNO_SETUP_ISCC", "User")
    if ($userInnoEnv) { $candidates += $userInnoEnv }
    $machineInnoEnv = [Environment]::GetEnvironmentVariable("INNO_SETUP_ISCC", "Machine")
    if ($machineInnoEnv) { $candidates += $machineInnoEnv }
    foreach ($commandName in @("iscc.exe", "iscc")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command) { $candidates += $command.Source }
    }
    if ($env:LOCALAPPDATA) {
        $candidates += (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    }
    $candidates += (Join-Path $env:USERPROFILE "AppData\Local\Programs\Inno Setup 6\ISCC.exe")
    $candidates += @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        $resolved = $null
        if (Test-Path -LiteralPath $candidate) {
            $resolved = (Resolve-Path -LiteralPath $candidate).Path
        }
        else {
            $command = Get-Command $candidate -ErrorAction SilentlyContinue
            if ($command) { $resolved = $command.Source }
        }
        if (-not $resolved) { continue }
        return (Get-InnoSetupCompilerInfo -Path $resolved)
    }
    throw "Inno Setup 6 compiler not found. Set INNO_SETUP_ISCC or pass -InnoSetupCompiler."
}

function Get-VersionMajor {
    param([string]$VersionText)
    if ([string]::IsNullOrWhiteSpace($VersionText)) { return $null }
    if ($VersionText -match "^\s*(\d+)(\.|$)") { return [int]$Matches[1] }
    return $null
}

function Get-InnoSetupCompilerInfo {
    param([Parameter(Mandatory = $true)][string]$Path)
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = (& $Path "/?" *>&1 | Out-String).Trim()
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0 -and $exitCode -ne 1) {
        throw "Inno Setup compiler check failed at $Path with exit code $exitCode."
    }
    if ($output -notmatch "Inno Setup\s+\d+.*Command-Line Compiler") {
        throw "Configured ISCC executable did not identify as the Inno Setup command-line compiler: $Path"
    }

    $versionInfo = (Get-Item -LiteralPath $Path).VersionInfo
    $productVersion = [string]$versionInfo.ProductVersion
    $fileVersion = [string]$versionInfo.FileVersion
    $metadataVersion = ""
    $versionSource = "unreliable_metadata"
    foreach ($candidate in @($productVersion, $fileVersion)) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and $candidate -ne "0.0.0.0") {
            $metadataVersion = $candidate
            $versionSource = if ($candidate -eq $productVersion) { "product_version" } else { "file_version" }
            break
        }
    }

    $helpMajor = $null
    if ($output -match "Inno Setup\s+(\d+).*Command-Line Compiler") {
        $helpMajor = [int]$Matches[1]
    }
    $metadataMajor = Get-VersionMajor -VersionText $metadataVersion
    foreach ($major in @($metadataMajor, $helpMajor)) {
        if ($null -ne $major -and $major -ne 6) {
            throw "Inno Setup compiler must be stable major version 6 for beta packaging. Detected major version $major at $Path."
        }
    }
    if ($null -eq $metadataMajor -and $null -eq $helpMajor) {
        throw "Inno Setup compiler major version could not be detected at $Path."
    }

    return [ordered]@{
        executable = $Path
        version_text = $output.Split([Environment]::NewLine)[0]
        product_version = $productVersion
        file_version = $fileVersion
        version_source = $versionSource
    }
}

function Resolve-GitCommand {
    param([string]$ExplicitPath)
    $candidates = @()
    if ($ExplicitPath) { $candidates += $ExplicitPath }
    if ($env:GIT_EXE) { $candidates += $env:GIT_EXE }
    $gitCommand = Get-Command git -ErrorAction SilentlyContinue
    if ($gitCommand) { $candidates += $gitCommand.Source }
    $candidates += @(
        "C:\Program Files\Git\cmd\git.exe",
        "C:\Program Files\Git\bin\git.exe",
        "C:\Program Files (x86)\Git\cmd\git.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate) {
            $resolved = $null
            if (Test-Path -LiteralPath $candidate) {
                $resolved = (Resolve-Path -LiteralPath $candidate).Path
            }
            else {
                $command = Get-Command $candidate -ErrorAction SilentlyContinue
                if ($command) { $resolved = $command.Source }
            }
            if (-not $resolved) { continue }
            $version = (& $resolved --version 2>&1 | Out-String).Trim()
            if ($LASTEXITCODE -ne 0 -or $version -notmatch "^git version ") {
                throw "Configured Git executable failed verification: $resolved"
            }
            return $resolved
        }
    }
    throw "Git executable not found. Install Git for Windows or set GIT_EXE before building the beta installer."
}

function Assert-PathUnderRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $rootFull = [System.IO.Path]::GetFullPath($Root)
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    $isRoot = $pathFull.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase)
    $isUnderRoot = $pathFull.StartsWith($rootFull.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)
    if (-not ($isRoot -or $isUnderRoot)) {
        throw "$Label path is outside expected root: $pathFull"
    }
}

function Resolve-InstallerOutputRoot {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$CommitSha,
        [string]$RequestedOutputRoot,
        [switch]$AllowRepoLocalReleaseArtifacts
    )
    $outputRoot = if ($RequestedOutputRoot) {
        if ([System.IO.Path]::IsPathRooted($RequestedOutputRoot)) {
            $RequestedOutputRoot
        }
        else {
            Join-Path $RepoRoot $RequestedOutputRoot
        }
    }
    else {
        Join-Path (Get-ImmoAppCanonicalRuntimePaths).AppDataRoot (Join-Path "release_artifacts" (Join-Path "desktop_installer" $CommitSha))
    }
    $full = [System.IO.Path]::GetFullPath($outputRoot)
    $repoTmp = Join-Path $RepoRoot ".tmp"
    $insideRepo = $false
    try {
        Assert-PathUnderRoot -Root $RepoRoot -Path $full -Label "Installer output root"
        $insideRepo = $true
    }
    catch {
        $insideRepo = $false
    }
    if ($insideRepo) {
        $insideTmp = $false
        try {
            Assert-PathUnderRoot -Root $repoTmp -Path $full -Label "Installer output root"
            $insideTmp = $true
        }
        catch {
            $insideTmp = $false
        }
        if (-not $insideTmp -and -not $AllowRepoLocalReleaseArtifacts.IsPresent) {
            throw "Installer output root is inside the Git source tree. Stable release artifacts must use C:\ProgramData\ImmoApp\release_artifacts, or pass -AllowRepoLocalReleaseArtifacts for developer-local output: $full"
        }
    }
    return $full
}

function Assert-NoForbiddenBundledFiles {
    param([Parameter(Mandatory = $true)][string]$BundleRoot)

    $resolvedBundleRoot = (Resolve-Path -LiteralPath $BundleRoot).Path.TrimEnd("\", "/")
    $forbidden = Get-ChildItem -LiteralPath $BundleRoot -Recurse -File -Force |
        ForEach-Object {
            $relative = Get-BundleRelativePath -Root $resolvedBundleRoot -Path $_.FullName
            $matches = @(Get-DesktopBundleForbiddenMatches -RelativePath $relative -FileName $_.Name)
            foreach ($match in $matches) {
                [ordered]@{
                    path = $relative
                    reason = $match
                }
            }
        }
    if ($forbidden) {
        $details = @($forbidden | ForEach-Object { "$($_.path) [$($_.reason)]" })
        throw "Installer bundle contains forbidden source/backend/test/artifact paths: $($details -join '; ')"
    }
}

function Get-BundleRelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd("\", "/")
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    if (-not $pathFull.StartsWith($rootFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unexpected bundled file outside build output root: $pathFull"
    }
    return $pathFull.Substring($rootFull.Length + 1).Replace("\", "/")
}

function Get-InstallerHubPayloadFiles {
    return @(
        "scripts/common.ps1",
        "scripts/setup_office_hub.ps1",
        "scripts/hub_manager.ps1",
        "scripts/hub_manager_authorization.ps1",
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
        "core/models_audit.py"
    )
}

function Get-InstallerCorePayloadFiles {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    $coreRoot = Join-Path $RepoRoot "core"
    if (-not (Test-Path -LiteralPath $coreRoot -PathType Container)) {
        throw "Required core package root is missing: $coreRoot"
    }
    return @(
        Get-ChildItem -LiteralPath $coreRoot -Recurse -File -Force |
            Where-Object {
                $_.FullName -notmatch "\\__pycache__\\" -and
                $_.Name -notmatch "\.pyc$"
            } |
            Sort-Object FullName |
            ForEach-Object {
                "core/" + (Get-BundleRelativePath -Root $coreRoot -Path $_.FullName)
            }
    )
}

function Test-InstallerHubPayloadPathAllowed {
    param([Parameter(Mandatory = $true)][string]$RelativePath)
    $normalized = $RelativePath.Replace("\", "/").Trim("/")
    $lower = $normalized.ToLowerInvariant()
    if ($lower -like "core/*") {
        return $true
    }
    if ($lower -in @(
            "deployment/managed-runtime/rootfs/immoappruntime.rootfs.tar",
            "deployment/managed-runtime/config/managed_wsl2_runtime_rootfs_inventory.json",
            "deployment/managed-runtime/images/immoapp-runtime-images.tar",
            "deployment/managed-runtime/config/managed_wsl2_runtime_image_bundle_inventory.json",
            "deployment/managed-runtime/config/managed_wsl2_runtime_artifact_inventory.json"
        )) {
        return $true
    }
    if ($lower -like "deployment/managed-runtime/artifact/managed-wsl2-artifact/*") {
        return $true
    }
    return (@(Get-InstallerHubPayloadFiles) -contains $normalized)
}

function Copy-HubInstallerPayload {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$BundleRoot
    )
    $payloadFiles = @(
        @(Get-InstallerHubPayloadFiles) +
        @(Get-InstallerCorePayloadFiles -RepoRoot $RepoRoot)
    ) | Select-Object -Unique
    foreach ($relative in $payloadFiles) {
        $source = Join-Path $RepoRoot ($relative.Replace("/", "\"))
        if (-not (Test-Path -LiteralPath $source)) {
            throw "Required Hub installer payload file is missing: $relative"
        }
        $destination = Join-Path $BundleRoot ($relative.Replace("/", "\"))
        $parent = Split-Path -Parent $destination
        if (-not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
}

function Copy-ManagedWsl2RuntimeGeneratedPayload {
    param(
        [Parameter(Mandatory = $true)][string]$BundleRoot,
        [string]$RootfsTarPath,
        [string]$RootfsInventoryPath,
        [string]$ImageBundleArchivePath,
        [string]$ImageBundleInventoryPath,
        [string]$ArtifactRoot,
        [string]$ArtifactInventoryPath,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceCommitSha
    )

    if ([string]::IsNullOrWhiteSpace($RootfsTarPath)) { $RootfsTarPath = Get-ImmoAppManagedWsl2RootfsTarPath }
    if ([string]::IsNullOrWhiteSpace($RootfsInventoryPath)) { $RootfsInventoryPath = Get-ImmoAppManagedWsl2RootfsInventoryPath }
    if ([string]::IsNullOrWhiteSpace($ImageBundleArchivePath)) { $ImageBundleArchivePath = Get-ImmoAppManagedWsl2ImageBundleArchivePath }
    if ([string]::IsNullOrWhiteSpace($ImageBundleInventoryPath)) { $ImageBundleInventoryPath = Get-ImmoAppManagedWsl2ImageBundleInventoryPath }
    if ([string]::IsNullOrWhiteSpace($ArtifactRoot)) { $ArtifactRoot = Join-Path (Ensure-ImmoAppRuntimeLayout).RuntimeRoot "managed-wsl2-artifact" }
    if ([string]::IsNullOrWhiteSpace($ArtifactInventoryPath)) { $ArtifactInventoryPath = Join-Path (Ensure-ImmoAppRuntimeLayout).ConfigRoot "managed_wsl2_runtime_artifact_inventory.json" }
    $allowTestOnlyPath = ([Environment]::GetEnvironmentVariable("IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT") -eq "1")

    foreach ($required in @(
            @{ label = "ManagedWslRootfsTarPath"; path = $RootfsTarPath },
            @{ label = "ManagedWslRootfsInventoryPath"; path = $RootfsInventoryPath },
            @{ label = "ManagedWslImageBundleArchivePath"; path = $ImageBundleArchivePath },
            @{ label = "ManagedWslImageBundleInventoryPath"; path = $ImageBundleInventoryPath },
            @{ label = "ManagedWslArtifactInventoryPath"; path = $ArtifactInventoryPath }
        )) {
        if (-not (Test-Path -LiteralPath ([string]$required.path) -PathType Leaf)) {
            throw "$($required.label) is required for a Hub-capable installer and was not found: $($required.path)"
        }
        if (Test-ImmoAppPathHasReparsePoint -Path ([string]$required.path)) {
            throw "$($required.label) cannot be a reparse point, symlink, or junction: $($required.path)"
        }
    }
    if (-not (Test-Path -LiteralPath $ArtifactRoot -PathType Container)) {
        throw "ManagedWslArtifactRoot is required for a Hub-capable installer and was not found: $ArtifactRoot"
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $ArtifactRoot) {
        throw "ManagedWslArtifactRoot cannot contain a reparse point, symlink, or junction: $ArtifactRoot"
    }

    $rootfsInventory = Get-Content -LiteralPath $RootfsInventoryPath -Raw | ConvertFrom-Json
    if ([string](Get-ImmoAppObjectValue -Data $rootfsInventory -Name "kind") -ne "immoapp_managed_wsl2_runtime_rootfs_inventory" -or
        [string](Get-ImmoAppObjectValue -Data $rootfsInventory -Name "proof_result") -ne "GO") {
        throw "Managed WSL2 runtime rootfs inventory must be GO before installer packaging."
    }
    if ([string](Get-ImmoAppObjectValue -Data $rootfsInventory -Name "source_commit_sha") -cne $ExpectedSourceCommitSha) {
        throw "Managed WSL2 runtime rootfs inventory source commit does not match installer source commit."
    }
    $rootfsSha = [string](Get-ImmoAppObjectValue -Data $rootfsInventory -Name "output_rootfs_tar_sha256")
    Assert-ImmoAppLowerHexSha256 -Value $rootfsSha -Name "output_rootfs_tar_sha256"
    if ((Get-ImmoAppFileSha256 -Path $RootfsTarPath) -ne $rootfsSha) {
        throw "Managed WSL2 runtime rootfs tar hash does not match rootfs inventory."
    }

    $imageInventorySha = Get-ImmoAppFileSha256 -Path $ImageBundleInventoryPath
    $imageInventory = Get-Content -LiteralPath $ImageBundleInventoryPath -Raw | ConvertFrom-Json
    if ([string](Get-ImmoAppObjectValue -Data $imageInventory -Name "source_commit_sha") -cne $ExpectedSourceCommitSha) {
        throw "Managed WSL2 image bundle inventory source commit does not match installer source commit."
    }
    $imageSummary = Assert-ImmoAppManagedWsl2ImageBundleInventoryReady `
        -Inventory $imageInventory `
        -ExpectedInventorySha256 $imageInventorySha `
        -ImageBundleInventoryPath $ImageBundleInventoryPath `
        -AllowTestOnlyPath:$allowTestOnlyPath
    if ([string]$imageSummary.image_archive_path -ne [System.IO.Path]::GetFullPath($ImageBundleArchivePath)) {
        throw "Managed WSL2 image bundle archive path does not match image inventory."
    }

    $artifactInventorySha = Get-ImmoAppFileSha256 -Path $ArtifactInventoryPath
    $artifactInventory = Get-Content -LiteralPath $ArtifactInventoryPath -Raw | ConvertFrom-Json
    if ([string](Get-ImmoAppObjectValue -Data $artifactInventory -Name "source_commit_sha") -cne $ExpectedSourceCommitSha) {
        throw "Managed WSL2 runtime artifact inventory source commit does not match installer source commit."
    }
    Assert-ImmoAppManagedWsl2RuntimeArtifactInventoryReady `
        -Inventory $artifactInventory `
        -ExpectedInventorySha256 $artifactInventorySha `
        -ArtifactInventoryPath $ArtifactInventoryPath `
        -AllowTestOnlyPath:$allowTestOnlyPath | Out-Null

    $payloads = @(
        @{ source = $RootfsTarPath; relative = "deployment\managed-runtime\rootfs\ImmoAppRuntime.rootfs.tar" },
        @{ source = $RootfsInventoryPath; relative = "deployment\managed-runtime\config\managed_wsl2_runtime_rootfs_inventory.json" },
        @{ source = $ImageBundleArchivePath; relative = "deployment\managed-runtime\images\immoapp-runtime-images.tar" },
        @{ source = $ImageBundleInventoryPath; relative = "deployment\managed-runtime\config\managed_wsl2_runtime_image_bundle_inventory.json" },
        @{ source = $ArtifactInventoryPath; relative = "deployment\managed-runtime\config\managed_wsl2_runtime_artifact_inventory.json" }
    )
    foreach ($payload in $payloads) {
        $destination = Join-Path $BundleRoot ([string]$payload.relative)
        $parent = Split-Path -Parent $destination
        if (-not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Copy-Item -LiteralPath ([string]$payload.source) -Destination $destination -Force
    }

    $artifactDestinationRoot = Join-Path $BundleRoot "deployment\managed-runtime\artifact\managed-wsl2-artifact"
    if (Test-Path -LiteralPath $artifactDestinationRoot) {
        Remove-Item -LiteralPath $artifactDestinationRoot -Recurse -Force
    }
    $artifactTree = Get-ImmoAppStrictRuntimeTreeInventory -Root $ArtifactRoot -RequireNonEmpty
    foreach ($file in @($artifactTree.files)) {
        $relative = [string]$file.path
        $source = Join-Path $ArtifactRoot ($relative.Replace("/", "\"))
        $destination = Join-Path $artifactDestinationRoot ($relative.Replace("/", "\"))
        $parent = Split-Path -Parent $destination
        if (-not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
}

function Get-InstallerBundleFileCategory {
    param([Parameter(Mandatory = $true)][string]$RelativePath)
    $relative = $RelativePath.Replace("\", "/").Trim("/")
    $lower = $relative.ToLowerInvariant()
    if ($lower -like "app/assets/*" -or $lower -like "_internal/app/assets/*") {
        if ($lower -like "*ofl.txt" -or $lower -like "*license*") {
            return "license_notice"
        }
        return "asset"
    }
    if ($lower -eq "immoapp.exe" -or $lower -like "_internal/*" -or $lower -like "*.dll" -or $lower -like "*.pyd") {
        return "desktop_runtime"
    }
    if ($lower -eq "immoapp hub manager.exe") {
        return "hub_manager"
    }
    if ($lower -in @("scripts/setup_office_hub.ps1", "scripts/set_hub_identity.ps1", "scripts/get_hub_identity.ps1")) {
        return "hub_setup"
    }
    if ($lower -in @("scripts/hub_manager.ps1", "scripts/hub_manager_authorization.ps1")) {
        return "hub_manager"
    }
    if ($lower -like "deployment/compose/*" -or $lower -like "deployment/env/*") {
        return "deployment_config"
    }
    if ($lower -like "deployment/proxy/*") {
        return "proxy_config"
    }
    if ($lower -like "deployment/managed-runtime/*") {
        return "managed_wsl2_runtime_payload"
    }
    if ($lower -like "core/*") {
        return "runtime_contract"
    }
    if ($lower -in @("scripts/common.ps1", "scripts/detect_hub_runtime.ps1", "scripts/hub_runtime_profile.py", "scripts/verify_hub_network_boundary.ps1")) {
        return "runtime_contract"
    }
    return "supporting_runtime"
}

function Get-InstallerRequiredFileChecks {
    param([Parameter(Mandatory = $true)][object[]]$Files)
    $paths = @($Files | ForEach-Object { [string]$_.relative_path })
    $checks = New-Object System.Collections.Generic.List[object]
    $requirements = @(
        @{ category = "desktop_runtime"; path = "ImmoApp.exe" },
        @{ category = "hub_manager"; path = "ImmoApp Hub Manager.exe" },
        @{ category = "hub_setup"; path = "scripts/setup_office_hub.ps1" },
        @{ category = "hub_setup"; path = "scripts/set_hub_identity.ps1" },
        @{ category = "hub_manager"; path = "scripts/hub_manager.ps1" },
        @{ category = "hub_manager"; path = "scripts/hub_manager_authorization.ps1" },
        @{ category = "deployment_config"; path = "deployment/env/.env.example" },
        @{ category = "runtime_contract"; path = "scripts/common.ps1" },
        @{ category = "runtime_contract"; path = "scripts/detect_hub_runtime.ps1" },
        @{ category = "runtime_contract"; path = "scripts/hub_runtime_profile.py" },
        @{ category = "runtime_contract"; path = "core/__init__.py" },
        @{ category = "runtime_contract"; path = "core/env_files.py" },
        @{ category = "runtime_contract"; path = "core/env_flags.py" },
        @{ category = "runtime_contract"; path = "core/paths.py" },
        @{ category = "runtime_contract"; path = "core/models_audit.py" },
        @{ category = "runtime_contract"; path = "core/runtime/__init__.py" },
        @{ category = "runtime_contract"; path = "core/runtime/hub_runtime_profile.py" },
        @{ category = "managed_wsl2_runtime_payload"; path = "deployment/managed-runtime/rootfs/ImmoAppRuntime.rootfs.tar" },
        @{ category = "managed_wsl2_runtime_payload"; path = "deployment/managed-runtime/images/immoapp-runtime-images.tar" },
        @{ category = "managed_wsl2_runtime_payload"; path = "deployment/managed-runtime/config/managed_wsl2_runtime_rootfs_inventory.json" },
        @{ category = "managed_wsl2_runtime_payload"; path = "deployment/managed-runtime/config/managed_wsl2_runtime_image_bundle_inventory.json" },
        @{ category = "managed_wsl2_runtime_payload"; path = "deployment/managed-runtime/config/managed_wsl2_runtime_artifact_inventory.json" },
        @{ category = "managed_wsl2_runtime_payload"; path = "deployment/managed-runtime/artifact/managed-wsl2-artifact/bin/immoapp-managed-wsl2-bridge.ps1" },
        @{ category = "managed_wsl2_runtime_payload"; path = "deployment/managed-runtime/artifact/managed-wsl2-artifact/bin/backup-managed-hub.ps1" }
    )
    foreach ($required in $requirements) {
        $path = [string]$required.path
        $checks.Add([ordered]@{
                category = [string]$required.category
                relative_path = $path
                present = ($paths -contains $path)
            })
    }
    $licensePresent = @($Files | Where-Object { [string]$_.category -eq "license_notice" }).Count -gt 0
    $assetPresent = @($Files | Where-Object { [string]$_.category -eq "asset" }).Count -gt 0
    $checks.Add([ordered]@{ category = "license_notice"; relative_path = "app/assets/fonts/OFL.txt"; present = $licensePresent })
    $checks.Add([ordered]@{ category = "asset"; relative_path = "app/assets"; present = $assetPresent })
    return @($checks.ToArray())
}

function Get-DesktopBundleForbiddenMatches {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$FileName
    )
    $relative = $RelativePath.Replace("\", "/").Trim("/")
    $lower = $relative.ToLowerInvariant()
    $name = $FileName.ToLowerInvariant()
    $segments = @($lower.Split("/", [System.StringSplitOptions]::RemoveEmptyEntries))
    $result = New-Object System.Collections.Generic.List[string]

    foreach ($segment in @(".git", ".tmp", "tests", "server", "docs", "__pycache__", ".pytest_cache", ".hypothesis")) {
        if ($segments -contains $segment) { $result.Add("forbidden segment '$segment'") }
    }
    if (($segments -contains "scripts" -or $segments -contains "deployment") -and -not (Test-InstallerHubPayloadPathAllowed -RelativePath $relative)) {
        $result.Add("unapproved installer Hub payload path")
    }
    if ($lower -like "app/tests/*" -or $lower -eq "app/tests") { $result.Add("app/tests") }
    if ($name -in @(".env", ".env.local", ".env.production", "immoapp-dev-secrets.json", "openbao.token", "openbao.unseal")) {
        $result.Add("local env or secret file")
    }
    if ($name -match "(secret|password|token|credential|private_key)") { $result.Add("secret-like filename") }
    if ($name -match "\.(sqlite|sqlite3|db|dump|bak)$") { $result.Add("database or dump file") }
    if ($name -match "\.(zip|7z|tar|gz)$" -and ($lower -match "(backup|release|bundle|artifact)")) {
        $result.Add("backup or release archive")
    }
    if (($lower -match "(^|/)(docker-compose|compose)\.ya?ml$" -or $name -eq "dockerfile") -and -not (Test-InstallerHubPayloadPathAllowed -RelativePath $relative)) {
        $result.Add("Docker/backend deployment file")
    }
    foreach ($token in @("release_backup", "release_artifacts", "minio", "postgres", "pgdata", "benchmark_outputs", "perf_outputs", "profiling")) {
        if ($lower.Contains($token) -and -not (Test-InstallerHubPayloadPathAllowed -RelativePath $relative)) {
            $result.Add("local artifact/data token '$token'")
        }
    }
    return @($result.ToArray())
}

function New-DesktopBundleInventory {
    param(
        [Parameter(Mandatory = $true)][string]$BundleRoot,
        [Parameter(Mandatory = $true)][string]$OutputPath,
        [Parameter(Mandatory = $true)][string]$SourceCommitSha,
        [Parameter(Mandatory = $true)][string]$InstallerVersion,
        [Parameter(Mandatory = $true)][string]$GeneratedAtUtc
    )

    $resolvedRoot = (Resolve-Path -LiteralPath $BundleRoot).Path.TrimEnd("\", "/")
    $files = New-Object System.Collections.Generic.List[object]
    $forbidden = New-Object System.Collections.Generic.List[object]
    $totalBytes = [int64]0
    foreach ($file in Get-ChildItem -LiteralPath $BundleRoot -Recurse -File -Force | Sort-Object FullName) {
        $relative = Get-BundleRelativePath -Root $resolvedRoot -Path $file.FullName
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $category = Get-InstallerBundleFileCategory -RelativePath $relative
        $totalBytes += [int64]$file.Length
        $files.Add([ordered]@{
                relative_path = $relative
                path = $relative
                size_bytes = [int64]$file.Length
                bytes = [int64]$file.Length
                sha256 = $hash
                category = $category
            })
        foreach ($match in @(Get-DesktopBundleForbiddenMatches -RelativePath $relative -FileName $file.Name)) {
            $forbidden.Add([ordered]@{
                    path = $relative
                    relative_path = $relative
                    reason = $match
                })
        }
    }
    $topLevel = @(Get-ChildItem -LiteralPath $BundleRoot -Force | Sort-Object Name | ForEach-Object { $_.Name })
    $fileEntries = @($files.ToArray())
    $forbiddenEntries = @($forbidden.ToArray())
    $requiredChecks = @(Get-InstallerRequiredFileChecks -Files $fileEntries)
    $missingRequiredChecks = @($requiredChecks | Where-Object { $_.present -ne $true })
    $proofResult = if ($forbiddenEntries.Count -eq 0 -and $missingRequiredChecks.Count -eq 0) { "GO" } else { "NO-GO" }
    $inventory = [ordered]@{
        kind = "immoapp_installer_package_inventory"
        schema_version = 1
        created_at_utc = $GeneratedAtUtc
        source_commit_sha = $SourceCommitSha
        installer_role_support = "desktop_and_or_hub"
        supports_desktop_only = $true
        supports_hub_only = $true
        supports_desktop_and_hub = $true
        installer_version = $InstallerVersion
        generated_at_utc = $GeneratedAtUtc
        pyinstaller_output_dir = $BundleRoot
        top_level_entries = @($topLevel)
        file_count = $files.Count
        total_bytes = $totalBytes
        total_file_count = $files.Count
        total_byte_size = $totalBytes
        files = $fileEntries
        forbidden_path_matches = $forbiddenEntries
        detected_forbidden_paths = $forbiddenEntries
        required_file_checks = $requiredChecks
        missing_required_file_checks = $missingRequiredChecks
        proof_result = $proofResult
        expected_runtime_categories = @(
            "desktop_runtime",
            "hub_setup",
            "hub_manager",
            "deployment_config",
            "proxy_config",
            "runtime_contract",
            "managed_wsl2_runtime_payload",
            "license_notice",
            "asset"
        )
        forbidden_policy = @(
            ".git",
            ".tmp",
            "tests",
            "app/tests",
            "server",
            "unapproved scripts",
            "unapproved deployment files",
            "docs",
            "__pycache__",
            ".pytest_cache",
            ".hypothesis",
            "backup bundles",
            "release artifact folders",
            "local env files",
            "secrets",
            "database files",
            "Docker compose files",
            "MinIO/Postgres data"
        )
    }
    $inventory | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    if ($forbidden.Count -gt 0) {
        $details = @($forbidden | ForEach-Object { "$($_.path) [$($_.reason)]" })
        throw "Desktop bundle inventory found forbidden paths: $($details -join '; ')"
    }
    if ($missingRequiredChecks.Count -gt 0) {
        $details = @($missingRequiredChecks | ForEach-Object { "$($_.category):$($_.relative_path)" })
        throw "Desktop bundle inventory missing required installer role files: $($details -join '; ')"
    }
    return $inventory
}

$repoRoot = (Get-ImmoAppRepoRoot).Path
$git = Resolve-GitCommand -ExplicitPath $GitExe

if (-not $AllowDirty.IsPresent) {
    $status = & $git -C $repoRoot status --short
    if ($LASTEXITCODE -ne 0) {
        throw "git status failed with exit code $LASTEXITCODE"
    }
    if ($status) {
        throw "Refusing to build installer from a dirty worktree. Commit/stash changes or pass -AllowDirty for non-release troubleshooting."
    }
}

$gitShaFull = (& $git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $gitShaFull) {
    throw "Unable to resolve git build identity."
}
$gitSha = $gitShaFull.Substring(0, 12)

$isccInfo = Resolve-InnoSetupCompiler -ExplicitPath $InnoSetupCompiler
$iscc = $isccInfo.executable

if ($WhatIfToolCheckOnly.IsPresent) {
    $gitVersion = (& $git --version 2>&1 | Out-String).Trim()
    Write-Host "Git executable: $git"
    Write-Host "Git version: $gitVersion"
    Write-Host "Source commit SHA: $gitShaFull"
    Write-Host "ISCC executable: $($isccInfo.executable)"
    Write-Host "ISCC version text: $($isccInfo.version_text)"
    Write-Host "ISCC product version: $($isccInfo.product_version)"
    Write-Host "ISCC file version: $($isccInfo.file_version)"
    Write-Host "ISCC version source: $($isccInfo.version_source)"
    Write-Host "Installer tool check passed."
    exit 0
}

$clientPython = Get-ImmoAppVenvPython -Kind client
if (-not (Test-Path $clientPython)) {
    throw "Client venv python not found at $clientPython"
}

if (-not $Version) {
    $Version = (& $clientPython -c "import tomllib, pathlib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'])").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $Version) {
        throw "Unable to resolve project version from pyproject.toml."
    }
}

$buildRoot = Join-Path $repoRoot (".tmp\desktop_installer_build_" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
$script:BuildRootForCleanup = $buildRoot
trap {
    $originalError = $_
    foreach ($path in @($script:OutputFilesForCleanup)) {
        if ($path -and (Test-Path -LiteralPath $path)) {
            Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        }
    }
    if ($script:BuildRootForCleanup -and -not $script:PreserveBuildRoot -and (Test-Path -LiteralPath $script:BuildRootForCleanup)) {
        Remove-Item -LiteralPath $script:BuildRootForCleanup -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw $originalError
}
$script:PreserveBuildRoot = ($KeepPyInstallerOutput.IsPresent -or $InspectBundleOnly.IsPresent)
$venvRoot = Join-Path $buildRoot "venv"
$pyiWork = Join-Path $buildRoot "pyinstaller"
$hubManagerDistRoot = Join-Path $buildRoot "hub-manager-dist"
$identityPath = Join-Path $buildRoot "build_identity.json"
$installerIdentityPath = Join-Path $buildRoot "installer_build_identity.json"
$bundleDistRoot = Join-Path $buildRoot "dist"
$installerOut = Resolve-InstallerOutputRoot -RepoRoot $repoRoot -CommitSha $gitSha -RequestedOutputRoot $OutputRoot -AllowRepoLocalReleaseArtifacts:($AllowRepoLocalReleaseArtifacts.IsPresent)
$sourceDir = Join-Path $bundleDistRoot "ImmoApp"
$outputBase = "ImmoApp-Beta-$Version-Setup"
$summaryPath = Join-Path $installerOut "$outputBase.summary.json"
$inventoryPath = Join-Path $installerOut "$outputBase.bundle_inventory.json"
$script:OutputFilesForCleanup = @($summaryPath, $inventoryPath)

Assert-PathUnderRoot -Root (Join-Path $repoRoot ".tmp") -Path $buildRoot -Label "Installer build root"
if (Test-Path -LiteralPath $buildRoot) {
    throw "Installer build root already exists: $buildRoot"
}
New-Item -ItemType Directory -Path $buildRoot, $bundleDistRoot | Out-Null
if (-not (Test-Path -LiteralPath $installerOut)) {
    New-Item -ItemType Directory -Path $installerOut | Out-Null
}
if (Test-Path -LiteralPath $summaryPath) {
    throw "Installer summary already exists and will not be overwritten: $summaryPath"
}
if (Test-Path -LiteralPath $inventoryPath) {
    throw "Desktop bundle inventory already exists and will not be overwritten: $inventoryPath"
}

Invoke-Checked -Label "build venv creation" -Command { & $clientPython -m venv $venvRoot }
$buildPython = Join-Path $venvRoot "Scripts\python.exe"
if (-not (Test-Path $buildPython)) {
    throw "Build venv python not found at $buildPython"
}

Invoke-Checked -Label "pip bootstrap" -Command { & $buildPython -m pip install --upgrade pip }
Invoke-Checked -Label "client dependency install" -Command { & $buildPython -m pip install -r (Join-Path $repoRoot "requirements\client.txt") }
Invoke-Checked -Label "packaging dependency install" -Command { & $buildPython -m pip install -r (Join-Path $repoRoot "requirements\packaging.txt") }

$buildTimeUtc = (Get-Date).ToUniversalTime().ToString("o")
$identity = @{
    version = $Version
    git_sha = $gitShaFull
    git_sha_short = $gitSha
    build_time_utc = $buildTimeUtc
    source = "installer"
} | ConvertTo-Json -Depth 4
Set-Content -Path $identityPath -Value $identity -Encoding UTF8
$installerIdentity = [ordered]@{
    kind = "immoapp_installer_build_identity"
    schema_version = 1
    source_commit_sha = $gitShaFull
    installer_version = $Version
    build_time_utc = $buildTimeUtc
    bundle_inventory_sha256 = ""
    bundle_inventory_sha256_source = "build_summary_after_pyinstaller_inventory"
    installer_expected_name = "$outputBase.exe"
    desktop_client_only = $false
    installer_role_support = "desktop_and_or_hub"
    supports_desktop_only = $true
    supports_hub_only = $true
    supports_desktop_and_hub = $true
    office_hub_role_supported = $true
}
$installerIdentity | ConvertTo-Json -Depth 4 | Set-Content -Path $installerIdentityPath -Encoding UTF8

$assetsPath = Join-Path $repoRoot "app\assets"
$mainPath = Join-Path $repoRoot "app\main.py"
$hubManagerMainPath = Join-Path $repoRoot "app\hub_manager_app.py"
$pyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--onedir",
    "--name", "ImmoApp",
    "--distpath", $bundleDistRoot,
    "--workpath", $pyiWork,
    "--specpath", $buildRoot,
    "--paths", $repoRoot,
    "--hidden-import", "PySide6.QtWebSockets",
    "--collect-submodules", "keyring.backends",
    "--exclude-module", "app.tests",
    "--exclude-module", "tests",
    "--exclude-module", "scripts",
    "--exclude-module", "server",
    "--exclude-module", "deployment",
    "--exclude-module", "docs",
    "--add-data", "$assetsPath;app\assets",
    "--add-data", "$identityPath;app",
    "--add-data", "$installerIdentityPath;app",
    $mainPath
)
Invoke-Checked -Label "PyInstaller desktop bundle" -Command { & $buildPython @pyInstallerArgs }

if (-not (Test-Path (Join-Path $sourceDir "ImmoApp.exe"))) {
    throw "PyInstaller did not produce ImmoApp.exe under $sourceDir"
}

$hubManagerPyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--onedir",
    "--name", "ImmoApp Hub Manager",
    "--distpath", $hubManagerDistRoot,
    "--workpath", (Join-Path $pyiWork "hub_manager"),
    "--specpath", $buildRoot,
    "--paths", $repoRoot,
    "--hidden-import", "scripts.create_hub_owner_authorization_evidence",
    "--hidden-import", "app.services.hub_manager_access_client",
    "--contents-directory", "_internal",
    "--exclude-module", "app.tests",
    "--exclude-module", "tests",
    "--exclude-module", "deployment",
    "--exclude-module", "docs",
    $hubManagerMainPath
)
Invoke-Checked -Label "PyInstaller Hub Manager bundle" -Command { & $buildPython @hubManagerPyInstallerArgs }

$hubManagerBuiltExe = Join-Path $hubManagerDistRoot "ImmoApp Hub Manager\ImmoApp Hub Manager.exe"
if (-not (Test-Path $hubManagerBuiltExe)) {
    throw "PyInstaller did not produce ImmoApp Hub Manager.exe under $hubManagerDistRoot"
}
Copy-Item -LiteralPath $hubManagerBuiltExe -Destination (Join-Path $sourceDir "ImmoApp Hub Manager.exe") -Force
if (-not (Test-Path (Join-Path $sourceDir "ImmoApp Hub Manager.exe"))) {
    throw "Hub Manager launcher was not copied into installer bundle root."
}
Copy-HubInstallerPayload -RepoRoot $repoRoot -BundleRoot $sourceDir
Copy-ManagedWsl2RuntimeGeneratedPayload `
    -BundleRoot $sourceDir `
    -RootfsTarPath $ManagedWslRootfsTarPath `
    -RootfsInventoryPath $ManagedWslRootfsInventoryPath `
    -ImageBundleArchivePath $ManagedWslImageBundleArchivePath `
    -ImageBundleInventoryPath $ManagedWslImageBundleInventoryPath `
    -ArtifactRoot $ManagedWslArtifactRoot `
    -ArtifactInventoryPath $ManagedWslArtifactInventoryPath `
    -ExpectedSourceCommitSha $gitShaFull
$inventory = New-DesktopBundleInventory `
    -BundleRoot $sourceDir `
    -OutputPath $inventoryPath `
    -SourceCommitSha $gitShaFull `
    -InstallerVersion $Version `
    -GeneratedAtUtc $buildTimeUtc
Assert-NoForbiddenBundledFiles -BundleRoot $sourceDir
$inventoryHash = (Get-FileHash -LiteralPath $inventoryPath -Algorithm SHA256).Hash.ToLowerInvariant()
$installerIdentityBundleInventoryHash = ""
$copiedInstallerIdentityPath = @(
    (Join-Path $sourceDir "_internal\app\installer_build_identity.json"),
    (Join-Path $sourceDir "app\installer_build_identity.json")
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($copiedInstallerIdentityPath) {
    $installerIdentity["bundle_inventory_sha256"] = $inventoryHash
    $installerIdentity["bundle_inventory_sha256_source"] = "pre_identity_update_inventory"
    $installerIdentityBundleInventoryHash = $inventoryHash
    $installerIdentity | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $copiedInstallerIdentityPath -Encoding UTF8
    $inventory = New-DesktopBundleInventory `
        -BundleRoot $sourceDir `
        -OutputPath $inventoryPath `
        -SourceCommitSha $gitShaFull `
        -InstallerVersion $Version `
        -GeneratedAtUtc $buildTimeUtc
    $inventoryHash = (Get-FileHash -LiteralPath $inventoryPath -Algorithm SHA256).Hash.ToLowerInvariant()
}

if ($InspectBundleOnly.IsPresent) {
    $summary = [ordered]@{
        kind = "immoapp_desktop_installer_build_summary"
        installer_role = "desktop_and_or_hub"
        installer_role_support = "desktop_and_or_hub"
        supports_desktop_only = $true
        supports_hub_only = $true
        supports_desktop_and_hub = $true
        installs_office_hub_backend = "when_hub_desktop_role_selected"
        office_hub_role_supported = $true
        inspect_bundle_only = $true
        installer_path = $null
        installer_sha256 = $null
        installer_signed = $null
        authenticode_status = "not_built_inspect_bundle_only"
        source_commit_sha = $gitShaFull
        source_commit_sha_short = $gitSha
        source_worktree_clean = (-not $AllowDirty.IsPresent)
        git_executable = $git
        iscc_executable = $isccInfo.executable
        iscc_version_text = $isccInfo.version_text
        iscc_product_version = $isccInfo.product_version
        iscc_file_version = $isccInfo.file_version
        iscc_version_source = $isccInfo.version_source
        version = $Version
        public_installer_name = "$outputBase.exe"
        internal_build_id = "$Version-$gitSha"
        build_identity_file = "app/build_identity.json"
        built_at_utc = $buildTimeUtc
        pyinstaller_output_dir = $sourceDir
        pyinstaller_build_root = $buildRoot
        pyinstaller_output_preserved = $true
        bundle_inventory_path = $inventoryPath
        bundle_inventory_sha256 = $inventoryHash
        package_inventory_path = $inventoryPath
        package_inventory_sha256 = $inventoryHash
        installer_identity_bundle_inventory_sha256 = $installerIdentityBundleInventoryHash
        bundle_inventory_file_count = $inventory["file_count"]
        bundle_inventory_total_byte_size = $inventory["total_bytes"]
        package_inventory_proof_result = $inventory["proof_result"]
    }
    $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    Write-Host "Desktop bundle inventory created: $inventoryPath" -ForegroundColor Green
    Write-Host "Desktop bundle inventory SHA-256: $inventoryHash" -ForegroundColor Green
    Write-Host "PyInstaller output preserved: $sourceDir" -ForegroundColor Green
    Write-Host "InspectBundleOnly requested; Inno installer compile skipped." -ForegroundColor Yellow
    Write-Host "Build summary: $summaryPath" -ForegroundColor Green
    exit 0
}

$issPath = Join-Path $repoRoot "deployment\installer\ImmoAppBeta.iss"
$installerPath = Join-Path $installerOut "$outputBase.exe"
$script:OutputFilesForCleanup = @($summaryPath, $inventoryPath, $installerPath)
if (Test-Path -LiteralPath $installerPath) {
    throw "Installer output already exists and will not be overwritten: $installerPath"
}
if (Test-Path -LiteralPath $summaryPath) {
    throw "Installer summary already exists and will not be overwritten: $summaryPath"
}
$oldInstallerVersion = $env:IMMOAPP_INSTALLER_VERSION
$oldInstallerSource = $env:IMMOAPP_INSTALLER_SOURCE_DIR
$oldInstallerOutput = $env:IMMOAPP_INSTALLER_OUTPUT_DIR
$oldInstallerBase = $env:IMMOAPP_INSTALLER_OUTPUT_BASE
try {
    $env:IMMOAPP_INSTALLER_VERSION = $Version
    $env:IMMOAPP_INSTALLER_SOURCE_DIR = $sourceDir
    $env:IMMOAPP_INSTALLER_OUTPUT_DIR = $installerOut
    $env:IMMOAPP_INSTALLER_OUTPUT_BASE = $outputBase
    Invoke-Checked -Label "Inno Setup installer compile" -Command { & $iscc $issPath }
}
finally {
    if ($null -ne $oldInstallerVersion) { $env:IMMOAPP_INSTALLER_VERSION = $oldInstallerVersion } else { Remove-Item Env:IMMOAPP_INSTALLER_VERSION -ErrorAction SilentlyContinue }
    if ($null -ne $oldInstallerSource) { $env:IMMOAPP_INSTALLER_SOURCE_DIR = $oldInstallerSource } else { Remove-Item Env:IMMOAPP_INSTALLER_SOURCE_DIR -ErrorAction SilentlyContinue }
    if ($null -ne $oldInstallerOutput) { $env:IMMOAPP_INSTALLER_OUTPUT_DIR = $oldInstallerOutput } else { Remove-Item Env:IMMOAPP_INSTALLER_OUTPUT_DIR -ErrorAction SilentlyContinue }
    if ($null -ne $oldInstallerBase) { $env:IMMOAPP_INSTALLER_OUTPUT_BASE = $oldInstallerBase } else { Remove-Item Env:IMMOAPP_INSTALLER_OUTPUT_BASE -ErrorAction SilentlyContinue }
}

if (-not (Test-Path $installerPath)) {
    throw "Installer was not produced at $installerPath"
}
$installerHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$signature = Get-AuthenticodeSignature -LiteralPath $installerPath
$summary = [ordered]@{
    kind = "immoapp_desktop_installer_build_summary"
    installer_role = "desktop_and_or_hub"
    installer_role_support = "desktop_and_or_hub"
    supports_desktop_only = $true
    supports_hub_only = $true
    supports_desktop_and_hub = $true
    installs_office_hub_backend = "when_hub_desktop_role_selected"
    office_hub_role_supported = $true
    installer_path = $installerPath
    installer_sha256 = $installerHash
    installer_signed = if ($signature.Status -eq "Valid") { $true } elseif ($signature.Status -eq "NotSigned") { $false } else { $null }
    authenticode_status = [string]$signature.Status
    source_commit_sha = $gitShaFull
    source_commit_sha_short = $gitSha
    source_worktree_clean = (-not $AllowDirty.IsPresent)
    git_executable = $git
    iscc_executable = $isccInfo.executable
    iscc_version_text = $isccInfo.version_text
    iscc_product_version = $isccInfo.product_version
    iscc_file_version = $isccInfo.file_version
    iscc_version_source = $isccInfo.version_source
    version = $Version
    public_installer_name = "$outputBase.exe"
    internal_build_id = "$Version-$gitSha"
    build_identity_file = "app/build_identity.json"
    built_at_utc = $buildTimeUtc
    pyinstaller_output_dir = $sourceDir
    pyinstaller_build_root = $buildRoot
    pyinstaller_output_preserved = ($KeepPyInstallerOutput.IsPresent)
    bundle_inventory_path = $inventoryPath
    bundle_inventory_sha256 = $inventoryHash
    package_inventory_path = $inventoryPath
    package_inventory_sha256 = $inventoryHash
    installer_identity_bundle_inventory_sha256 = $installerIdentityBundleInventoryHash
    bundle_inventory_file_count = $inventory["file_count"]
    bundle_inventory_total_byte_size = $inventory["total_bytes"]
    package_inventory_proof_result = $inventory["proof_result"]
}
$summary | ConvertTo-Json -Depth 8 | Set-Content -Path $summaryPath -Encoding UTF8

Write-Warning "Unsigned beta installers can trigger Windows SmartScreen. Configure signing separately before broad distribution."
Write-Host "Desktop bundle inventory created: $inventoryPath" -ForegroundColor Green
Write-Host "Desktop bundle inventory SHA-256: $inventoryHash" -ForegroundColor Green
Write-Host "Desktop installer created: $installerPath" -ForegroundColor Green
Write-Host "Desktop installer SHA-256: $installerHash" -ForegroundColor Green
Write-Host "Desktop installer Authenticode status: $($signature.Status)" -ForegroundColor Green
Write-Host "Source commit SHA: $gitShaFull" -ForegroundColor Green
Write-Host "Git executable: $git" -ForegroundColor Green
Write-Host "ISCC executable: $($isccInfo.executable)" -ForegroundColor Green
Write-Host "ISCC version text: $($isccInfo.version_text)" -ForegroundColor Green
Write-Host "ISCC product version: $($isccInfo.product_version)" -ForegroundColor Green
Write-Host "ISCC file version: $($isccInfo.file_version)" -ForegroundColor Green
Write-Host "ISCC version source: $($isccInfo.version_source)" -ForegroundColor Green
if ($KeepPyInstallerOutput.IsPresent) {
    Write-Host "PyInstaller output preserved: $sourceDir" -ForegroundColor Green
}
Write-Host "Build summary: $summaryPath" -ForegroundColor Green

if ((-not $KeepPyInstallerOutput.IsPresent) -and (Test-Path -LiteralPath $buildRoot)) {
    Remove-Item -LiteralPath $buildRoot -Recurse -Force -ErrorAction SilentlyContinue
}
