[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$ConfirmManagedRuntimeProviderRemoval
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

if (-not $ConfirmManagedRuntimeProviderRemoval) {
    throw "uninstall_managed_hub_runtime_provider.ps1 requires -ConfirmManagedRuntimeProviderRemoval."
}

$providerPath = Assert-ImmoAppProviderSnapshotPathSafe -Path (Get-ImmoAppHubRuntimeProviderConfigPath) -AllowNonCanonical
$removed = $false
if (Test-Path -LiteralPath $providerPath) {
    if ($PSCmdlet.ShouldProcess($providerPath, "remove Hub runtime provider config")) {
        Remove-Item -LiteralPath $providerPath -Force
        $removed = $true
    }
}

[ordered]@{
    kind = "immoapp_managed_hub_runtime_provider_uninstall"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    provider_config_path = $providerPath
    removed_provider_config = $removed
    removed_runtime_data = $false
    proof_result = "GO"
} | ConvertTo-Json -Depth 8
