[CmdletBinding()]
param(
    [string]$RootfsTarPath = "",
    [string]$InstallLocation = "",
    [string]$OutputJson = "",
    [switch]$PlanOnly,
    [switch]$ConfirmImportManagedWslRuntime,
    [switch]$ConfirmReplaceExistingDistro,
    [switch]$UpdateExistingRuntimePayload,
    [switch]$ConfirmUpdateExistingRuntimePayload,
    [string]$ExpectedDistroName = "ImmoAppRuntime"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

function Test-ImportPathParentHasReparsePoint {
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

function Resolve-ImportExistingFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "$Label missing."
    }
    $full = [System.IO.Path]::GetFullPath($Path)
    if (Test-ImportPathParentHasReparsePoint -Path $full) {
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

function Get-ApprovedWslPath {
    $systemWsl = Join-Path $env:WINDIR "System32\wsl.exe"
    $testWslPath = [Environment]::GetEnvironmentVariable("IMMOAPP_TEST_WSL_EXE")
    if (
        -not [string]::IsNullOrWhiteSpace($testWslPath) -and
        [Environment]::GetEnvironmentVariable("IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT") -eq "1"
    ) {
        return [System.IO.Path]::GetFullPath($testWslPath)
    }
    return $systemWsl
}

function Get-ExistingWslDistros {
    param([Parameter(Mandatory = $true)][string]$WslPath)
    $text = (& $WslPath -l -q 2>$null | Out-String).Replace([string][char]0, "")
    if ($LASTEXITCODE -ne 0) {
        throw "managed_wsl2_runtime_distro_list_failed"
    }
    return @(
        $text -split "(`r`n|`n|`r)" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            ForEach-Object { [string]$_.Trim() }
    )
}

function Get-ImmoAppManagedWsl2RootfsRequiredEntries {
    return @(
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
}

function Convert-ImportRootfsHostPathToWslPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    if ([Environment]::GetEnvironmentVariable("IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT") -eq "1") {
        $full = [System.IO.Path]::GetFullPath($Path)
        $drive = [System.IO.Path]::GetPathRoot($full).TrimEnd("\", ":").ToLowerInvariant()
        if ($drive -ne "c") {
            throw "managed_wsl2_rootfs_wsl_path_missing|Only C: rootfs paths can be converted to WSL paths."
        }
        $suffix = $full.Substring(([System.IO.Path]::GetPathRoot($full)).Length).TrimStart("\", "/").Replace("\", "/")
        return "/mnt/c/$suffix"
    }
    return (Convert-ImmoAppManagedWsl2CanonicalHostPathToWslPath -Path $Path)
}

function Get-RootfsTarEntries {
    param([Parameter(Mandatory = $true)][string]$Path)
    $tarPath = Join-Path $env:WINDIR "System32\tar.exe"
    if (-not (Test-Path -LiteralPath $tarPath -PathType Leaf)) {
        $tarPath = "tar.exe"
    }
    $output = & $tarPath -tf $Path 2>&1
    $tarExitCode = $LASTEXITCODE
    if ($tarExitCode -ne 0 -and @($output).Count -lt 1) {
        throw "managed_wsl2_rootfs_tar_invalid|RootfsTarPath must be a readable tar archive."
    }
    $entries = New-Object System.Collections.Generic.List[string]
    foreach ($line in @($output)) {
        $entry = ([string]$line).Trim()
        if ([string]::IsNullOrWhiteSpace($entry)) { continue }
        if (
            $entry.StartsWith("tar.exe:", [System.StringComparison]::OrdinalIgnoreCase) -or
            $entry.StartsWith("tar:", [System.StringComparison]::OrdinalIgnoreCase) -or
            $entry.StartsWith("At line:", [System.StringComparison]::OrdinalIgnoreCase) -or
            $entry.StartsWith("+ ", [System.StringComparison]::OrdinalIgnoreCase) -or
            $entry.StartsWith("CategoryInfo", [System.StringComparison]::OrdinalIgnoreCase) -or
            $entry.StartsWith("FullyQualifiedErrorId", [System.StringComparison]::OrdinalIgnoreCase)
        ) { continue }
        $normalized = $entry.Replace("\", "/").TrimStart("/")
        while ($normalized.StartsWith("./")) {
            $normalized = $normalized.Substring(2)
        }
        if (
            $normalized -eq ".." -or
            $normalized.StartsWith("../") -or
            $normalized.Contains("/../")
        ) {
            throw "managed_wsl2_rootfs_tar_unsafe_entry|RootfsTarPath contains an unsafe traversal entry."
        }
        $entries.Add($normalized.TrimEnd("/"))
    }
    if ($entries.Count -lt 1) {
        throw "managed_wsl2_rootfs_tar_invalid|RootfsTarPath did not expose any readable tar entries."
    }
    return @($entries.ToArray())
}

function Test-RootfsRequiredEntries {
    param([Parameter(Mandatory = $true)][string]$Path)
    $entries = @(Get-RootfsTarEntries -Path $Path)
    $required = @(Get-ImmoAppManagedWsl2RootfsRequiredEntries)
    $missing = @($required | Where-Object { $entries -notcontains $_ })
    return [ordered]@{
        entries = @($entries)
        required_entries = @($required)
        missing_entries = @($missing)
        status = if ($missing.Count -eq 0) { "GO" } else { "NO-GO" }
    }
}

function Invoke-ExistingRuntimePayloadUpdate {
    param(
        [Parameter(Mandatory = $true)][string]$WslPath,
        [Parameter(Mandatory = $true)][string]$DistroName,
        [Parameter(Mandatory = $true)][string]$RootfsTarPath
    )
    $rootfsWslPath = Convert-ImportRootfsHostPathToWslPath -Path $RootfsTarPath
    $requiredChecks = @(
        "test -x /opt/immoapp/runtime/bin/immoapp-runtime-identity",
        "test -x /opt/immoapp/runtime/bin/start-managed-hub",
        "test -x /opt/immoapp/runtime/bin/status-managed-hub",
        "test -x /opt/immoapp/runtime/bin/health-managed-hub",
        "test -x /opt/immoapp/runtime/bin/logs-managed-hub",
        "test -x /opt/immoapp/runtime/bin/backup-managed-hub",
        "test -x /opt/immoapp/runtime/bin/stop-managed-hub",
        "test -x /opt/immoapp/runtime/bin/restart-managed-hub",
        "test -x /opt/immoapp/runtime/bin/keepalive-managed-hub",
        "test -f /opt/immoapp/runtime/compose/compose.yaml"
    ) -join "; "
    $rootfsQuoted = "'" + $rootfsWslPath.Replace("'", "'\''") + "'"
    $scriptTemplate = @'
set -eu
staging="/opt/immoapp/runtime.update.$$"
previous=""
runtime_was_running=false
preserve_runtime_state() {
  old_runtime="$1"
  new_runtime="$2"
  for item in secrets backups logs images state; do
    if [ -e "$old_runtime/$item" ]; then
      rm -rf "$new_runtime/$item"
      mkdir -p "$(dirname "$new_runtime/$item")"
      cp -a "$old_runtime/$item" "$new_runtime/$item"
    fi
  done
}
rollback() {
  status="$?"
  if [ "$status" -ne 0 ] && [ -n "$previous" ] && [ -d "$previous" ]; then
    rm -rf /opt/immoapp/runtime
    mv "$previous" /opt/immoapp/runtime
  fi
  rm -rf "$staging"
}
trap rollback EXIT
rm -rf "$staging"
mkdir -p "$staging"
if [ -x /opt/immoapp/runtime/bin/managed-hub-common ] &&
   [ -x /opt/immoapp/runtime/bin/stop-managed-hub ]; then
  . /opt/immoapp/runtime/bin/managed-hub-common
  if docker_info_ok; then
    running_ids="$(
      capture_with_timeout \
        "$command_timeout" \
        "$runtime_root/logs/payload-update-compose-ps.out" \
        docker compose -f "$compose_file" -p "$project_name" ps --status running -q ||
        true
    )"
    if [ -n "$running_ids" ]; then
      runtime_was_running=true
      if ! /opt/immoapp/runtime/bin/stop-managed-hub \
        >"$runtime_root/logs/payload-update-stop.json" \
        2>"$runtime_root/logs/payload-update-stop.err"; then
        cat "$runtime_root/logs/payload-update-stop.err" >&2 || true
        exit 40
      fi
    fi
  fi
fi
if ! tar -C "$staging" -xf __ROOTFS_QUOTED__ opt/immoapp/runtime 2>/tmp/immoapp-runtime-update-tar.err; then
  if ! tar -C "$staging" -xf __ROOTFS_QUOTED__ ./opt/immoapp/runtime 2>>/tmp/immoapp-runtime-update-tar.err; then
    cat /tmp/immoapp-runtime-update-tar.err >&2 || true
    exit 41
  fi
fi
rm -f /tmp/immoapp-runtime-update-tar.err
test -d "$staging/opt/immoapp/runtime"
if [ -e /opt/immoapp/runtime ]; then
  previous="/opt/immoapp/runtime.previous.$$"
  rm -rf "$previous"
  mv /opt/immoapp/runtime "$previous"
fi
mkdir -p /opt/immoapp
mv "$staging/opt/immoapp/runtime" /opt/immoapp/runtime
if [ -n "$previous" ] && [ -d "$previous" ]; then
  preserve_runtime_state "$previous" /opt/immoapp/runtime
fi
chmod +x /opt/immoapp/runtime/bin/*
__REQUIRED_CHECKS__
rm -rf "$staging"
if [ -n "$previous" ]; then rm -rf "$previous"; fi
trap - EXIT
printf 'managed_wsl2_runtime_was_running=%s\n' "$runtime_was_running"
printf '%s\n' 'managed_wsl2_runtime_payload_update_go'
'@
    $script = $scriptTemplate.
        Replace("__ROOTFS_QUOTED__", $rootfsQuoted).
        Replace("__REQUIRED_CHECKS__", $requiredChecks)
    $runtimePaths = Ensure-ImmoAppRuntimeLayout
    $tempScriptPath = Join-Path $runtimePaths.TmpRoot ("managed-wsl2-runtime-payload-update-{0}.sh" -f ([guid]::NewGuid().ToString("N")))
    $tempScriptParent = Split-Path -Parent $tempScriptPath
    if (-not (Test-Path -LiteralPath $tempScriptParent -PathType Container)) {
        [System.IO.Directory]::CreateDirectory($tempScriptParent) | Out-Null
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $tempScriptParent) {
        throw "managed_wsl2_runtime_payload_update_tmp_reparse_point|Payload update temp directory contains a reparse point."
    }
    $tempScriptWslPath = Convert-ImportRootfsHostPathToWslPath -Path $tempScriptPath
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($tempScriptPath, $script.Replace("`r`n", "`n"), $utf8NoBom)
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $WslPath -d $DistroName -- sh $tempScriptWslPath 2>&1
        $wslExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Remove-Item -LiteralPath $tempScriptPath -Force -ErrorAction SilentlyContinue
    }
    $outputText = (($output | Out-String).Trim())
    $successSentinelPresent = $outputText.Contains("managed_wsl2_runtime_payload_update_go")
    if ($wslExitCode -ne 0 -and -not $successSentinelPresent) {
        throw "managed_wsl2_runtime_payload_update_failed|Failed to update /opt/immoapp/runtime in existing ImmoAppRuntime: $outputText"
    }
    if (-not $successSentinelPresent) {
        throw "managed_wsl2_runtime_payload_update_missing_success_sentinel|Existing ImmoAppRuntime payload update did not emit the verified success sentinel: $outputText"
    }
    return [ordered]@{
        payload_update_status = "GO"
        payload_update_output = $outputText
        rootfs_wsl_path = $rootfsWslPath
        runtime_was_running = $outputText.Contains("managed_wsl2_runtime_was_running=true")
    }
}

$paths = Ensure-ImmoAppRuntimeLayout
$canonicalPaths = Get-ImmoAppCanonicalRuntimePaths
if ([string]::IsNullOrWhiteSpace($InstallLocation)) {
    $InstallLocation = Join-Path $canonicalPaths.RuntimeRoot ("wsl\" + $ExpectedDistroName)
}
if ([string]::IsNullOrWhiteSpace($OutputJson)) {
    $OutputJson = Join-Path $paths.LogsRoot "managed_wsl2_runtime_import_plan.json"
}

$runtimeRoots = Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "runtime"
$outputRoots = @()
$outputRoots += Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "logs"
$outputRoots += Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "config"
$outputRoots += Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "runtime"
$outputRoots = @($outputRoots | Select-Object -Unique)

$effectivePlanOnly = if ($UpdateExistingRuntimePayload.IsPresent) {
    ($PlanOnly.IsPresent -or -not $ConfirmUpdateExistingRuntimePayload.IsPresent)
} else {
    ($PlanOnly.IsPresent -or -not $ConfirmImportManagedWslRuntime.IsPresent)
}
$createdAt = (Get-Date).ToUniversalTime().ToString("o")
$installLocationFull = [System.IO.Path]::GetFullPath($InstallLocation)
$rootfsFull = ""
$rootfsSha = ""
$rootfsStatus = "missing"
$rootfsRequiredEntries = @()
$rootfsMissingEntries = @()
$wslPath = Get-ApprovedWslPath
$wslStatus = "not_checked"
$existingDistroPresent = $false
$existingDistros = @()
$importAttempted = $false
$payloadUpdateAttempted = $false
$payloadUpdateStatus = "not_applicable"
$payloadUpdateOutput = ""
$payloadUpdateRootfsWslPath = ""
$runtimeWasRunning = $false
$mutationPerformed = $false
$importStatus = if ($effectivePlanOnly) { "planned" } else { "NO-GO" }
$reasonCode = ""
$proofResult = "NO-GO"
$failure = ""

try {
    if ([string]::IsNullOrWhiteSpace($ExpectedDistroName) -or $ExpectedDistroName -ne "ImmoAppRuntime") {
        throw "managed_wsl2_runtime_distro_name_not_approved|ExpectedDistroName must be ImmoAppRuntime for this managed runtime lane."
    }

    Assert-ImmoAppProofOnlyPathApproved -Path $installLocationFull -Roots $runtimeRoots -Label "InstallLocation"
    if (Test-ImportPathParentHasReparsePoint -Path $installLocationFull) {
        throw "managed_wsl2_runtime_import_reparse_point|InstallLocation parent contains a reparse point, symlink, or junction."
    }

    if ([string]::IsNullOrWhiteSpace($RootfsTarPath)) {
        throw "managed_wsl2_rootfs_tar_path_required|RootfsTarPath is required; no default rootfs is inferred."
    }
    $rootfsFull = Resolve-ImportExistingFile -Path $RootfsTarPath -Label "RootfsTarPath"
    $rootfsSha = Get-ImmoAppFileSha256 -Path $rootfsFull
    $rootfsCheck = Test-RootfsRequiredEntries -Path $rootfsFull
    $rootfsRequiredEntries = @($rootfsCheck.required_entries)
    $rootfsMissingEntries = @($rootfsCheck.missing_entries)
    $rootfsStatus = [string]$rootfsCheck.status
    if ($rootfsStatus -ne "GO") {
        throw "managed_wsl2_rootfs_required_command_missing|RootfsTarPath is missing required ImmoAppRuntime commands."
    }

    if (-not (Test-Path -LiteralPath $wslPath -PathType Leaf)) {
        throw "managed_wsl2_wsl_executable_missing|Windows WSL executable was not found at the approved path."
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $wslPath) {
        throw "managed_wsl2_wsl_executable_reparse_point|The approved WSL executable path is a reparse point."
    }
    $wslStatus = "GO"
    $existingDistros = @(Get-ExistingWslDistros -WslPath $wslPath)
    $existingDistroPresent = ($existingDistros -contains $ExpectedDistroName)

    if ($UpdateExistingRuntimePayload.IsPresent -and -not $existingDistroPresent) {
        throw "managed_wsl2_runtime_distro_missing_for_payload_update|ImmoAppRuntime must exist before updating its runtime payload."
    }

    if ($existingDistroPresent -and -not $ConfirmReplaceExistingDistro.IsPresent -and -not $UpdateExistingRuntimePayload.IsPresent) {
        throw "managed_wsl2_runtime_distro_exists_replace_not_confirmed|ImmoAppRuntime already exists; replacement requires ConfirmReplaceExistingDistro."
    }

    if ($effectivePlanOnly) {
        $importStatus = "planned"
        $proofResult = "GO"
        $reasonCode = if ($UpdateExistingRuntimePayload.IsPresent) { "managed_wsl2_runtime_payload_update_plan_ready" } else { "managed_wsl2_runtime_import_plan_ready" }
    }
    elseif ($UpdateExistingRuntimePayload.IsPresent) {
        $payloadUpdateAttempted = $true
        $update = Invoke-ExistingRuntimePayloadUpdate -WslPath $wslPath -DistroName $ExpectedDistroName -RootfsTarPath $rootfsFull
        $payloadUpdateStatus = [string]$update.payload_update_status
        $payloadUpdateOutput = [string]$update.payload_update_output
        $payloadUpdateRootfsWslPath = [string]$update.rootfs_wsl_path
        $runtimeWasRunning = [bool]$update.runtime_was_running
        $mutationPerformed = $true
        $importStatus = "not_attempted_existing_distro_payload_update"
        $proofResult = "GO"
        $reasonCode = "managed_wsl2_runtime_payload_updated"
    }
    else {
        if ($existingDistroPresent) {
            $importAttempted = $true
            & $wslPath --unregister $ExpectedDistroName | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "managed_wsl2_runtime_distro_unregister_failed|Existing ImmoAppRuntime distro replacement failed."
            }
            $mutationPerformed = $true
        }
        if (-not (Test-Path -LiteralPath $installLocationFull)) {
            [System.IO.Directory]::CreateDirectory($installLocationFull) | Out-Null
        }
        if (Test-ImmoAppPathHasReparsePoint -Path $installLocationFull) {
            throw "managed_wsl2_runtime_import_reparse_point|InstallLocation contains a reparse point after creation."
        }
        $importAttempted = $true
        & $wslPath --import $ExpectedDistroName $installLocationFull $rootfsFull --version 2 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "managed_wsl2_runtime_distro_import_failed|wsl.exe --import failed for ImmoAppRuntime."
        }
        $mutationPerformed = $true
        $importStatus = "GO"
        $proofResult = "GO"
        $reasonCode = "managed_wsl2_runtime_distro_imported"
    }
}
catch {
    $failure = [string]$_.Exception.Message
    if ($failure.Contains("|")) {
        $reasonCode = $failure.Split("|", 2)[0]
    }
    elseif ([string]::IsNullOrWhiteSpace($reasonCode)) {
        $reasonCode = "managed_wsl2_runtime_import_failed"
    }
    if ([string]::IsNullOrWhiteSpace($importStatus) -or $importStatus -eq "planned") {
        $importStatus = "NO-GO"
    }
    $proofResult = "NO-GO"
}

$payload = [ordered]@{
    kind = "immoapp_managed_wsl2_runtime_import_plan"
    schema_version = 1
    created_at_utc = $createdAt
    expected_distro_name = $ExpectedDistroName
    rootfs_tar_path = $rootfsFull
    rootfs_tar_sha256 = $rootfsSha
    rootfs_status = $rootfsStatus
    rootfs_required_entries = @($rootfsRequiredEntries)
    rootfs_missing_entries = @($rootfsMissingEntries)
    install_location = $installLocationFull
    install_location_status = if ([string]::IsNullOrWhiteSpace($failure) -or $reasonCode -notin @("managed_wsl2_runtime_import_reparse_point", "managed_runtime_proof_provider_path_not_approved")) { "GO" } else { "NO-GO" }
    wsl_executable_path = $wslPath
    wsl_executable_status = $wslStatus
    existing_distro_present = $existingDistroPresent
    existing_distros = @($existingDistros)
    plan_only = $effectivePlanOnly
    import_attempted = $importAttempted
    payload_update_requested = [bool]$UpdateExistingRuntimePayload.IsPresent
    payload_update_attempted = $payloadUpdateAttempted
    payload_update_status = $payloadUpdateStatus
    payload_update_output = $payloadUpdateOutput
    payload_update_rootfs_wsl_path = $payloadUpdateRootfsWslPath
    runtime_was_running = $runtimeWasRunning
    mutation_performed = $mutationPerformed
    import_status = $importStatus
    runtime_identity_status = "NO-GO"
    runtime_start_status = "NO-GO"
    agency_install_status = "NO_GO"
    public_beta_status = "NO_GO"
    proof_result = $proofResult
    reason_code = if ([string]::IsNullOrWhiteSpace($reasonCode)) { "managed_wsl2_runtime_import_unknown" } else { $reasonCode }
    reason = $failure
    recommended_next_action = if ($proofResult -eq "GO" -and -not $effectivePlanOnly) {
        "Run Hub Manager managed-runtime status/start proof against ImmoAppRuntime; do not claim agency GO until front-door, LAN, backup/restore, lifecycle, support, signing, and HTTPS proofs pass."
    } elseif ($proofResult -eq "GO") {
        "Confirm import with an approved rootfs when ready; this plan does not start the runtime."
    } else {
        "Provide a real ImmoAppRuntime rootfs tar path, remove unsafe paths, or confirm replacement only when intentionally replacing the managed distro."
    }
}

$writeResult = Write-ImmoAppSafeJson -Path $OutputJson -Payload $payload -ApprovedRoots $outputRoots
$json = $payload | ConvertTo-Json -Depth 12
Write-Output $json
if ($proofResult -ne "GO") {
    [Console]::Error.WriteLine("$($payload.reason_code)|$($payload.reason)")
    exit 1
}
exit 0
