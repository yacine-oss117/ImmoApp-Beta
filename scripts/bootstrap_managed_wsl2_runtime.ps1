[CmdletBinding()]
param(
    [string]$OutputJson = "",
    [string]$ProviderConfigPath = "",
    [string]$ExpectedDistroName = "ImmoAppRuntime"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

function Join-ImmoAppProcessArguments {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    return (($Arguments | ForEach-Object {
                $value = [string]$_
                if ($value -match '[\s"]') {
                    '"' + ($value.Replace('\', '\\').Replace('"', '\"')) + '"'
                }
                else {
                    $value
                }
            }) -join " ")
}

function Invoke-ManagedRuntimeCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$TimeoutSeconds = 30
    )
    $stdout = [System.IO.Path]::GetTempFileName()
    $stderr = [System.IO.Path]::GetTempFileName()
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $process = $null
    $timedOut = $false
    $exitCode = 998
    try {
        $process = Start-Process `
            -FilePath "powershell" `
            -ArgumentList (Join-ImmoAppProcessArguments -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Path, "identity")) `
            -RedirectStandardOutput $stdout `
            -RedirectStandardError $stderr `
            -PassThru `
            -WindowStyle Hidden
        if (-not $process.WaitForExit([Math]::Max(1, $TimeoutSeconds) * 1000)) {
            $timedOut = $true
            try {
                & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
            }
            catch {
                try { $process.Kill() } catch { }
            }
            $exitCode = 124
        }
        else {
            $exitCode = [int]$process.ExitCode
        }
    }
    catch {
        $exitCode = 998
        Set-Content -LiteralPath $stderr -Value ([string]$_.Exception.Message) -Encoding UTF8
    }
    finally {
        $stopwatch.Stop()
    }
    $output = if (Test-Path -LiteralPath $stdout) { Get-Content -LiteralPath $stdout -Raw -ErrorAction SilentlyContinue } else { "" }
    $errorText = if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr -Raw -ErrorAction SilentlyContinue } else { "" }
    Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
    return [ordered]@{
        exit_code = $exitCode
        timed_out = $timedOut
        timeout_seconds = [int]$TimeoutSeconds
        elapsed_seconds = [math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
        output = (($output + $errorText) | Out-String).Trim()
    }
}

function Get-ApprovedWslPath {
    $wslPath = Join-Path $env:WINDIR "System32\wsl.exe"
    $testWslPath = [Environment]::GetEnvironmentVariable("IMMOAPP_TEST_WSL_EXE")
    if (
        -not [string]::IsNullOrWhiteSpace($testWslPath) -and
        [Environment]::GetEnvironmentVariable("IMMOAPP_ALLOW_TEST_PROGRAMDATA_ROOT") -eq "1"
    ) {
        $wslPath = [System.IO.Path]::GetFullPath($testWslPath)
    }
    if (-not (Test-Path -LiteralPath $wslPath -PathType Leaf)) {
        return [ordered]@{ path = $wslPath; status = "NO-GO"; reason_code = "wsl2_unavailable" }
    }
    $item = Get-Item -LiteralPath $wslPath
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        return [ordered]@{ path = $wslPath; status = "NO-GO"; reason_code = "wsl2_executable_reparse_point" }
    }
    return [ordered]@{ path = $item.FullName; status = "GO"; reason_code = "wsl2_executable_ok" }
}

$paths = Ensure-ImmoAppRuntimeLayout
if ([string]::IsNullOrWhiteSpace($OutputJson)) {
    $OutputJson = Join-Path $paths.LogsRoot "managed_wsl2_runtime_bootstrap_evidence.json"
}
if ([string]::IsNullOrWhiteSpace($ProviderConfigPath)) {
    $ProviderConfigPath = Get-ImmoAppHubRuntimeProviderConfigPath
}

$reasonCode = "managed_wsl2_runtime_bootstrap_not_go"
$proofResult = "NO-GO"
$provider = $null
$providerConfigSha = ""
$bootstrapCommandPath = ""
$runtimeIdentity = $null
$actualDistroName = ""
$runtimeIdentityStatus = "NO-GO"
$containerEngineStatus = "NO-GO"
$composeStatus = "NO-GO"
$composeCliStatus = "NO-GO"
$serviceStatus = "NO-GO"
$services = @()
$bootstrapOutput = ""
$bootstrapExitCode = 999
$bootstrapTimedOut = $false
$bootstrapTimeoutSeconds = 30
$bootstrapElapsedSeconds = 0.0
$identityTimeoutOverride = [Environment]::GetEnvironmentVariable("IMMOAPP_MANAGED_WSL2_IDENTITY_TIMEOUT_SECONDS")
if (-not [string]::IsNullOrWhiteSpace($identityTimeoutOverride)) {
    $parsedIdentityTimeout = 0
    if ([int]::TryParse($identityTimeoutOverride, [ref]$parsedIdentityTimeout) -and $parsedIdentityTimeout -gt 0) {
        $bootstrapTimeoutSeconds = $parsedIdentityTimeout
    }
}

$wsl = Get-ApprovedWslPath
$wslStatus = [string]$wsl.status
$distroPresent = $false
if ($wslStatus -eq "GO") {
    $distrosText = (& ([string]$wsl.path) -l -q 2>$null | Out-String).Replace([string][char]0, "")
    $distroPresent = @($distrosText -split "(`r`n|`n|`r)" | ForEach-Object { [string]$_.Trim() } | Where-Object { $_ }).Contains($ExpectedDistroName)
}

try {
    if (-not (Test-Path -LiteralPath $ProviderConfigPath -PathType Leaf)) {
        throw "managed_wsl2_runtime_artifact_provider_missing|Managed WSL2 artifact provider config is missing."
    }
    $providerConfigSha = Get-ImmoAppFileSha256 -Path $ProviderConfigPath
    $provider = Get-Content -LiteralPath $ProviderConfigPath -Raw | ConvertFrom-Json
    if ([string](Get-ImmoAppObjectValue -Data $provider -Name "runtime_dependency_mode") -ne "managed_wsl2_container_runtime_artifact") {
        throw "managed_wsl2_runtime_artifact_provider_missing|Active provider is not managed_wsl2_container_runtime_artifact."
    }
    $expectedFromProvider = [string](Get-ImmoAppObjectValue -Data $provider -Name "expected_distro_name")
    if (-not [string]::IsNullOrWhiteSpace($expectedFromProvider)) {
        $ExpectedDistroName = $expectedFromProvider
    }
    if ($wslStatus -ne "GO") {
        throw "$($wsl.reason_code)|Approved WSL executable is not available."
    }
    if (-not $distroPresent) {
        throw "managed_wsl2_runtime_distribution_missing|The expected ImmoAppRuntime WSL distribution is not installed."
    }
    $bootstrapCommandPath = [string](Get-ImmoAppObjectValue -Data $provider -Name "managed_bootstrap_command_path")
    if ([string]::IsNullOrWhiteSpace($bootstrapCommandPath) -or -not (Test-Path -LiteralPath $bootstrapCommandPath -PathType Leaf)) {
        throw "managed_wsl2_runtime_bootstrap_command_missing|Managed WSL2 runtime bootstrap command is missing."
    }
    $command = Invoke-ManagedRuntimeCommand -Path $bootstrapCommandPath -TimeoutSeconds $bootstrapTimeoutSeconds
    $bootstrapExitCode = [int]$command.exit_code
    $bootstrapOutput = [string]$command.output
    $bootstrapTimedOut = [bool]$command.timed_out
    $bootstrapElapsedSeconds = [double]$command.elapsed_seconds
    if ($bootstrapTimedOut) {
        throw "managed_wsl2_runtime_identity_timeout|Managed WSL2 runtime identity command timed out."
    }
    if ($bootstrapExitCode -ne 0) {
        try {
            $failedIdentity = $bootstrapOutput | ConvertFrom-Json
            $failedReason = [string](Get-ImmoAppObjectValue -Data $failedIdentity -Name "reason_code")
            if (-not [string]::IsNullOrWhiteSpace($failedReason)) {
                throw "$failedReason|Managed WSL2 runtime identity command failed."
            }
        }
        catch {
            if ([string]$_.Exception.Message -match "^[a-z0-9_]+\|") {
                throw
            }
        }
        throw "managed_wsl2_runtime_identity_command_failed|Managed WSL2 runtime identity command failed."
    }
    $runtimeIdentity = $bootstrapOutput | ConvertFrom-Json
    if ([string](Get-ImmoAppObjectValue -Data $runtimeIdentity -Name "kind") -ne "immoapp_managed_wsl2_runtime_identity") {
        throw "managed_wsl2_runtime_identity_invalid|Managed WSL2 runtime identity has the wrong kind."
    }
    if ([int](Get-ImmoAppObjectValue -Data $runtimeIdentity -Name "schema_version") -ne 1) {
        throw "managed_wsl2_runtime_identity_invalid|Managed WSL2 runtime identity has an unsupported schema_version."
    }
    $actualDistroName = [string](Get-ImmoAppObjectValue -Data $runtimeIdentity -Name "distro_name")
    if ($actualDistroName -ne $ExpectedDistroName) {
        throw "managed_wsl2_runtime_identity_mismatch|Managed WSL2 runtime identity does not match expected distro."
    }
    $runtimeIdentityStatus = "GO"
    $containerEngineStatus = [string](Get-ImmoAppObjectValue -Data $runtimeIdentity -Name "container_engine_status")
    $composeStatus = [string](Get-ImmoAppObjectValue -Data $runtimeIdentity -Name "compose_status")
    $composeCliStatus = [string](Get-ImmoAppObjectValue -Data $runtimeIdentity -Name "compose_cli_status")
    if ([string]::IsNullOrWhiteSpace($composeCliStatus)) { $composeCliStatus = $composeStatus }
    $serviceStatus = [string](Get-ImmoAppObjectValue -Data $runtimeIdentity -Name "service_status")
    $services = @(Get-ImmoAppObjectValue -Data $runtimeIdentity -Name "services")
    if ($containerEngineStatus -ne "GO") {
        throw "managed_wsl2_container_engine_not_go|Managed WSL2 container engine is not GO."
    }
    if ($composeStatus -ne "GO") {
        throw "managed_wsl2_compose_not_go|Managed WSL2 compose is not GO."
    }
    if ([string]::IsNullOrWhiteSpace($serviceStatus)) {
        $serviceStatus = "GO"
    }
    $proofResult = "GO"
    $reasonCode = "managed_wsl2_runtime_identity_go"
}
catch {
    $message = $_.Exception.Message
    if ($message -match "^(?<code>[a-z0-9_]+)\|") {
        $reasonCode = $Matches["code"]
    }
    else {
        $reasonCode = "managed_wsl2_runtime_bootstrap_failed"
    }
}

$payload = [ordered]@{
    kind = "immoapp_managed_wsl2_runtime_bootstrap_evidence"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    expected_distro_name = $ExpectedDistroName
    actual_distro_name = $actualDistroName
    wsl_executable_path = [string]$wsl.path
    wsl_executable_status = $wslStatus
    distro_present = [bool]$distroPresent
    provider_config_path = $ProviderConfigPath
    provider_config_sha256 = $providerConfigSha
    managed_bootstrap_command_path = $bootstrapCommandPath
    bootstrap_exit_code = $bootstrapExitCode
    bootstrap_timeout_seconds = $bootstrapTimeoutSeconds
    bootstrap_elapsed_seconds = $bootstrapElapsedSeconds
    bootstrap_timed_out = $bootstrapTimedOut
    bootstrap_output = $bootstrapOutput
    runtime_identity_status = $runtimeIdentityStatus
    runtime_identity = $runtimeIdentity
    container_engine_status = $containerEngineStatus
    compose_cli_status = $composeCliStatus
    compose_status = $composeStatus
    service_status = $serviceStatus
    services = @($services)
    proof_result = $proofResult
    reason_code = $reasonCode
    agency_install_status = "NO_GO"
    public_beta_status = "NO_GO"
}

$write = Write-ImmoAppSafeJson -Path $OutputJson -Payload $payload -ApprovedRoots @($paths.LogsRoot, $paths.ConfigRoot, $paths.TmpRoot) -Depth 12
$payload["evidence_path"] = [string]$OutputJson
$payload["evidence_sha256"] = [string]$write.sha256
$payload | ConvertTo-Json -Depth 12
if ($proofResult -ne "GO") { exit 1 }
