[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$RuntimeExecutablePath,
    [string]$ComposeExecutablePath = "",
    [string]$PackageInventoryJson = "",
    [string]$SourceCommitSha = "",
    [string]$InstallerSha256 = "",
    [switch]$AllowTestRuntime,
    [switch]$ConfirmManagedRuntimeProof
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

if (-not $ConfirmManagedRuntimeProof) {
    throw "install_managed_hub_runtime_provider.ps1 requires -ConfirmManagedRuntimeProof."
}
if (-not $AllowTestRuntime -and [string]::IsNullOrWhiteSpace($PackageInventoryJson)) {
    throw "Production managed runtime provider requires -PackageInventoryJson."
}

[Console]::Error.WriteLine("WARNING: install_managed_hub_runtime_provider.ps1 is deprecated; delegating to register_managed_hub_runtime_provider.ps1 for identical validation.")

$paths = Ensure-ImmoAppRuntimeLayout
$args = @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    (Join-Path $PSScriptRoot "register_managed_hub_runtime_provider.ps1"),
    "-RuntimeExecutablePath",
    $RuntimeExecutablePath,
    "-InstallRoot",
    $paths.RuntimeRoot,
    "-DataRoot",
    $paths.DataRoot,
    "-LogsRoot",
    $paths.LogsRoot,
    "-ConfirmManagedRuntimeProof"
)
if (-not [string]::IsNullOrWhiteSpace($ComposeExecutablePath)) {
    $args += @("-ComposeExecutablePath", $ComposeExecutablePath)
}
if (-not [string]::IsNullOrWhiteSpace($PackageInventoryJson)) {
    $args += @("-PackageInventoryJson", $PackageInventoryJson)
}
if (-not [string]::IsNullOrWhiteSpace($SourceCommitSha)) {
    $args += @("-SourceCommitSha", $SourceCommitSha)
}
if (-not [string]::IsNullOrWhiteSpace($InstallerSha256)) {
    $args += @("-InstallerSha256", $InstallerSha256)
}
if ($AllowTestRuntime) {
    $args += "-AllowTestOnlyPath"
}
if ($WhatIfPreference) {
    $args += "-WhatIf"
}

& powershell @args
exit $LASTEXITCODE
