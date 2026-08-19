[CmdletBinding()]
param(
    [string]$BaseRootfsTarPath = "",
    [string]$OutputRootfsTarPath = "",
    [string]$OutputJson = "",
    [string]$RuntimeVersion = "0.1.0",
    [string]$SourceCommitSha = "",
    [switch]$AllowReplaceOutputRootfs,
    [switch]$AllowTestOnlyPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

function Test-RootfsBuildPathParentHasReparsePoint {
    param([Parameter(Mandatory = $true)][string]$Path)
    $current = [System.IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        if (Test-Path -LiteralPath $current) {
            return (Test-ImmoAppPathHasReparsePoint -Path $current)
        }
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) { break }
        $current = $parent
    }
    return $false
}

function Resolve-RootfsBuildExistingFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "$Label missing."
    }
    $full = [System.IO.Path]::GetFullPath($Path)
    if (Test-RootfsBuildPathParentHasReparsePoint -Path $full) {
        throw "$Label contains a reparse point, symlink, or junction."
    }
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        throw "$Label must exist as a local file."
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $full) {
        throw "$Label contains a reparse point, symlink, or junction."
    }
    return $full
}

function Resolve-ImmoAppPython {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:PYTHON)) {
        $candidates += [string]$env:PYTHON
    }
    $candidates += @(
        (Join-Path (Get-ImmoAppCanonicalRuntimePaths).VenvsRoot "immoapp-server-py314\Scripts\python.exe"),
        "python.exe",
        "python"
    )
    foreach ($candidate in $candidates) {
        try {
            $output = & $candidate -c "import tarfile, sys; print(sys.version_info[0])" 2>$null
            if ($LASTEXITCODE -eq 0 -and ([string]$output).Trim() -eq "3") {
                return $candidate
            }
        }
        catch {
            continue
        }
    }
    throw "managed_wsl2_rootfs_python_missing|Python 3 with tarfile is required to build the ImmoAppRuntime rootfs overlay."
}

$paths = Ensure-ImmoAppRuntimeLayout
$canonicalPaths = Get-ImmoAppCanonicalRuntimePaths
if ([string]::IsNullOrWhiteSpace($OutputRootfsTarPath)) {
    $OutputRootfsTarPath = Get-ImmoAppManagedWsl2RootfsTarPath
}
if ([string]::IsNullOrWhiteSpace($OutputJson)) {
    $OutputJson = Get-ImmoAppManagedWsl2RootfsInventoryPath
}
if ([string]::IsNullOrWhiteSpace($SourceCommitSha)) {
    try {
        $SourceCommitSha = (& git -C (Get-ImmoAppRepoRoot).Path rev-parse HEAD 2>$null | Out-String).Trim().ToLowerInvariant()
    }
    catch {
        $SourceCommitSha = ""
    }
}
if (-not $AllowTestOnlyPath.IsPresent) {
    $repoRoot = (Get-ImmoAppRepoRoot).Path
    $gitStatus = @(& git -C $repoRoot status --short 2>$null)
    if ($LASTEXITCODE -ne 0) {
        throw "managed_wsl2_runtime_rootfs_git_status_failed|Unable to verify the rootfs source worktree."
    }
    if ($gitStatus.Count -gt 0) {
        throw "managed_wsl2_runtime_rootfs_dirty_source|Refusing to build a release rootfs from a dirty worktree."
    }
    $headSha = (& git -C $repoRoot rev-parse HEAD 2>$null | Out-String).Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($headSha)) {
        throw "managed_wsl2_runtime_rootfs_git_head_failed|Unable to resolve the rootfs source commit."
    }
    if ($SourceCommitSha.Trim().ToLowerInvariant() -cne $headSha) {
        throw "managed_wsl2_runtime_rootfs_source_commit_mismatch|SourceCommitSha must match clean HEAD."
    }
}

$runtimeRoots = if ($AllowTestOnlyPath) {
    Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "runtime"
} else {
    @($canonicalPaths.RuntimeRoot)
}
$outputRoots = @()
$outputRoots += Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "config"
$outputRoots += Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "runtime"
$outputRoots = @($outputRoots | Select-Object -Unique)

$createdAt = (Get-Date).ToUniversalTime().ToString("o")
$baseFull = ""
$baseSha = ""
$outputFull = [System.IO.Path]::GetFullPath($OutputRootfsTarPath)
$pendingOutputFull = ""
$outputSha = ""
$proofResult = "NO-GO"
$reasonCode = "managed_wsl2_runtime_rootfs_build_failed"
$failure = ""
$buildMethod = "direct_tar_overlay"
$archiveValidationStatus = "NO-GO"
$archiveEntryCount = 0
$sparseFilesExpanded = 0
$requiredEntries = @(
    "opt/immoapp/runtime/bin/immoapp-runtime-identity",
    "opt/immoapp/runtime/bin/start-managed-hub",
    "opt/immoapp/runtime/bin/status-managed-hub",
    "opt/immoapp/runtime/bin/health-managed-hub",
    "opt/immoapp/runtime/bin/logs-managed-hub",
    "opt/immoapp/runtime/bin/backup-managed-hub",
    "opt/immoapp/runtime/bin/stop-managed-hub",
    "opt/immoapp/runtime/bin/restart-managed-hub",
    "opt/immoapp/runtime/bin/keepalive-managed-hub",
    "opt/immoapp/runtime/compose/compose.yaml"
)

try {
    if ([string]::IsNullOrWhiteSpace($BaseRootfsTarPath)) {
        throw "managed_wsl2_base_rootfs_tar_path_required|BaseRootfsTarPath is required; no distro rootfs is downloaded or inferred."
    }
    $baseFull = Resolve-RootfsBuildExistingFile -Path $BaseRootfsTarPath -Label "BaseRootfsTarPath"
    $baseSha = Get-ImmoAppFileSha256 -Path $baseFull
    Assert-ImmoAppProofOnlyPathApproved -Path $outputFull -Roots $runtimeRoots -Label "OutputRootfsTarPath"
    if (Test-RootfsBuildPathParentHasReparsePoint -Path $outputFull) {
        throw "managed_wsl2_runtime_rootfs_output_reparse_point|OutputRootfsTarPath parent contains a reparse point, symlink, or junction."
    }
    if ((Test-Path -LiteralPath $outputFull) -and -not $AllowReplaceOutputRootfs.IsPresent) {
        throw "managed_wsl2_runtime_rootfs_output_exists_requires_replace|OutputRootfsTarPath already exists; replacement requires AllowReplaceOutputRootfs."
    }
    $parent = Split-Path -Parent $outputFull
    if (-not (Test-Path -LiteralPath $parent)) {
        [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $parent) {
        throw "managed_wsl2_runtime_rootfs_output_reparse_point|OutputRootfsTarPath parent contains a reparse point after creation."
    }
    $pendingOutputFull = Join-Path $parent ((Split-Path -Leaf $outputFull) + ".pending-" + [Guid]::NewGuid().ToString("N"))
    Assert-ImmoAppProofOnlyPathApproved -Path $pendingOutputFull -Roots $runtimeRoots -Label "PendingOutputRootfsTarPath"
    $templateRoot = Join-Path (Get-ImmoAppRepoRoot).Path "deployment\managed-runtime"
    if (-not (Test-Path -LiteralPath $templateRoot -PathType Container)) {
        throw "managed_wsl2_runtime_template_missing|Managed runtime template root is missing."
    }
    $python = Resolve-ImmoAppPython
    $builder = @'
import io
import json
import pathlib
import sys
import tarfile
import time

base_path, output_path, runtime_version, source_commit, template_root = sys.argv[1:6]
template_root_path = pathlib.Path(template_root)
required = [
    "opt/immoapp/runtime/bin/immoapp-runtime-identity",
    "opt/immoapp/runtime/bin/start-managed-hub",
    "opt/immoapp/runtime/bin/status-managed-hub",
    "opt/immoapp/runtime/bin/health-managed-hub",
    "opt/immoapp/runtime/bin/logs-managed-hub",
    "opt/immoapp/runtime/bin/backup-managed-hub",
    "opt/immoapp/runtime/bin/stop-managed-hub",
    "opt/immoapp/runtime/bin/restart-managed-hub",
    "opt/immoapp/runtime/bin/keepalive-managed-hub",
    "opt/immoapp/runtime/compose/compose.yaml",
]
overlay = {}
metadata = {
    "kind": "immoapp_managed_wsl2_runtime_metadata",
    "schema_version": 1,
    "runtime_name": "ImmoAppRuntime",
    "runtime_version": runtime_version,
    "runtime_root": "/opt/immoapp/runtime",
    "source_commit_sha": source_commit,
    "proof_scope": "internal_managed_wsl2_runtime",
    "agency_install_status": "NO_GO",
}
overlay["opt/immoapp/runtime/runtime-metadata.json"] = json.dumps(metadata, sort_keys=True).encode("utf-8") + b"\n"
for source in sorted(template_root_path.rglob("*")):
    if not source.is_file():
        continue
    relative = source.relative_to(template_root_path).as_posix()
    if relative.startswith("../") or "/../" in relative or relative.startswith("/"):
        raise SystemExit("managed_wsl2_runtime_template_unsafe_entry")
    target = "opt/immoapp/runtime/" + relative
    data = source.read_bytes()
    if source.name in {"immoapp-runtime-identity"}:
        data = data.replace(b"__IMMOAPP_RUNTIME_VERSION__", runtime_version.encode("utf-8"))
        data = data.replace(b"__IMMOAPP_SOURCE_COMMIT_SHA__", source_commit.encode("utf-8"))
    overlay[target] = data
skip = set(overlay)
safe_seen = set()
sparse_files_expanded = 0
with tarfile.open(base_path, "r:*") as src, tarfile.open(output_path, "w") as dst:
    for member in src:
        name = member.name.replace("\\\\", "/").lstrip("/")
        while name.startswith("./"):
            name = name[2:]
        if name in ("", "."):
            continue
        if name == ".." or name.startswith("../") or "/../" in name:
            raise SystemExit("managed_wsl2_base_rootfs_unsafe_entry")
        if name in skip:
            continue
        member.name = name
        if member.isfile():
            fileobj = src.extractfile(member)
            if fileobj is None:
                raise SystemExit("managed_wsl2_base_rootfs_file_unreadable")
            sparse_headers = [key for key in member.pax_headers if key.startswith("GNU.sparse")]
            if member.sparse or sparse_headers:
                # extractfile() exposes logical bytes. Remove transport-only sparse
                # metadata before writing those expanded bytes into the new archive.
                member.pax_headers = {
                    key: value
                    for key, value in member.pax_headers.items()
                    if not key.startswith("GNU.sparse")
                }
                member.sparse = None
                sparse_files_expanded += 1
            dst.addfile(member, fileobj)
        else:
            dst.addfile(member)
        safe_seen.add(name.rstrip("/"))
    for directory in [
        "opt",
        "opt/immoapp",
        "opt/immoapp/runtime",
        "opt/immoapp/runtime/bin",
        "opt/immoapp/runtime/compose",
        "opt/immoapp/runtime/images",
        "opt/immoapp/runtime/logs",
        "opt/immoapp/runtime/proxy",
        "opt/immoapp/runtime/secrets",
    ]:
        if directory not in safe_seen:
            info = tarfile.TarInfo(directory)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            info.mtime = int(time.time())
            dst.addfile(info)
            safe_seen.add(directory)
    for name, data in overlay.items():
        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mode = 0o755 if name.startswith("opt/immoapp/runtime/bin/") else 0o644
        info.mtime = int(time.time())
        dst.addfile(info, io.BytesIO(data))

verified_entries = set()
with tarfile.open(output_path, "r:") as verified:
    for member in verified:
        normalized = member.name.replace("\\\\", "/").lstrip("/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if normalized:
            verified_entries.add(normalized.rstrip("/"))
missing_required = sorted(set(required) - verified_entries)
if missing_required:
    raise SystemExit(
        "managed_wsl2_rootfs_output_required_entry_missing:" + ",".join(missing_required)
    )
print(
    json.dumps(
        {
            "archive_entry_count": len(verified_entries),
            "archive_validation_status": "GO",
            "required_entries": required,
            "overlay_file_count": len(overlay),
            "sparse_files_expanded": sparse_files_expanded,
        },
        sort_keys=True,
    )
)
'@
    $pythonOutput = $builder | & $python - $baseFull $pendingOutputFull $RuntimeVersion $SourceCommitSha $templateRoot 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "managed_wsl2_runtime_rootfs_build_python_failed|$pythonOutput"
    }
    if (-not (Test-Path -LiteralPath $pendingOutputFull -PathType Leaf)) {
        throw "managed_wsl2_runtime_rootfs_output_missing|OutputRootfsTarPath was not created."
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $pendingOutputFull) {
        throw "managed_wsl2_runtime_rootfs_output_reparse_point|OutputRootfsTarPath is a reparse point after write."
    }
    $buildDetails = (($pythonOutput | Out-String).Trim() | ConvertFrom-Json)
    $archiveValidationStatus = [string]$buildDetails.archive_validation_status
    $archiveEntryCount = [int]$buildDetails.archive_entry_count
    $sparseFilesExpanded = [int]$buildDetails.sparse_files_expanded
    if ($archiveValidationStatus -ne "GO" -or $archiveEntryCount -lt $requiredEntries.Count) {
        throw "managed_wsl2_runtime_rootfs_output_validation_failed|The complete pending rootfs archive was not validated."
    }
    $outputSha = Get-ImmoAppFileSha256 -Path $pendingOutputFull
    Move-Item -LiteralPath $pendingOutputFull -Destination $outputFull -Force
    $pendingOutputFull = ""
    $proofResult = "GO"
    $reasonCode = "managed_wsl2_runtime_rootfs_built"
}
catch {
    $failure = [string]$_.Exception.Message
    if ($failure.Contains("|")) {
        $reasonCode = $failure.Split("|", 2)[0]
    }
    elseif ([string]::IsNullOrWhiteSpace($reasonCode)) {
        $reasonCode = "managed_wsl2_runtime_rootfs_build_failed"
    }
    $proofResult = "NO-GO"
}
finally {
    if (-not [string]::IsNullOrWhiteSpace($pendingOutputFull)) {
        Remove-Item -LiteralPath $pendingOutputFull -Force -ErrorAction SilentlyContinue
    }
}

$payload = [ordered]@{
    kind = "immoapp_managed_wsl2_runtime_rootfs_inventory"
    schema_version = 1
    created_at_utc = $createdAt
    source_commit_sha = $SourceCommitSha
    base_rootfs_tar_path = $baseFull
    base_rootfs_tar_sha256 = $baseSha
    output_rootfs_tar_path = $outputFull
    output_rootfs_tar_sha256 = $outputSha
    runtime_version = $RuntimeVersion
    build_method = $buildMethod
    build_mutated_wsl = $false
    build_invoked_docker = $false
    build_invoked_package_manager = $false
    archive_validation_status = $archiveValidationStatus
    archive_entry_count = $archiveEntryCount
    sparse_files_expanded = $sparseFilesExpanded
    expected_distro_name = "ImmoAppRuntime"
    required_entries = @($requiredEntries)
    rootfs_artifact_status = $proofResult
    runtime_identity_status = "NO-GO"
    runtime_start_status = "NO-GO"
    agency_install_status = "NO_GO"
    public_beta_status = "NO_GO"
    proof_result = $proofResult
    reason_code = $reasonCode
    reason = $failure
    recommended_next_action = if ($proofResult -eq "GO") {
        "Run import_managed_wsl2_runtime_distro.ps1 -PlanOnly against this rootfs, then import with explicit confirmation only when ready."
    } else {
        "Provide an explicit safe base rootfs tar and an approved ProgramData runtime output path."
    }
}

$writeResult = Write-ImmoAppSafeJson -Path $OutputJson -Payload $payload -ApprovedRoots $outputRoots
$payload["inventory_path"] = $writeResult.path
$payload["inventory_sha256"] = $writeResult.sha256
$finalWrite = Write-ImmoAppSafeJson -Path $OutputJson -Payload $payload -ApprovedRoots $outputRoots
$payload["inventory_sha256"] = $finalWrite.sha256

Write-Output ($payload | ConvertTo-Json -Depth 12)
if ($proofResult -ne "GO") {
    [Console]::Error.WriteLine("$($payload.reason_code)|$($payload.reason)")
    exit 1
}
exit 0
