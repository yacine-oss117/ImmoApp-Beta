[CmdletBinding()]
param(
    [string]$OutputArchivePath = "",
    [string]$OutputJson = "",
    [string]$SourceCommitSha = "",
    [string]$DockerExe = "docker",
    [string]$AppImageTag = "immoapp-server:local",
    [switch]$BuildAppImage,
    [switch]$AllowTestOnlyPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

function Invoke-ImageBundleDocker {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $dockerCommand = Get-Command -Name $DockerExe -CommandType Application -ErrorAction SilentlyContinue
    if ($null -eq $dockerCommand -and (Test-Path -LiteralPath $DockerExe -PathType Leaf)) {
        $dockerCommand = Get-Item -LiteralPath $DockerExe
    }
    if ($null -eq $dockerCommand) {
        throw "$Label failed because Docker executable '$DockerExe' was not found."
    }

    $previousErrorActionPreference = $ErrorActionPreference
    $output = @()
    $exitCode = 1
    try {
        $ErrorActionPreference = "Continue"
        $output = & $DockerExe @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $outputText = (($output | ForEach-Object { [string]$_ }) | Out-String).Trim()
    if ($exitCode -ne 0) {
        throw "$Label failed with exit code $exitCode. $outputText"
    }
    return $outputText
}

function Get-ImageRepoDigest {
    param([Parameter(Mandatory = $true)][string]$Image)
    try {
        $digestJson = Invoke-ImageBundleDocker -Arguments @(
            "image",
            "inspect",
            $Image,
            "--format",
            "{{json .RepoDigests}}"
        ) -Label "docker image inspect digest"
        if ([string]::IsNullOrWhiteSpace($digestJson) -or $digestJson.Trim() -eq "null") {
            return ""
        }
        $convertedDigests = $digestJson | ConvertFrom-Json
        if ($null -eq $convertedDigests) {
            return ""
        }
        $digests = if ($convertedDigests -is [System.Array]) {
            @($convertedDigests | ForEach-Object { [string]$_ })
        }
        else {
            @([string]$convertedDigests)
        }
        if ($digests.Count -eq 0) {
            return ""
        }
        $repo = $Image
        if ($repo.Contains("@")) {
            $repo = $repo.Substring(0, $repo.LastIndexOf("@"))
        }
        else {
            $lastSlash = $repo.LastIndexOf("/")
            $lastColon = $repo.LastIndexOf(":")
            if ($lastColon -gt $lastSlash) {
                $repo = $repo.Substring(0, $lastColon)
            }
        }
        $matchingDigest = @($digests | Where-Object { [string]$_ -like "$repo@sha256:*" }) | Select-Object -First 1
        if ($null -ne $matchingDigest) {
            return [string]$matchingDigest
        }
        return [string]($digests | Select-Object -First 1)
    }
    catch {
        return ""
    }
}

function Assert-ImageExists {
    param([Parameter(Mandatory = $true)][string]$Image)
    Invoke-ImageBundleDocker -Arguments @("image", "inspect", $Image) -Label "docker image inspect $Image" | Out-Null
}

function Get-ImageLabel {
    param(
        [Parameter(Mandatory = $true)][string]$Image,
        [Parameter(Mandatory = $true)][string]$LabelName
    )
    $labelsJson = [string](Invoke-ImageBundleDocker -Arguments @(
            "image",
            "inspect",
            $Image,
            "--format",
            "{{json .Config.Labels}}"
        ) -Label "docker image inspect label $Image")
    if ([string]::IsNullOrWhiteSpace($labelsJson) -or $labelsJson.Trim() -eq "null") {
        return ""
    }
    try {
        $labels = $labelsJson | ConvertFrom-Json
    }
    catch {
        throw "Unable to parse Docker image labels for '$Image'. $([string]$_.Exception.Message)"
    }
    $property = $labels.PSObject.Properties[$LabelName]
    if ($null -eq $property) {
        return ""
    }
    return [string]$property.Value
}

function Assert-AppImageRevision {
    param(
        [Parameter(Mandatory = $true)][string]$Image,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceCommitSha,
        [Parameter(Mandatory = $true)][string]$LabelName
    )
    $revision = ""
    try {
        $revision = (Get-ImageLabel -Image $Image -LabelName $LabelName).Trim().ToLowerInvariant()
    }
    catch {
        throw "managed_runtime_app_image_commit_mismatch|Unable to verify app image source commit label '$LabelName' on '$Image'. $([string]$_.Exception.Message)"
    }
    if ([string]::IsNullOrWhiteSpace($revision) -or $revision -ne $ExpectedSourceCommitSha) {
        throw "managed_runtime_app_image_commit_mismatch|App image '$Image' source commit label '$LabelName' is missing or mismatched."
    }
    return $revision
}

function Get-RequiredManagedImages {
    param([Parameter(Mandatory = $true)][string]$AppImage)
    return @(
        [ordered]@{ service = "rabbitmq-init"; source = "busybox:1.36"; tag = "immoapp-managed/busybox:1.36" },
        [ordered]@{ service = "app-data-init"; source = "busybox:1.36"; tag = "immoapp-managed/busybox:1.36" },
        [ordered]@{ service = "db"; source = "postgis/postgis:18-3.6"; tag = "immoapp-managed/postgis:18-3.6" },
        [ordered]@{ service = "rabbitmq"; source = "rabbitmq:3.13-management"; tag = "immoapp-managed/rabbitmq:3.13-management" },
        [ordered]@{ service = "valkey"; source = "valkey/valkey:9.0.1"; tag = "immoapp-managed/valkey:9.0.1" },
        [ordered]@{ service = "openbao"; source = "openbao/openbao:2.3.1"; tag = "immoapp-managed/openbao:2.3.1" },
        [ordered]@{ service = "minio"; source = "minio/minio:RELEASE.2025-09-07T16-13-09Z"; tag = "immoapp-managed/minio:RELEASE.2025-09-07T16-13-09Z" },
        [ordered]@{ service = "minio-init"; source = "minio/mc:RELEASE.2025-08-13T08-35-41Z"; tag = "immoapp-managed/minio-mc:RELEASE.2025-08-13T08-35-41Z" },
        [ordered]@{ service = "clamav"; source = "clamav/clamav:1.4.3"; tag = "immoapp-managed/clamav:1.4.3" },
        [ordered]@{ service = "web"; source = $AppImage; tag = "immoapp-managed/server:local" },
        [ordered]@{ service = "worker"; source = $AppImage; tag = "immoapp-managed/server:local" },
        [ordered]@{ service = "worker-import"; source = $AppImage; tag = "immoapp-managed/server:local" },
        [ordered]@{ service = "worker-rebuild"; source = $AppImage; tag = "immoapp-managed/server:local" },
        [ordered]@{ service = "worker-match"; source = $AppImage; tag = "immoapp-managed/server:local" },
        [ordered]@{ service = "beat"; source = $AppImage; tag = "immoapp-managed/server:local" },
        [ordered]@{ service = "caddy"; source = "caddy:2.9.1"; tag = "immoapp-managed/caddy:2.9.1" }
    )
}

$paths = Ensure-ImmoAppRuntimeLayout
$canonicalPaths = Get-ImmoAppCanonicalRuntimePaths
if ([string]::IsNullOrWhiteSpace($OutputArchivePath)) {
    $OutputArchivePath = Join-Path $paths.RuntimeRoot "images\immoapp-runtime-images.tar"
}
if ([string]::IsNullOrWhiteSpace($OutputJson)) {
    $OutputJson = Join-Path $paths.ConfigRoot "managed_wsl2_runtime_image_bundle_inventory.json"
}
if ([string]::IsNullOrWhiteSpace($SourceCommitSha)) {
    try {
        $SourceCommitSha = (& git -C (Get-ImmoAppRepoRoot).Path rev-parse HEAD 2>$null | Out-String).Trim().ToLowerInvariant()
    }
    catch {
        $SourceCommitSha = ""
    }
}
$SourceCommitSha = $SourceCommitSha.Trim().ToLowerInvariant()
Assert-ImmoAppLowerGitSha -Value $SourceCommitSha -Name "source_commit_sha"
$appImageRevisionLabel = "org.opencontainers.image.revision"

$archiveFull = [System.IO.Path]::GetFullPath($OutputArchivePath)
$inventoryFull = [System.IO.Path]::GetFullPath($OutputJson)
$archiveWslPath = ""
$inventoryWslPath = ""
try {
    $archiveWslPath = Convert-ImmoAppManagedWsl2CanonicalHostPathToWslPath -Path $archiveFull
    $inventoryWslPath = Convert-ImmoAppManagedWsl2CanonicalHostPathToWslPath -Path $inventoryFull
}
catch {
    if (-not $AllowTestOnlyPath.IsPresent) { throw }
}
$runtimeRoots = if ($AllowTestOnlyPath) {
    Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "runtime"
} else {
    @($canonicalPaths.RuntimeRoot)
}
$configRoots = if ($AllowTestOnlyPath) {
    Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "config"
} else {
    @($canonicalPaths.ConfigRoot)
}
Assert-ImmoAppProofOnlyPathApproved -Path $archiveFull -Roots $runtimeRoots -Label "OutputArchivePath"
Assert-ImmoAppProofOnlyPathApproved -Path $inventoryFull -Roots $configRoots -Label "OutputJson"

$createdAt = (Get-Date).ToUniversalTime().ToString("o")
$proofResult = "NO-GO"
$reasonCode = "managed_runtime_image_bundle_build_failed"
$failure = ""
$imageEntries = @()
$archiveSha = ""
$archiveBytes = 0L
$appImageRevision = ""
$appImageRevisionVerified = $false

try {
    if ($BuildAppImage.IsPresent) {
        Invoke-ImageBundleDocker -Arguments @(
            "build",
            "--build-arg",
            "IMMOAPP_SOURCE_COMMIT_SHA=$SourceCommitSha",
            "--label",
            "$appImageRevisionLabel=$SourceCommitSha",
            "-t",
            $AppImageTag,
            "-f",
            (Join-Path (Get-ImmoAppRepoRoot).Path "deployment\docker\Dockerfile"),
            (Get-ImmoAppRepoRoot).Path
        ) -Label "docker build app image" | Out-Null
    }
    $appImageRevision = Assert-AppImageRevision `
        -Image $AppImageTag `
        -ExpectedSourceCommitSha $SourceCommitSha `
        -LabelName $appImageRevisionLabel
    $appImageRevisionVerified = $true

    $specs = @(Get-RequiredManagedImages -AppImage $AppImageTag)
    $unpinned = @($specs | Where-Object { [string]$_.source -match "(:latest$|/latest$)" })
    if ($unpinned.Count -gt 0) {
        throw "managed_runtime_image_source_not_pinned|Image bundle source images must not use latest: $(@($unpinned | ForEach-Object { [string]$_.source }) -join ', ')"
    }
    foreach ($spec in $specs) {
        Assert-ImageExists -Image ([string]$spec.source)
        if ([string]$spec.source -ne [string]$spec.tag) {
            Invoke-ImageBundleDocker -Arguments @("image", "tag", [string]$spec.source, [string]$spec.tag) -Label "docker image tag $($spec.source)" | Out-Null
        }
    }

    $uniqueTags = @($specs | ForEach-Object { [string]$_.tag } | Select-Object -Unique)
    $archiveParent = Split-Path -Parent $archiveFull
    if (-not (Test-Path -LiteralPath $archiveParent)) {
        [System.IO.Directory]::CreateDirectory($archiveParent) | Out-Null
    }
    Invoke-ImageBundleDocker -Arguments (@("save", "-o", $archiveFull) + $uniqueTags) -Label "docker save managed runtime images" | Out-Null
    if (-not (Test-Path -LiteralPath $archiveFull -PathType Leaf)) {
        throw "managed_runtime_image_archive_missing|docker save did not create the image archive."
    }
    $archiveSha = Get-ImmoAppFileSha256 -Path $archiveFull
    $archiveBytes = [int64](Get-Item -LiteralPath $archiveFull).Length

    foreach ($spec in $specs) {
        $imageEntries += [ordered]@{
            service = [string]$spec.service
            source_image = [string]$spec.source
            tag = [string]$spec.tag
            repo_digest = Get-ImageRepoDigest -Image ([string]$spec.tag)
        }
    }
    $proofResult = "GO"
    $reasonCode = "managed_runtime_image_bundle_built"
}
catch {
    $failure = [string]$_.Exception.Message
    if ($failure -match "^(?<code>[a-z0-9_]+)\|") {
        $reasonCode = $Matches["code"]
    }
}

$payload = [ordered]@{
    kind = "immoapp_managed_wsl2_runtime_image_bundle_inventory"
    schema_version = 1
    created_at_utc = $createdAt
    source_commit_sha = $SourceCommitSha
    app_image_source_commit_sha = $appImageRevision
    app_image_revision_label = $appImageRevisionLabel
    app_image_revision_verified = $appImageRevisionVerified
    image_archive_path = $archiveFull
    image_archive_host_path = $archiveFull
    image_archive_wsl_path = $archiveWslPath
    image_archive_sha256 = $archiveSha
    image_archive_bytes = $archiveBytes
    image_bundle_inventory_host_path = $inventoryFull
    image_bundle_inventory_wsl_path = $inventoryWslPath
    image_count = @($imageEntries).Count
    images = @($imageEntries)
    docker_save_invoked = ($proofResult -eq "GO")
    docker_pull_invoked = $false
    package_manager_install_invoked = $false
    compose_pull_policy_required = "never"
    proof_result = $proofResult
    reason_code = $reasonCode
    failure_reason = $failure
    agency_install_status = "NO_GO"
    public_beta_status = "NO_GO"
}

$write = Write-ImmoAppSafeJson -Path $inventoryFull -Payload $payload -ApprovedRoots $configRoots -Depth 12
$payload["inventory_path"] = $inventoryFull
$payload["inventory_sha256"] = [string]$write.sha256
$payload | ConvertTo-Json -Depth 12
if ($proofResult -ne "GO") { exit 1 }
exit 0
