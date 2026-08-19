param(
    [string]$OutputJson = "",
    [string]$ProviderConfigPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

$args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "detect_hub_runtime.ps1"))
if ($ProviderConfigPath) { $args += @("-ProviderConfigPath", $ProviderConfigPath) }
$runtimeText = & powershell @args
if ($LASTEXITCODE -ne 0) { throw "Hub runtime detection failed." }
$runtime = (($runtimeText | Out-String) | ConvertFrom-Json)

$providerMode = [string](Get-ImmoAppObjectValue -Data $runtime.provider -Name "provider_mode")
$proofOnly = ([string](Get-ImmoAppObjectValue -Data $runtime.provider -Name "proof_only")).ToLowerInvariant() -in @("true", "1")
$internalStatus = [string](Get-ImmoAppObjectValue -Data $runtime -Name "internal_proof_status")
$agencyStatus = [string](Get-ImmoAppObjectValue -Data $runtime -Name "agency_install_status")
$isManaged = ([string]$runtime.runtime_dependency_mode -eq "managed_container_runtime" -and $providerMode -eq "managed_container_runtime")
$proofResult = if ($isManaged -and $internalStatus -eq "GO") { "GO" } else { "NO-GO" }
$reasonCode = if ($proofResult -eq "GO") {
    if ($proofOnly) { "managed_runtime_proof_provider_verified" } else { "managed_runtime_provider_verified" }
} elseif ([string]$runtime.reason_code) {
    [string]$runtime.reason_code
} else {
    "managed_runtime_provider_missing"
}

$evidence = [ordered]@{
    kind = "immoapp_managed_hub_runtime_provider_verification"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    proof_result = $proofResult
    reason_code = $reasonCode
    failure_reason = if ($proofResult -eq "GO") { "" } else { [string]$runtime.reason }
    runtime_dependency_mode = [string]$runtime.runtime_dependency_mode
    provider_mode = $providerMode
    provider_config_path = [string]$runtime.provider_config_path
    provider_config_valid = [bool]$runtime.provider_config_valid
    proof_only = $proofOnly
    internal_proof_status = $internalStatus
    agency_install_status = $agencyStatus
    runtime_detection = $runtime
}

if ($OutputJson) {
    $parent = Split-Path -Parent $OutputJson
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $evidence | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputJson -Encoding UTF8
}
$evidence | ConvertTo-Json -Depth 12
if ($proofResult -ne "GO") {
    exit 1
}
