[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet("managed_container_runtime", "managed_wsl2_container_runtime_candidate", "managed_wsl2_container_runtime_artifact")]
    [string]$RuntimeDependencyMode = "managed_container_runtime",
    [string]$RuntimeExecutablePath = "",
    [string]$ComposeExecutablePath = "",
    [string]$InstallRoot = "",
    [string]$DataRoot = "",
    [string]$LogsRoot = "",
    [string]$ManagedServiceName = "",
    [string]$PackageInventoryJson = "",
    [string]$RuntimeArtifactInventoryJson = "",
    [string]$WslPolicyJsonPath = "",
    [string]$WslConfigPlanJsonPath = "",
    [string]$SourceCommitSha = "",
    [string]$InstallerSha256 = "",
    [switch]$ConfirmManagedRuntimeProof,
    [switch]$AllowTestOnlyPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

$providerPath = Get-ImmoAppHubRuntimeProviderConfigPath
$providerLock = $null
$writeProvider = $false
try {
    if (-not $WhatIfPreference) {
        $providerLock = Enter-ImmoAppProviderMutationLock -TimeoutSeconds 60
        $writeProvider = $PSCmdlet.ShouldProcess($providerPath, "write managed Hub runtime provider config")
    }

    $result = Invoke-ImmoAppManagedRuntimeProviderRegistration `
        -RuntimeDependencyMode $RuntimeDependencyMode `
        -RuntimeExecutablePath $RuntimeExecutablePath `
        -ComposeExecutablePath $ComposeExecutablePath `
        -InstallRoot $InstallRoot `
        -DataRoot $DataRoot `
        -LogsRoot $LogsRoot `
        -ManagedServiceName $ManagedServiceName `
        -PackageInventoryJson $PackageInventoryJson `
        -RuntimeArtifactInventoryJson $RuntimeArtifactInventoryJson `
        -WslPolicyJsonPath $WslPolicyJsonPath `
        -WslConfigPlanJsonPath $WslConfigPlanJsonPath `
        -SourceCommitSha $SourceCommitSha `
        -InstallerSha256 $InstallerSha256 `
        -ProviderLock $providerLock `
        -WriteProvider:$writeProvider `
        -WhatIfMode:$WhatIfPreference `
        -ConfirmManagedRuntimeProof:$ConfirmManagedRuntimeProof `
        -AllowTestOnlyPath:$AllowTestOnlyPath
}
finally {
    if ($null -ne $providerLock) {
        Exit-ImmoAppProviderMutationLock -Lock $providerLock
    }
}

$result | ConvertTo-Json -Depth 10
