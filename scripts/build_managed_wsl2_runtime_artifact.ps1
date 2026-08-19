[CmdletBinding()]
param(
    [string]$ArtifactRoot = "",
    [string]$OutputJson = "",
    [string]$SourceCommitSha = "",
    [switch]$AllowTestOnlyPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

function Get-ManagedWsl2BridgeScriptContent {
    return @'
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("start", "stop", "restart", "status", "health", "logs", "backup", "identity")]
    [string]$Action
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$distroName = "ImmoAppRuntime"
$wslPath = Join-Path $env:WINDIR "System32\wsl.exe"
$testWslPath = [Environment]::GetEnvironmentVariable("IMMOAPP_TEST_WSL_EXE")
if (
    -not [string]::IsNullOrWhiteSpace($testWslPath) -and
    [Environment]::GetEnvironmentVariable("IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT") -eq "1"
) {
    $wslPath = [System.IO.Path]::GetFullPath($testWslPath)
}
if (-not (Test-Path -LiteralPath $wslPath -PathType Leaf)) {
    [Console]::Error.WriteLine("wsl2_unavailable|Windows WSL executable was not found at the approved system path.")
    exit 21
}
$wslItem = Get-Item -LiteralPath $wslPath
if (($wslItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    [Console]::Error.WriteLine("wsl2_executable_reparse_point|The approved WSL executable path is a reparse point.")
    exit 21
}

$distrosText = (& $wslPath -l -q 2>$null | Out-String).Replace([string][char]0, "")
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine("managed_wsl2_runtime_distro_list_failed|Unable to list WSL distributions.")
    exit 22
}
$distros = @($distrosText -split "(`r`n|`n|`r)" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { [string]$_.Trim() })
if ($distros -notcontains $distroName) {
    [Console]::Error.WriteLine("managed_wsl2_runtime_distribution_missing|The ImmoAppRuntime WSL distribution is not installed.")
    exit 23
}

function Start-ImmoAppManagedWslKeepAlive {
    $keepAliveArgs = @(
        "-d",
        $distroName,
        "--cd",
        "/opt/immoapp/runtime",
        "--",
        "/opt/immoapp/runtime/bin/keepalive-managed-hub"
    )
    Start-Process `
        -FilePath $wslPath `
        -ArgumentList $keepAliveArgs `
        -WindowStyle Hidden | Out-Null
    Start-Sleep -Milliseconds 250
}

function Read-ImmoAppManagedRuntimeEnvFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    $values = @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $values
    }
    foreach ($rawLine in [System.IO.File]::ReadAllLines($Path)) {
        $line = [string]$rawLine
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith("#")) {
            continue
        }
        $separator = $line.IndexOf("=")
        if ($separator -le 0) {
            continue
        }
        $name = $line.Substring(0, $separator).Trim()
        $value = $line.Substring($separator + 1).Trim()
        if ($value.Length -ge 2 -and (
                ($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'"))
            )) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$name] = $value
    }
    return $values
}

function Get-ImmoAppManagedRuntimeEnvArgs {
    $allowedNames = @(
        "COMPOSE_PROFILES",
        "DJANGO_ALLOWED_HOSTS",
        "IMMOAPP_BACKEND_HOST_PORT",
        "IMMOAPP_CADDY_BIND_HOST",
        "IMMOAPP_HUB_FRONT_DOOR_PORT",
        "IMMOAPP_HUB_FRONT_DOOR_URL",
        "IMMOAPP_PLATFORM_ADMIN_EMAIL",
        "IMMOAPP_PUBLIC_BASE_URL",
        "IMMOAPP_WEB_BIND_HOST",
        "WEB_PORT"
    )
    $artifactRoot = Split-Path -Parent $PSScriptRoot
    $runtimeRoot = Split-Path -Parent $artifactRoot
    $appRoot = Split-Path -Parent $runtimeRoot
    $envFile = Join-Path (Join-Path $appRoot "config") ".env.local"
    $values = Read-ImmoAppManagedRuntimeEnvFile -Path $envFile
    $envArgs = New-Object System.Collections.Generic.List[string]
    foreach ($name in $allowedNames) {
        $value = ""
        if ($values.ContainsKey($name)) {
            $value = [string]$values[$name]
        }
        $processValue = [Environment]::GetEnvironmentVariable($name)
        if ([string]::IsNullOrWhiteSpace($value) -and -not [string]::IsNullOrWhiteSpace($processValue)) {
            $value = [string]$processValue
        }
        if ([string]::IsNullOrWhiteSpace($value)) {
            continue
        }
        if ($value.IndexOf([char]0) -ge 0 -or $value.Contains("`r") -or $value.Contains("`n") -or $value.Length -gt 2048) {
            [Console]::Error.WriteLine("managed_wsl2_runtime_env_value_invalid|Managed runtime environment value is invalid for $name.")
            exit 24
        }
        $envArgs.Add("$name=$value") | Out-Null
    }
    return @($envArgs.ToArray())
}

[string[]]$linuxArgs = @(
    switch ($Action) {
        "identity" { "/opt/immoapp/runtime/bin/immoapp-runtime-identity"; "--json" }
        "start" { "/opt/immoapp/runtime/bin/start-managed-hub" }
        "stop" { "/opt/immoapp/runtime/bin/stop-managed-hub" }
        "restart" { "/opt/immoapp/runtime/bin/restart-managed-hub" }
        "status" { "/opt/immoapp/runtime/bin/status-managed-hub" }
        "health" { "/opt/immoapp/runtime/bin/health-managed-hub" }
        "logs" { "/opt/immoapp/runtime/bin/logs-managed-hub" }
        "backup" { "/opt/immoapp/runtime/bin/backup-managed-hub" }
    }
)
$stdoutPath = [System.IO.Path]::GetTempFileName()
$stderrPath = [System.IO.Path]::GetTempFileName()
try {
    $defaultActionTimeoutSeconds = switch ($Action) {
        "start" { 720 }
        "restart" { 720 }
        "logs" { 120 }
        "backup" { 720 }
        default { 90 }
    }
    $actionTimeoutSeconds = $defaultActionTimeoutSeconds
    $timeoutOverride = [Environment]::GetEnvironmentVariable("IMMOAPP_MANAGED_WSL2_ACTION_TIMEOUT_SECONDS")
    if (-not [string]::IsNullOrWhiteSpace($timeoutOverride)) {
        $parsedTimeout = 0
        if ([int]::TryParse($timeoutOverride, [ref]$parsedTimeout) -and $parsedTimeout -gt 0) {
            $actionTimeoutSeconds = $parsedTimeout
        }
    }
    if ($Action -eq "start") {
        Start-ImmoAppManagedWslKeepAlive
    }
    [string[]]$runtimeEnvArgs = @(Get-ImmoAppManagedRuntimeEnvArgs)
    $linuxCommandArgs = if ($runtimeEnvArgs.Count -gt 0) { @("env") + $runtimeEnvArgs + $linuxArgs } else { $linuxArgs }
    $wslArguments = @("-d", $distroName, "--cd", "/opt/immoapp/runtime", "--") + $linuxCommandArgs
    $process = Start-Process `
        -FilePath $wslPath `
        -ArgumentList $wslArguments `
        -NoNewWindow `
        -PassThru `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath
    if (-not $process.WaitForExit([Math]::Max(1, $actionTimeoutSeconds) * 1000)) {
        try {
            & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
        }
        catch {
            try { $process.Kill() } catch { }
        }
        $stdout = if (Test-Path -LiteralPath $stdoutPath) {
            [System.IO.File]::ReadAllText($stdoutPath)
        } else {
            ""
        }
        $stderr = if (Test-Path -LiteralPath $stderrPath) {
            [System.IO.File]::ReadAllText($stderrPath)
        } else {
            ""
        }
        if (-not [string]::IsNullOrWhiteSpace($stdout)) {
            Write-Output $stdout
        }
        if (-not [string]::IsNullOrWhiteSpace($stderr)) {
            [Console]::Error.WriteLine($stderr)
        }
        [Console]::Error.WriteLine("managed_wsl2_runtime_bridge_timeout|Managed WSL2 runtime command '$Action' timed out after $actionTimeoutSeconds seconds.")
        exit 124
    }
    $exitCode = [int]$process.ExitCode
    if ($Action -eq "restart" -and $exitCode -eq 0) {
        Start-ImmoAppManagedWslKeepAlive
    }
    $stdout = if (Test-Path -LiteralPath $stdoutPath) {
        [System.IO.File]::ReadAllText($stdoutPath)
    } else {
        ""
    }
    if (-not [string]::IsNullOrWhiteSpace($stdout)) {
        Write-Output $stdout
    }
    if ($exitCode -ne 0) {
        $stderr = if (Test-Path -LiteralPath $stderrPath) {
            [System.IO.File]::ReadAllText($stderrPath)
        } else {
            ""
        }
        if (-not [string]::IsNullOrWhiteSpace($stderr)) {
            [Console]::Error.WriteLine($stderr)
        }
        [Console]::Error.WriteLine("managed_wsl2_runtime_bridge_command_failed|Managed WSL2 runtime command '$Action' failed with exit code $exitCode.")
        exit $exitCode
    }
    exit 0
}
finally {
    Remove-Item -LiteralPath $stdoutPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
}
'@
}

function Write-ManagedWsl2RuntimeEntrypoint {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$BridgeScript,
        [Parameter(Mandatory = $true)][string]$Kind
    )
    $content = @"
param([Parameter(ValueFromRemainingArguments = `$true)][string[]]`$Args)
`$ErrorActionPreference = "Stop"
`$command = if (`$Args.Count -gt 0) { [string]`$Args[0] } else { "" }
if (`$command -eq "--version" -or `$command -eq "version") {
    Write-Output "ImmoApp managed WSL2 $Kind artifact 0.1.0"
    exit 0
}
if (`$command -in @("up", "start")) {
    & "$BridgeScript" -Action start
    exit `$LASTEXITCODE
}
if (`$command -in @("down", "stop")) {
    & "$BridgeScript" -Action stop
    exit `$LASTEXITCODE
}
if (`$command -eq "restart") {
    & "$BridgeScript" -Action restart
    exit `$LASTEXITCODE
}
if (`$command -in @("status", "health", "logs", "identity")) {
    & "$BridgeScript" -Action `$command
    exit `$LASTEXITCODE
}
[Console]::Error.WriteLine("managed_wsl2_runtime_command_not_supported|Unsupported managed WSL2 runtime artifact command: `$command")
exit 18
"@
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    }
    [System.IO.File]::WriteAllText($Path, $content, [System.Text.UTF8Encoding]::new($false))
}

function Write-ManagedWsl2RuntimeActionScript {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Action
    )
    $content = @"
`$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
`$bridge = Join-Path `$PSScriptRoot "immoapp-managed-wsl2-bridge.ps1"
& `$bridge -Action "$Action"
exit `$LASTEXITCODE
"@
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    }
    [System.IO.File]::WriteAllText($Path, $content, [System.Text.UTF8Encoding]::new($false))
}

$paths = Ensure-ImmoAppRuntimeLayout
$canonicalPaths = Get-ImmoAppCanonicalRuntimePaths
if ([string]::IsNullOrWhiteSpace($ArtifactRoot)) {
    $ArtifactRoot = Join-Path $paths.RuntimeRoot "managed-wsl2-artifact"
}
if ([string]::IsNullOrWhiteSpace($OutputJson)) {
    $OutputJson = Join-Path $paths.ConfigRoot "managed_wsl2_runtime_artifact_inventory.json"
}

$artifactRootFull = [System.IO.Path]::GetFullPath($ArtifactRoot)
$runtimeRoots = if ($AllowTestOnlyPath) {
    Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "runtime"
} else {
    @($canonicalPaths.RuntimeRoot)
}
Assert-ImmoAppProofOnlyPathApproved -Path $artifactRootFull -Roots $runtimeRoots -Label "ArtifactRoot"
if (Test-Path -LiteralPath $artifactRootFull -PathType Container) {
    if (Test-ImmoAppPathHasReparsePoint -Path $artifactRootFull) {
        throw "managed_wsl2_runtime_artifact_reparse_point|ArtifactRoot contains a reparse point, symlink, or junction: $artifactRootFull"
    }
} else {
    [System.IO.Directory]::CreateDirectory($artifactRootFull) | Out-Null
}

if ([string]::IsNullOrWhiteSpace($SourceCommitSha)) {
    try {
        $SourceCommitSha = (& git -C (Get-ImmoAppRepoRoot).Path rev-parse HEAD 2>$null | Out-String).Trim().ToLowerInvariant()
    }
    catch {
        $SourceCommitSha = ""
    }
}

$runtimeWrapper = Join-Path $artifactRootFull "bin\immoapp-managed-wsl2-runtime.ps1"
$composeWrapper = Join-Path $artifactRootFull "bin\immoapp-managed-wsl2-compose.ps1"
$bridgeScript = Join-Path $artifactRootFull "bin\immoapp-managed-wsl2-bridge.ps1"
$startScript = Join-Path $artifactRootFull "bin\start-managed-hub.ps1"
$statusScript = Join-Path $artifactRootFull "bin\status-managed-hub.ps1"
$healthScript = Join-Path $artifactRootFull "bin\health-managed-hub.ps1"
$logsScript = Join-Path $artifactRootFull "bin\logs-managed-hub.ps1"
$backupScript = Join-Path $artifactRootFull "bin\backup-managed-hub.ps1"
$stopScript = Join-Path $artifactRootFull "bin\stop-managed-hub.ps1"
$restartScript = Join-Path $artifactRootFull "bin\restart-managed-hub.ps1"
$bootstrapScript = Join-Path $artifactRootFull "bin\bootstrap-managed-runtime.ps1"
$keepAliveScript = Join-Path $artifactRootFull "bin\keepalive-managed-hub.ps1"
$metadata = Join-Path $artifactRootFull "runtime-metadata.json"
$imageBundleArchivePath = Get-ImmoAppManagedWsl2ImageBundleArchivePath
$imageBundleInventoryPath = Get-ImmoAppManagedWsl2ImageBundleInventoryPath
$composePayloadPath = Get-ImmoAppManagedWsl2RuntimeComposePayloadPath

Write-ManagedWsl2RuntimeEntrypoint -Path $runtimeWrapper -BridgeScript $bridgeScript -Kind "runtime"
Write-ManagedWsl2RuntimeEntrypoint -Path $composeWrapper -BridgeScript $bridgeScript -Kind "compose"
[System.IO.File]::WriteAllText($bridgeScript, (Get-ManagedWsl2BridgeScriptContent), [System.Text.UTF8Encoding]::new($false))
Write-ManagedWsl2RuntimeActionScript -Path $startScript -Action "start"
Write-ManagedWsl2RuntimeActionScript -Path $statusScript -Action "status"
Write-ManagedWsl2RuntimeActionScript -Path $healthScript -Action "health"
Write-ManagedWsl2RuntimeActionScript -Path $logsScript -Action "logs"
Write-ManagedWsl2RuntimeActionScript -Path $backupScript -Action "backup"
Write-ManagedWsl2RuntimeActionScript -Path $stopScript -Action "stop"
Write-ManagedWsl2RuntimeActionScript -Path $restartScript -Action "restart"
Write-ManagedWsl2RuntimeActionScript -Path $bootstrapScript -Action "identity"
Write-ManagedWsl2RuntimeActionScript -Path $keepAliveScript -Action "start"
$metadataPayload = [ordered]@{
    kind = "immoapp_managed_wsl2_runtime_artifact_metadata"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    source_commit_sha = $SourceCommitSha
    artifact_version = "0.1.0"
    runtime_mode = "managed_wsl2_container_runtime_artifact"
    start_bridge_status = "implemented_requires_immoapp_wsl_distribution"
    expected_wsl_distribution_name = "ImmoAppRuntime"
    linux_runtime_root = "/opt/immoapp/runtime"
    compose_payload_path = $composePayloadPath
    image_bundle_archive_path = $imageBundleArchivePath
    image_bundle_inventory_path = $imageBundleInventoryPath
    expected_compose_pull_policy = "never"
    runtime_identity_command_args = @("/opt/immoapp/runtime/bin/immoapp-runtime-identity", "--json")
    proof_only = $true
    agency_install_status = "NO_GO"
}
[System.IO.File]::WriteAllText($metadata, ($metadataPayload | ConvertTo-Json -Depth 6), [System.Text.UTF8Encoding]::new($false))

$inventory = Get-ImmoAppStrictRuntimeTreeInventory -Root $artifactRootFull -RequireNonEmpty
$files = @($inventory.files)
$requiredEntries = [ordered]@{}
foreach ($entry in Get-ImmoAppManagedWsl2RuntimeArtifactRequiredEntries) {
    $match = @($files | Where-Object { [string]$_.path -eq $entry })
    $requiredEntries[$entry] = [ordered]@{
        status = if ($match.Count -gt 0) { "present" } else { "missing" }
        sha256 = if ($match.Count -gt 0) { [string]$match[0].sha256 } else { "" }
    }
}
$missingRequired = @($requiredEntries.GetEnumerator() | Where-Object { [string]$_.Value.status -ne "present" } | ForEach-Object { [string]$_.Key })
$proofResult = if ($missingRequired.Count -eq 0 -and @($inventory.forbidden_matches).Count -eq 0) { "GO" } else { "NO-GO" }
$reasonCode = if ($proofResult -eq "GO") { "managed_wsl2_runtime_artifact_inventory_go_start_not_proven" } else { "managed_wsl2_runtime_required_entry_missing" }

$payload = [ordered]@{
    kind = "immoapp_managed_wsl2_runtime_artifact_inventory"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    source_commit_sha = $SourceCommitSha
    artifact_root = $artifactRootFull
    artifact_tree_sha256 = [string]$inventory.sha256
    file_count = [int]$inventory.file_count
    total_bytes = [int64]$inventory.total_bytes
    files = @($files)
    required_entries = $requiredEntries
    forbidden_path_count = [int]@($inventory.forbidden_matches).Count
    forbidden_path_matches = @($inventory.forbidden_matches)
    runtime_executable_path = $runtimeWrapper
    compose_executable_path = $composeWrapper
    start_command_path = $startScript
    status_command_path = $statusScript
    health_command_path = $healthScript
    logs_command_path = $logsScript
    backup_command_path = $backupScript
    stop_command_path = $stopScript
    restart_command_path = $restartScript
    bootstrap_command_path = $bootstrapScript
    keepalive_command_path = $keepAliveScript
    image_bundle_archive_path = $imageBundleArchivePath
    image_bundle_inventory_path = $imageBundleInventoryPath
    compose_payload_path = $composePayloadPath
    compose_pull_policy = "never"
    required_compose_services = @(Get-ImmoAppManagedWsl2RuntimeRequiredComposeServices)
    expected_distro_name = "ImmoAppRuntime"
    artifact_version = "0.1.0"
    runtime_dependency_mode = "managed_wsl2_container_runtime_artifact"
    runtime_artifact_status = if ($proofResult -eq "GO") { "GO" } else { "NO-GO" }
    runtime_start_status = "NO-GO"
    internal_proof_status = if ($proofResult -eq "GO") { "GO" } else { "NO_GO" }
    agency_install_status = "NO_GO"
    public_beta_status = "NO_GO"
    proof_result = $proofResult
    reason_code = $reasonCode
    recommended_next_action = "Install/prove the ImmoAppRuntime WSL distribution command path, then collect fresh Hub start, Caddy/front-door health, and network-boundary evidence."
}

$approvedOutputRoots = if ($AllowTestOnlyPath) {
    @(
        (Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "config") +
        (Get-ImmoAppProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "logs")
    ) | Select-Object -Unique
} else {
    @($canonicalPaths.ConfigRoot, $canonicalPaths.LogsRoot)
}
$write = Write-ImmoAppSafeJson -Path $OutputJson -Payload $payload -ApprovedRoots $approvedOutputRoots -Depth 12
$payload["inventory_path"] = [string]$OutputJson
$payload["inventory_sha256"] = [string]$write.sha256
$payload | ConvertTo-Json -Depth 12
