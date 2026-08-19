param(
    [string]$RuntimeSourceRoot = "",
    [string]$OutputRoot = "",
    [string]$SourceCommitSha = "",
    [string]$PackageName = "immoapp-managed-hub-runtime-proof",
    [string]$RuntimeExecutableRelativePath = "",
    [string]$ComposeExecutableRelativePath = "",
    [string]$VendorProvenanceJson = "",
    [switch]$AllowProofOnlyRuntime,
    [switch]$AllowExternalRuntimeSource,
    [switch]$AllowDirtyRuntimePackageProof,
    [switch]$AllowSourceCommitOverride,
    [switch]$AllowReplaceOutputRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-GitCommitSha {
    try {
        $repoRoot = (Get-ImmoAppRepoRoot).Path
        $sha = (& git -C $repoRoot rev-parse HEAD 2>$null | Out-String).Trim().ToLowerInvariant()
        if ($LASTEXITCODE -eq 0 -and $sha) { return $sha }
    }
    catch {
        return ""
    }
    return ""
}

function Test-LowerGitSha {
    param([string]$Value)
    return (-not [string]::IsNullOrWhiteSpace($Value) -and $Value -match "^[0-9a-f]{40}$")
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Convert-BytesToHex {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)
    return (($Bytes | ForEach-Object { $_.ToString("x2") }) -join "")
}

function Get-StreamSha256 {
    param([Parameter(Mandatory = $true)][System.IO.Stream]$Stream)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return (Convert-BytesToHex -Bytes $sha.ComputeHash($Stream))
    }
    finally {
        $sha.Dispose()
    }
}

function Get-RelativeRuntimePackagePath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd("\", "/")
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    $separator = [System.IO.Path]::DirectorySeparatorChar
    if ($pathFull.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return ""
    }
    if ($pathFull.StartsWith($rootFull + $separator, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $pathFull.Substring($rootFull.Length + 1).Replace("\", "/")
    }
    return $pathFull.Replace("\", "/")
}

function Normalize-PackageRelativePath {
    param([string]$Path)
    $clean = $Path.Trim().Replace("\", "/")
    if ($clean.StartsWith("./")) {
        return $clean.Substring(2)
    }
    return $clean
}

function Convert-PackagePathToSourcePath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )
    if (Test-UnsafeArchivePath -RelativePath $RelativePath) {
        return ""
    }
    $combined = Join-Path $Root ($RelativePath.Replace("/", [string][System.IO.Path]::DirectorySeparatorChar))
    $fullRoot = [System.IO.Path]::GetFullPath($Root)
    $fullCombined = [System.IO.Path]::GetFullPath($combined)
    if (-not (Test-ImmoAppPathUnderRoot -Root $fullRoot -Path $fullCombined)) {
        return ""
    }
    if (-not (Test-Path -LiteralPath $fullCombined -PathType Leaf)) {
        return ""
    }
    return $fullCombined
}

function Get-GitState {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    $state = [ordered]@{
        git_available = $false
        git_status_ok = $false
        git_head_sha = ""
        dirty_file_count = 0
        dirty_state_verified = $false
        failure_reason = ""
    }
    try {
        $git = Get-Command git -ErrorAction SilentlyContinue
        if ($null -eq $git) {
            $state.failure_reason = "managed_runtime_git_unavailable"
            return $state
        }
        $state.git_available = $true
        $head = (& git -C $RepoRoot rev-parse HEAD 2>&1 | Out-String).Trim().ToLowerInvariant()
        if ($LASTEXITCODE -ne 0 -or -not (Test-LowerGitSha -Value $head)) {
            $state.failure_reason = "managed_runtime_git_head_unverified"
            return $state
        }
        $state.git_head_sha = $head
        $status = & git -C $RepoRoot status --porcelain --untracked-files=all 2>$null
        if ($LASTEXITCODE -ne 0) {
            $state.failure_reason = "managed_runtime_git_status_failed"
            return $state
        }
        $state.git_status_ok = $true
        $state.dirty_file_count = @($status | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }).Count
        $state.dirty_state_verified = $true
        return $state
    }
    catch {
        $state.failure_reason = "managed_runtime_git_status_failed"
        return $state
    }
}

function Test-GitTrackedSourceFile {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Path
    )
    try {
        $relative = Get-RelativeRuntimePackagePath -Root $RepoRoot -Path $Path
        & git -C $RepoRoot ls-files --error-unmatch -- $relative *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Test-UnsafeArchivePath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)
    return Test-ImmoAppUnsafeArchivePath -RelativePath $RelativePath
}

function Get-ForbiddenRuntimePackageReason {
    param([Parameter(Mandatory = $true)][string]$RelativePath)
    return Get-ImmoAppForbiddenRuntimePackageReason -RelativePath $RelativePath
}

function New-InventoryPayload {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$CommitSha,
        [Parameter(Mandatory = $true)][string]$ProofResult,
        [Parameter(Mandatory = $true)][string]$ReasonCode,
        [string]$FailureReason = "",
        [string]$RuntimeSourceRoot = "",
        [string]$PackagePath = "",
        [string]$PackageSha256 = "",
        [int64]$PackageBytes = 0,
        [object[]]$Files = @(),
        [object[]]$ForbiddenMatches = @(),
        [object]$CriticalExecutables = $null,
        [bool]$ProofOnly = $false,
        [bool]$SourceTreeClean = $false,
        [bool]$SourceCommitOverride = $false,
        [string]$RuntimeSourceOrigin = "",
        [int]$DirtyFilesSummaryCount = 0,
        [string]$ExtractedInventorySha256 = "",
        [string]$VendorProvenancePath = "",
        [string]$VendorProvenanceSha256 = "",
        [object]$GitState = $null
    )
    $fileCount = @($Files).Count
    $totalBytes = 0L
    foreach ($file in @($Files)) {
        $totalBytes += [int64]$file.bytes
    }
    if ($null -eq $CriticalExecutables) {
        $CriticalExecutables = [ordered]@{
            runtime_executable_relative_path = ""
            compose_executable_relative_path = ""
        }
    }
    return [ordered]@{
        kind = "immoapp_managed_hub_runtime_package_inventory"
        schema_version = 2
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        source_commit_sha = $CommitSha
        runtime_source_root = $RuntimeSourceRoot
        proof_result = $ProofResult
        reason_code = $ReasonCode
        failure_reason = $FailureReason
        package_path = $PackagePath
        package_sha256 = $PackageSha256
        package_bytes = $PackageBytes
        package_file_count = $fileCount
        file_count = $fileCount
        total_bytes = $totalBytes
        source_tree_clean = [bool]$SourceTreeClean
        source_commit_override = [bool]$SourceCommitOverride
        runtime_source_origin = $RuntimeSourceOrigin
        dirty_files_summary_count = [int]$DirtyFilesSummaryCount
        extracted_inventory_sha256 = $ExtractedInventorySha256
        vendor_provenance_path = $VendorProvenancePath
        vendor_provenance_sha256 = $VendorProvenanceSha256
        git_state = $GitState
        proof_only = [bool]$ProofOnly
        critical_executables = $CriticalExecutables
        forbidden_matches = @($ForbiddenMatches)
        files = @($Files)
    }
}

function Write-Inventory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Payload
    )
    $outputRoot = $script:ManagedRuntimePackageOutputRoot
    if (-not [string]::IsNullOrWhiteSpace($outputRoot)) {
        if (-not (Test-ImmoAppPathUnderRoot -Root $outputRoot -Path $Path) -or -not (Test-ImmoAppResolvedPathUnderRoot -Root $outputRoot -Path $Path)) {
            throw "managed_runtime_inventory_output_outside_output_root|Inventory output path escaped OutputRoot: $Path"
        }
        if ((Test-Path -LiteralPath $Path) -and (Test-ImmoAppPathHasReparsePoint -Path $Path)) {
            throw "managed_runtime_inventory_output_reparse_point|Inventory output path contains a reparse point: $Path"
        }
        $parent = Split-Path -Parent $Path
        if ($parent -and (Test-Path -LiteralPath $parent) -and (Test-ImmoAppPathHasReparsePoint -Path $parent)) {
            throw "managed_runtime_inventory_output_reparse_point|Inventory output parent contains a reparse point: $parent"
        }
        Write-ImmoAppSafeJson -Path $Path -Payload $Payload -ApprovedRoots @($outputRoot) -Depth 14 | Out-Null
    }
    else {
        Write-ImmoAppSafeJson -Path $Path -Payload $Payload -ApprovedRoots @((Split-Path -Parent $Path)) -Depth 14 | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 14
}

function Assert-ManagedRuntimePackageOutputRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][object]$RuntimePaths
    )
    $full = [System.IO.Path]::GetFullPath($Path)
    $existing = $full
    while (-not [string]::IsNullOrWhiteSpace($existing) -and -not (Test-Path -LiteralPath $existing)) {
        $next = Split-Path -Parent $existing
        if ([string]::IsNullOrWhiteSpace($next) -or $next -eq $existing) { break }
        $existing = $next
    }
    if (-not [string]::IsNullOrWhiteSpace($existing) -and (Test-Path -LiteralPath $existing) -and (Test-ImmoAppPathHasReparsePoint -Path $existing)) {
        throw "managed_runtime_output_root_reparse_point|OutputRoot or one of its existing parents is a reparse point, symlink, or junction: $existing"
    }
    $repoTmp = Join-Path $RepoRoot ".tmp"
    $canonicalPaths = Get-ImmoAppCanonicalRuntimePaths
    $approvedRoots = New-Object System.Collections.Generic.List[string]
    foreach ($root in @($repoTmp, $canonicalPaths.RuntimeRoot, $canonicalPaths.ConfigRoot, $canonicalPaths.LogsRoot)) {
        if (-not [string]::IsNullOrWhiteSpace([string]$root)) {
            [void]$approvedRoots.Add([string]$root)
        }
    }
    if ((Get-ImmoAppRuntimeRootSource) -ne "canonical_programdata") {
        [void]$approvedRoots.Add([string]$RuntimePaths.AppDataRoot)
    }
    $insideRepo = Test-ImmoAppPathUnderRoot -Root $RepoRoot -Path $full
    if ($insideRepo -and -not (Test-ImmoAppPathUnderRoot -Root $repoTmp -Path $full)) {
        throw "managed_runtime_output_root_repo_root_not_allowed|OutputRoot inside the repo must be under .tmp: $full"
    }
    $underApprovedRoot = $false
    foreach ($root in @($approvedRoots.ToArray())) {
        if ((Test-ImmoAppPathUnderRoot -Root $root -Path $full) -and (Test-ImmoAppResolvedPathUnderRoot -Root $root -Path $full)) {
            $underApprovedRoot = $true
            break
        }
        if ((Test-ImmoAppPathUnderRoot -Root $root -Path $full) -and -not (Test-ImmoAppResolvedPathUnderRoot -Root $root -Path $full)) {
            throw "managed_runtime_output_root_resolved_outside_approved_root|OutputRoot resolves outside approved root: $full"
        }
    }
    if (-not $underApprovedRoot) {
        throw "managed_runtime_output_root_not_approved|OutputRoot must be under repo .tmp, canonical ProgramData runtime/config/logs, or an explicit test ProgramData root: $full"
    }
    return $full
}

function Verify-ZipMatchesInventory {
    param(
        [Parameter(Mandatory = $true)][string]$PackagePath,
        [Parameter(Mandatory = $true)][object[]]$Files
    )
    $expected = @{}
    foreach ($file in @($Files)) {
        $expected[[string]$file.path] = $file
    }
    $seen = @{}
    $stream = [System.IO.File]::OpenRead($PackagePath)
    try {
        $zip = [System.IO.Compression.ZipArchive]::new($stream, [System.IO.Compression.ZipArchiveMode]::Read)
        try {
            $entries = @($zip.Entries | Where-Object { -not [string]::IsNullOrEmpty($_.Name) })
            if ($entries.Count -ne $expected.Count) {
                return "package entry count does not match inventory"
            }
            foreach ($entry in $entries) {
                $name = $entry.FullName.Replace("\", "/")
                if (-not $expected.ContainsKey($name)) {
                    return "package entry is not in inventory: $name"
                }
                if ($seen.ContainsKey($name.ToLowerInvariant())) {
                    return "package contains duplicate archive entry: $name"
                }
                $seen[$name.ToLowerInvariant()] = $true
                $file = $expected[$name]
                if ([int64]$entry.Length -ne [int64]$file.bytes) {
                    return "package entry byte length mismatch: $name"
                }
                $entryStream = $entry.Open()
                try {
                    $entrySha = Get-StreamSha256 -Stream $entryStream
                }
                finally {
                    $entryStream.Dispose()
                }
                if ($entrySha -ne [string]$file.sha256) {
                    return "package entry SHA-256 mismatch: $name"
                }
            }
        }
        finally {
            $zip.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
    return ""
}

$repoRoot = (Get-ImmoAppRepoRoot).Path
$runtimePaths = Get-ImmoAppRuntimePaths
$gitState = Get-GitState -RepoRoot $repoRoot
$outputRootWasExplicit = -not [string]::IsNullOrWhiteSpace($OutputRoot)
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $repoRoot (Join-Path ".tmp" (Join-Path "managed_hub_runtime_package" (Get-Date -Format "yyyyMMdd_HHmmss")))
}
$OutputRoot = Assert-ManagedRuntimePackageOutputRoot -Path $OutputRoot -RepoRoot $repoRoot -RuntimePaths $runtimePaths
$script:ManagedRuntimePackageOutputRoot = $OutputRoot
$packagePath = Join-Path $OutputRoot "$PackageName.zip"
$stagingPackagePath = Join-Path $OutputRoot "$PackageName.staging.zip"
if (Test-Path -LiteralPath $OutputRoot) {
    $existingEntries = @(Get-ChildItem -LiteralPath $OutputRoot -Force)
    if ($outputRootWasExplicit -and $existingEntries.Count -gt 0 -and -not $AllowReplaceOutputRoot) {
        throw "OutputRoot is not empty. Pass -AllowReplaceOutputRoot to replace managed-runtime package proof outputs safely: $OutputRoot"
    }
}
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
foreach ($stale in @($packagePath, $stagingPackagePath)) {
    if (Test-Path -LiteralPath $stale) {
        if (-not (Test-ImmoAppPathUnderRoot -Root $OutputRoot -Path $stale) -or -not (Test-ImmoAppResolvedPathUnderRoot -Root $OutputRoot -Path $stale)) {
            throw "managed_runtime_stale_package_cleanup_outside_output_root|Refusing to remove stale package outside OutputRoot: $stale"
        }
        Remove-Item -LiteralPath $stale -Force
    }
}

$inventoryPath = Join-Path $OutputRoot "managed_hub_runtime_package_inventory.json"
$sourceCommitOverride = -not [string]::IsNullOrWhiteSpace($SourceCommitSha)
$commitSha = if ($sourceCommitOverride) { $SourceCommitSha.Trim().ToLowerInvariant() } else { [string]$gitState.git_head_sha }
$runtimeSourceOrigin = ""
$dirtyFilesSummaryCount = 0
$sourceTreeClean = $false
$inventoryProofOnly = [bool]$AllowProofOnlyRuntime
$extractedInventorySha256 = ""
$vendorProvenancePath = ""
$vendorProvenanceSha256 = ""

if ([string]::IsNullOrWhiteSpace($RuntimeSourceRoot)) {
    $inventory = New-InventoryPayload `
        -CommitSha $commitSha `
        -ProofResult "NO-GO" `
        -ReasonCode "managed_runtime_artifact_missing" `
        -FailureReason "No hidden ImmoApp-managed runtime source was supplied. This package proof does not relabel Docker Desktop as managed." `
        -ProofOnly $inventoryProofOnly `
        -SourceTreeClean $sourceTreeClean `
        -SourceCommitOverride $sourceCommitOverride `
        -RuntimeSourceOrigin $runtimeSourceOrigin `
        -DirtyFilesSummaryCount $dirtyFilesSummaryCount `
        -GitState $gitState
    Write-Inventory -Path $inventoryPath -Payload $inventory
    exit 0
}

if (-not (Test-Path -LiteralPath $RuntimeSourceRoot)) {
    throw "RuntimeSourceRoot does not exist: $RuntimeSourceRoot"
}

$declaredSourceFull = [System.IO.Path]::GetFullPath($RuntimeSourceRoot)
if (Test-ImmoAppPathHasReparsePoint -Path $RuntimeSourceRoot) {
    $inventory = New-InventoryPayload `
        -CommitSha $commitSha `
        -ProofResult "NO-GO" `
        -ReasonCode "managed_runtime_source_root_reparse_point" `
        -FailureReason "RuntimeSourceRoot or one of its parents is a reparse point, symlink, or junction." `
        -RuntimeSourceRoot $declaredSourceFull `
        -ProofOnly $true `
        -SourceTreeClean $false `
        -SourceCommitOverride $sourceCommitOverride `
        -RuntimeSourceOrigin "" `
        -DirtyFilesSummaryCount 0 `
        -GitState $gitState
    Write-Inventory -Path $inventoryPath -Payload $inventory
    exit 1
}

$sourceRoot = (Resolve-Path -LiteralPath $RuntimeSourceRoot).Path
$sourceFull = [System.IO.Path]::GetFullPath($sourceRoot)
if (-not $sourceFull.Equals($declaredSourceFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    $inventory = New-InventoryPayload `
        -CommitSha $commitSha `
        -ProofResult "NO-GO" `
        -ReasonCode "managed_runtime_source_root_resolves_outside_declared_root" `
        -FailureReason "RuntimeSourceRoot resolves to a different location than the declared path." `
        -RuntimeSourceRoot $declaredSourceFull `
        -ProofOnly $true `
        -SourceTreeClean $false `
        -SourceCommitOverride $sourceCommitOverride `
        -RuntimeSourceOrigin "" `
        -DirtyFilesSummaryCount 0 `
        -GitState $gitState
    Write-Inventory -Path $inventoryPath -Payload $inventory
    exit 1
}
$repoFull = [System.IO.Path]::GetFullPath($repoRoot)
$sourceInsideRepo = Test-ImmoAppPathUnderRoot -Root $repoFull -Path $sourceFull
$runtimeSourceOrigin = if ($sourceInsideRepo) { "repo" } else { "external_artifact" }
$dirtyFilesSummaryCount = if ($sourceInsideRepo -and [bool]$gitState.dirty_state_verified) { [int]$gitState.dirty_file_count } else { 0 }
$sourceTreeClean = ($sourceInsideRepo -and [bool]$gitState.dirty_state_verified -and $dirtyFilesSummaryCount -eq 0)
$files = New-Object System.Collections.Generic.List[object]
$forbidden = New-Object System.Collections.Generic.List[object]
$entryNames = @{}

foreach ($item in Get-ChildItem -LiteralPath $sourceRoot -Recurse -Force) {
    $relative = Get-RelativeRuntimePackagePath -Root $sourceRoot -Path $item.FullName
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        $forbidden.Add([ordered]@{ path = $relative; reason = "reparse_points_not_supported" })
        continue
    }
    if ($item.PSIsContainer) { continue }
    $relative = Normalize-PackageRelativePath -Path $relative
    if (Test-UnsafeArchivePath -RelativePath $relative) {
        $forbidden.Add([ordered]@{ path = $relative; reason = "unsafe_archive_path" })
        continue
    }
    $mappedSource = Convert-PackagePathToSourcePath -Root $sourceRoot -RelativePath $relative
    if ([string]::IsNullOrWhiteSpace($mappedSource)) {
        $forbidden.Add([ordered]@{ path = $relative; reason = "managed_runtime_package_path_mapping_failed" })
        continue
    }
    $duplicateKey = $relative.ToLowerInvariant()
    if ($entryNames.ContainsKey($duplicateKey)) {
        $forbidden.Add([ordered]@{ path = $relative; reason = "duplicate_archive_entry" })
        continue
    }
    $entryNames[$duplicateKey] = $true
    $reason = Get-ForbiddenRuntimePackageReason -RelativePath $relative
    if ($reason) {
        $forbidden.Add([ordered]@{ path = $relative; reason = $reason })
    }
    if ($sourceInsideRepo -and -not (Test-GitTrackedSourceFile -RepoRoot $repoFull -Path $mappedSource)) {
        $forbidden.Add([ordered]@{ path = $relative; reason = "untracked_source_file" })
    }
    $files.Add([ordered]@{
        path = $relative
        bytes = [int64]$item.Length
        sha256 = Get-FileSha256 -Path $mappedSource
    })
}

$fileArray = @($files.ToArray() | Sort-Object { [string]$_.path })
try {
    $strictSourceInventory = Get-ImmoAppStrictRuntimeTreeInventory -Root $sourceRoot -RequireNonEmpty
    $extractedInventorySha256 = [string]$strictSourceInventory.sha256
    if (-not $sourceInsideRepo) {
        $sourceTreeClean = $true
    }
}
catch {
    $strictError = $_.Exception.Message
    $strictReason = "managed_runtime_tree_invalid"
    $strictPath = $sourceRoot
    if ($strictError -match "^(?<code>[a-z0-9_]+)\|(?<message>.*)$") {
        $strictReason = $Matches["code"]
        $strictPath = $Matches["message"]
    }
    $forbidden.Add([ordered]@{ path = $strictPath; reason = $strictReason })
    $extractedInventorySha256 = ""
}
$fileMap = @{}
foreach ($file in $fileArray) {
    $fileMap[[string]$file.path] = $file
}

$runtimeCritical = Normalize-PackageRelativePath -Path $RuntimeExecutableRelativePath
if ([string]::IsNullOrWhiteSpace($runtimeCritical)) {
    $candidate = @($fileArray | Where-Object { [System.IO.Path]::GetExtension([string]$_.path).ToLowerInvariant() -in @(".exe", ".cmd", ".bat") } | Select-Object -First 1)
    if ($candidate.Count -gt 0) {
        $runtimeCritical = [string]$candidate[0].path
    }
}
$composeCritical = Normalize-PackageRelativePath -Path $ComposeExecutableRelativePath
if ([string]::IsNullOrWhiteSpace($composeCritical)) {
    $composeCritical = $runtimeCritical
}
foreach ($critical in @(
    @{ path = $runtimeCritical; label = "runtime_executable_relative_path" },
    @{ path = $composeCritical; label = "compose_executable_relative_path" }
)) {
    if ([string]::IsNullOrWhiteSpace($critical.path) -or -not $fileMap.ContainsKey($critical.path)) {
        $forbidden.Add([ordered]@{ path = [string]$critical.path; reason = "missing_critical_executable:$($critical.label)" })
    }
}

$criticalExecutables = [ordered]@{
    runtime_executable_relative_path = $runtimeCritical
    compose_executable_relative_path = $composeCritical
}

$vendorProvenanceValid = $false
$vendorProvenanceFailureCode = ""
if (-not [string]::IsNullOrWhiteSpace($VendorProvenanceJson)) {
    try {
        $provenance = Assert-ImmoAppManagedRuntimeVendorProvenance `
            -ProvenancePath $VendorProvenanceJson `
            -ExpectedSourceCommitSha $commitSha `
            -ExpectedExtractedInventorySha256 $extractedInventorySha256 `
            -AllowNonCanonicalRoot:((-not (Test-ImmoAppUsingCanonicalRuntimeRoot)))
        $vendorProvenanceValid = $true
        $vendorProvenancePath = [string]$provenance.path
        $vendorProvenanceSha256 = [string]$provenance.sha256
    }
    catch {
        $vendorProvenanceFailureCode = "managed_runtime_vendor_provenance_invalid"
        if ($_.Exception.Message -match "^(?<code>[a-z0-9_]+)\|(?<message>.*)$") {
            $vendorProvenanceFailureCode = $Matches["code"]
        }
    }
}

$proofResult = "GO"
$reasonCode = "managed_runtime_package_built"
if ($sourceCommitOverride -and -not $AllowSourceCommitOverride) {
    $proofResult = "NO-GO"
    $reasonCode = "managed_runtime_source_commit_override_not_allowed"
}
elseif ($sourceCommitOverride -and $AllowSourceCommitOverride) {
    $proofResult = "NO-GO"
    $reasonCode = "managed_runtime_source_commit_override"
    $inventoryProofOnly = $true
}
elseif (-not (Test-LowerGitSha -Value $commitSha)) {
    $proofResult = "NO-GO"
    $reasonCode = "managed_runtime_missing_source_provenance"
}
elseif ($runtimeSourceOrigin -eq "repo" -and -not [bool]$gitState.dirty_state_verified) {
    $proofResult = "NO-GO"
    $reasonCode = if ([string]::IsNullOrWhiteSpace([string]$gitState.failure_reason)) { "managed_runtime_git_state_unverified" } else { [string]$gitState.failure_reason }
    if ($AllowDirtyRuntimePackageProof) {
        $inventoryProofOnly = $true
    }
}
elseif ($fileArray.Count -eq 0) {
    $proofResult = "NO-GO"
    $reasonCode = "managed_runtime_artifact_empty"
}
elseif ($forbidden.Count -gt 0) {
    $proofResult = "NO-GO"
    $mappingFailures = @($forbidden.ToArray() | Where-Object { [string]$_.reason -eq "managed_runtime_package_path_mapping_failed" })
    $reasonCode = if ($mappingFailures.Count -gt 0) { "managed_runtime_package_path_mapping_failed" } else { "forbidden_runtime_package_content" }
}
elseif ($runtimeSourceOrigin -eq "external_artifact" -and -not $AllowExternalRuntimeSource) {
    $proofResult = "NO-GO"
    $reasonCode = "managed_runtime_external_source_not_allowed"
}
elseif ($runtimeSourceOrigin -eq "external_artifact" -and $AllowExternalRuntimeSource -and [string]::IsNullOrWhiteSpace($VendorProvenanceJson)) {
    $proofResult = "NO-GO"
    $reasonCode = "managed_runtime_external_artifact_requires_vendor_provenance"
    $inventoryProofOnly = $true
}
elseif ($runtimeSourceOrigin -eq "external_artifact" -and $AllowExternalRuntimeSource -and -not $vendorProvenanceValid) {
    $proofResult = "NO-GO"
    $reasonCode = $vendorProvenanceFailureCode
    $inventoryProofOnly = $true
}
elseif ($runtimeSourceOrigin -eq "external_artifact" -and $AllowExternalRuntimeSource -and $vendorProvenanceValid) {
    if (-not (Test-ImmoAppUsingCanonicalRuntimeRoot)) {
        $inventoryProofOnly = $true
    }
}
elseif ($runtimeSourceOrigin -eq "repo" -and -not $sourceTreeClean -and -not $AllowDirtyRuntimePackageProof) {
    $proofResult = "NO-GO"
    $reasonCode = "managed_runtime_dirty_source_tree"
}
elseif ($runtimeSourceOrigin -eq "repo" -and -not $sourceTreeClean -and $AllowDirtyRuntimePackageProof) {
    $proofResult = "NO-GO"
    $reasonCode = "managed_runtime_dirty_source_tree_proof_only"
    $inventoryProofOnly = $true
}

$packageSha256 = ""
$packageBytes = 0L
if ($proofResult -eq "GO") {
    foreach ($stale in @($packagePath, $stagingPackagePath)) {
        if (Test-Path -LiteralPath $stale) {
            if (-not (Test-ImmoAppPathUnderRoot -Root $OutputRoot -Path $stale) -or -not (Test-ImmoAppResolvedPathUnderRoot -Root $OutputRoot -Path $stale)) {
                throw "managed_runtime_stale_package_cleanup_outside_output_root|Refusing to remove stale package outside OutputRoot: $stale"
            }
            Remove-Item -LiteralPath $stale -Force
        }
    }
    $packageStream = [System.IO.File]::Open($stagingPackagePath, [System.IO.FileMode]::CreateNew)
    try {
        $zip = [System.IO.Compression.ZipArchive]::new($packageStream, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            foreach ($entry in $fileArray) {
                $entryPath = [string]$entry.path
                $zipEntry = $zip.CreateEntry($entryPath, [System.IO.Compression.CompressionLevel]::Optimal)
                $entryStream = $zipEntry.Open()
                $sourceFile = Convert-PackagePathToSourcePath -Root $sourceRoot -RelativePath $entryPath
                if ([string]::IsNullOrWhiteSpace($sourceFile)) {
                    throw "Source file mapping failed during packaging: $entryPath"
                }
                $sourceStream = [System.IO.File]::OpenRead($sourceFile)
                try {
                    $sourceStream.CopyTo($entryStream)
                }
                finally {
                    $sourceStream.Dispose()
                    $entryStream.Dispose()
                }
            }
        }
        finally {
            $zip.Dispose()
        }
    }
    finally {
        $packageStream.Dispose()
    }

    $verificationError = Verify-ZipMatchesInventory -PackagePath $stagingPackagePath -Files $fileArray
    if ($verificationError) {
        $proofResult = "NO-GO"
        $reasonCode = "managed_runtime_package_verification_failed"
        $forbidden.Add([ordered]@{ path = $stagingPackagePath; reason = $verificationError })
        if (Test-Path -LiteralPath $stagingPackagePath) { Remove-Item -LiteralPath $stagingPackagePath -Force }
    }
    else {
        Move-Item -LiteralPath $stagingPackagePath -Destination $packagePath -Force
        $packageSha256 = Get-FileSha256 -Path $packagePath
        $packageBytes = [int64](Get-Item -LiteralPath $packagePath).Length
    }
}
else {
    foreach ($stale in @($packagePath, $stagingPackagePath)) {
        if (Test-Path -LiteralPath $stale) {
            if (-not (Test-ImmoAppPathUnderRoot -Root $OutputRoot -Path $stale) -or -not (Test-ImmoAppResolvedPathUnderRoot -Root $OutputRoot -Path $stale)) {
                throw "managed_runtime_stale_package_cleanup_outside_output_root|Refusing to remove stale package outside OutputRoot: $stale"
            }
            Remove-Item -LiteralPath $stale -Force
        }
    }
}

$inventoryFailureReason = ""
if ($proofResult -ne "GO") {
    $inventoryFailureReason = $reasonCode
}
$inventoryPackagePath = ""
if ($proofResult -eq "GO" -and (Test-Path -LiteralPath $packagePath)) {
    $inventoryPackagePath = $packagePath
}

$inventory = New-InventoryPayload `
    -CommitSha $commitSha `
    -ProofResult $proofResult `
    -ReasonCode $reasonCode `
    -FailureReason $inventoryFailureReason `
    -RuntimeSourceRoot $sourceRoot `
    -PackagePath $inventoryPackagePath `
    -PackageSha256 $packageSha256 `
    -PackageBytes $packageBytes `
    -Files $fileArray `
    -ForbiddenMatches @($forbidden.ToArray()) `
    -CriticalExecutables $criticalExecutables `
    -ProofOnly $inventoryProofOnly `
    -SourceTreeClean $sourceTreeClean `
    -SourceCommitOverride $sourceCommitOverride `
    -RuntimeSourceOrigin $runtimeSourceOrigin `
    -DirtyFilesSummaryCount $dirtyFilesSummaryCount `
    -ExtractedInventorySha256 $extractedInventorySha256 `
    -VendorProvenancePath $vendorProvenancePath `
    -VendorProvenanceSha256 $vendorProvenanceSha256 `
    -GitState $gitState
Write-Inventory -Path $inventoryPath -Payload $inventory
if ($proofResult -ne "GO" -and $forbidden.Count -gt 0) {
    exit 1
}
