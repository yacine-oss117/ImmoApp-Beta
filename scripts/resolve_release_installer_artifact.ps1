param(
    [string]$CommitSha = "",
    [string]$ArtifactRoot = "",
    [string]$ReleaseRoot = "C:\ProgramData\ImmoApp\release_artifacts\desktop_installer",
    [string]$OutputJson = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

function Get-ResolverFullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-ResolverPathUnderRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-ImmoAppPathUnderRoot -Root $Root -Path $Path)) {
        throw "$Label path is outside expected root: $(Get-ResolverFullPath -Path $Path)"
    }
}

function Get-ArtifactFailure {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ReasonCode,
        [Parameter(Mandatory = $true)][string]$Reason
    )
    return [ordered]@{
        artifact_root = (Get-ResolverFullPath -Path $Path)
        status = "NO-GO"
        reason_code = $ReasonCode
        reason = $Reason
    }
}

function Assert-LowerSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Value -cnotmatch "^[0-9a-f]{64}$") {
        throw "$Label must be lowercase SHA-256."
    }
}

function Test-ArtifactRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$ExpectedCommitSha = ""
    )
    $full = Get-ResolverFullPath -Path $Path
    if (-not (Test-Path -LiteralPath $full -PathType Container)) {
        return Get-ArtifactFailure -Path $full -ReasonCode "release_artifact_root_missing" -Reason "Artifact root does not exist."
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $full) {
        return Get-ArtifactFailure -Path $full -ReasonCode "release_artifact_root_reparse_point" -Reason "Artifact root contains a reparse point, symlink, or junction."
    }

    $installerFiles = @(Get-ChildItem -LiteralPath $full -File -Filter "*-Setup.exe")
    $summaryFiles = @(Get-ChildItem -LiteralPath $full -File -Filter "*.summary.json")
    $inventoryFiles = @(Get-ChildItem -LiteralPath $full -File -Filter "*.bundle_inventory.json")
    if ($installerFiles.Count -ne 1) {
        return Get-ArtifactFailure -Path $full -ReasonCode "release_artifact_installer_missing_or_ambiguous" -Reason "Artifact root must contain exactly one installer EXE."
    }
    if ($summaryFiles.Count -ne 1) {
        return Get-ArtifactFailure -Path $full -ReasonCode "release_artifact_summary_missing_or_ambiguous" -Reason "Artifact root must contain exactly one build summary JSON."
    }
    if ($inventoryFiles.Count -ne 1) {
        return Get-ArtifactFailure -Path $full -ReasonCode "release_artifact_inventory_missing_or_ambiguous" -Reason "Artifact root must contain exactly one bundle inventory JSON."
    }

    try {
        $installerPath = (Resolve-Path -LiteralPath $installerFiles[0].FullName).Path
        $summaryPath = (Resolve-Path -LiteralPath $summaryFiles[0].FullName).Path
        $inventoryPath = (Resolve-Path -LiteralPath $inventoryFiles[0].FullName).Path
        foreach ($entry in @(
                @{ Label = "installer"; Path = $installerPath },
                @{ Label = "summary"; Path = $summaryPath },
                @{ Label = "inventory"; Path = $inventoryPath }
            )) {
            Assert-ResolverPathUnderRoot -Root $full -Path $entry.Path -Label $entry.Label
            if (Test-ImmoAppPathHasReparsePoint -Path $entry.Path) {
                throw "$($entry.Label) path contains a reparse point, symlink, or junction."
            }
        }

        $summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
        $inventory = Get-Content -LiteralPath $inventoryPath -Raw | ConvertFrom-Json
        if ([string]$summary.kind -ne "immoapp_desktop_installer_build_summary") { throw "Build summary has wrong kind." }
        if ([string]$inventory.kind -ne "immoapp_installer_package_inventory") { throw "Bundle inventory has wrong kind." }
        if ($ExpectedCommitSha -and [string]$summary.source_commit_sha -ne $ExpectedCommitSha) { throw "Build summary source_commit_sha does not match expected commit." }
        if ($ExpectedCommitSha -and [string]$inventory.source_commit_sha -ne $ExpectedCommitSha) { throw "Bundle inventory source_commit_sha does not match expected commit." }

        $summaryInstallerPath = [string]$summary.installer_path
        $summaryInventoryPath = [string]$summary.bundle_inventory_path
        if ((Get-ResolverFullPath -Path $summaryInstallerPath) -ne $installerPath) { throw "Build summary installer_path does not match selected artifact installer." }
        if ((Get-ResolverFullPath -Path $summaryInventoryPath) -ne $inventoryPath) { throw "Build summary bundle_inventory_path does not match selected artifact inventory." }
        if ([string]$summary.package_inventory_path -ne [string]$summary.bundle_inventory_path) { throw "Build summary package_inventory_path must match bundle_inventory_path." }

        $actualInstallerSha = Get-ImmoAppFileSha256 -Path $installerPath
        $summaryInstallerSha = ([string]$summary.installer_sha256).ToLowerInvariant()
        Assert-LowerSha256 -Value $summaryInstallerSha -Label "Build summary installer_sha256"
        if ($actualInstallerSha -ne $summaryInstallerSha) { throw "Build summary installer_sha256 does not match actual installer hash." }

        $actualInventorySha = Get-ImmoAppFileSha256 -Path $inventoryPath
        $summaryInventorySha = ([string]$summary.bundle_inventory_sha256).ToLowerInvariant()
        Assert-LowerSha256 -Value $summaryInventorySha -Label "Build summary bundle_inventory_sha256"
        if ($actualInventorySha -ne $summaryInventorySha) { throw "Build summary bundle_inventory_sha256 does not match actual inventory hash." }
        if (([string]$summary.package_inventory_sha256).ToLowerInvariant() -ne $summaryInventorySha) { throw "Build summary package_inventory_sha256 must match bundle_inventory_sha256." }

        if ([string]$inventory.proof_result -ne "GO") { throw "Bundle inventory proof_result must be GO." }
        if (@($inventory.forbidden_path_matches).Count -gt 0 -or @($inventory.detected_forbidden_paths).Count -gt 0) { throw "Bundle inventory contains forbidden path matches." }
        if (@($inventory.missing_required_file_checks).Count -gt 0) { throw "Bundle inventory contains missing required file checks." }
        $hubManagerFile = @($inventory.files | Where-Object { [string]$_.relative_path -eq "ImmoApp Hub Manager.exe" })
        if ($hubManagerFile.Count -ne 1) { throw "Bundle inventory must contain ImmoApp Hub Manager.exe exactly once." }
        $hubManagerRequired = @($inventory.required_file_checks | Where-Object { [string]$_.relative_path -eq "ImmoApp Hub Manager.exe" -and (($_.present -eq $true) -or ([string]$_.present).ToLowerInvariant() -eq "true") })
        if ($hubManagerRequired.Count -ne 1) { throw "Bundle inventory must require ImmoApp Hub Manager.exe." }

        return [ordered]@{
            artifact_root = $full
            status = "GO"
            reason_code = "release_artifact_selected"
            installer_path = $installerPath
            installer_sha256 = $actualInstallerSha
            summary_path = $summaryPath
            summary_sha256 = Get-ImmoAppFileSha256 -Path $summaryPath
            bundle_inventory_path = $inventoryPath
            bundle_inventory_sha256 = $actualInventorySha
            source_commit_sha = [string]$summary.source_commit_sha
            hub_manager_packaged_status = "GO"
            package_inventory_proof_result = [string]$inventory.proof_result
            forbidden_path_count = @($inventory.forbidden_path_matches).Count + @($inventory.detected_forbidden_paths).Count
            missing_required_file_count = @($inventory.missing_required_file_checks).Count
        }
    }
    catch {
        return Get-ArtifactFailure -Path $full -ReasonCode "release_artifact_invalid" -Reason $_.Exception.Message
    }
}

if ([string]::IsNullOrWhiteSpace($ArtifactRoot) -and [string]::IsNullOrWhiteSpace($CommitSha)) {
    throw "Provide -ArtifactRoot or -CommitSha."
}

$releaseRootFull = Get-ResolverFullPath -Path $ReleaseRoot
$expectedCommit = ""
if ($CommitSha) {
    $expectedCommit = $CommitSha.Trim()
    if ($expectedCommit.Length -lt 12) { throw "CommitSha must be at least 12 characters." }
}

$candidates = if ($ArtifactRoot) {
    @((Get-ResolverFullPath -Path $ArtifactRoot))
}
else {
    if (-not (Test-Path -LiteralPath $releaseRootFull -PathType Container)) {
        throw "ReleaseRoot does not exist: $releaseRootFull"
    }
    $prefix = $expectedCommit.Substring(0, 12)
    @(Get-ChildItem -LiteralPath $releaseRootFull -Directory | Where-Object { $_.Name -like "$prefix*" } | ForEach-Object { $_.FullName })
}
$candidates = @($candidates)

if ($candidates.Count -eq 0) { throw "No artifact candidates found." }
$results = @($candidates | ForEach-Object { Test-ArtifactRoot -Path $_ -ExpectedCommitSha $expectedCommit })
$valid = @($results | Where-Object { [string]$_.status -eq "GO" })
if ($valid.Count -ne 1) {
    $payload = [ordered]@{
        kind = "immoapp_release_installer_artifact_resolution"
        schema_version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        proof_result = "NO-GO"
        reason_code = if ($valid.Count -eq 0) { "release_artifact_no_valid_candidate" } else { "release_artifact_ambiguous_valid_candidates" }
        expected_commit_sha = $expectedCommit
        release_root = $releaseRootFull
        candidates = @($results)
    }
    if ($OutputJson) {
        Write-ImmoAppSafeJson -Path $OutputJson -Payload $payload -ApprovedRoots @($releaseRootFull, (Join-Path (Get-ImmoAppRepoRoot) ".tmp")) | Out-Null
    }
    $payload | ConvertTo-Json -Depth 8
    exit 1
}

$selected = $valid[0]
$payload = [ordered]@{
    kind = "immoapp_release_installer_artifact_resolution"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    proof_result = "GO"
    reason_code = "release_artifact_selected"
    expected_commit_sha = $expectedCommit
    release_root = $releaseRootFull
    selected_artifact = $selected
    candidates = @($results)
}
if ($OutputJson) {
    Write-ImmoAppSafeJson -Path $OutputJson -Payload $payload -ApprovedRoots @($releaseRootFull, (Join-Path (Get-ImmoAppRepoRoot) ".tmp")) | Out-Null
}
$payload | ConvertTo-Json -Depth 8
