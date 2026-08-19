param(
    [string]$DesktopUserSid = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "Runtime permission repair is only required on Windows."
}

if ([string]::IsNullOrWhiteSpace($DesktopUserSid)) {
    $DesktopUserSid = Get-ImmoAppDesktopUserSid
}

if (-not (Test-ImmoAppIsAdministrator)) {
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -DesktopUserSid `"$DesktopUserSid`""
    $process = Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -WorkingDirectory (Get-ImmoAppRepoRoot) -Verb RunAs -Wait -PassThru
    if ($null -eq $process -or $process.ExitCode -ne 0) {
        throw "Windows administrator permission was not granted or the runtime permission repair failed."
    }
    exit 0
}

$env:IMMOAPP_DESKTOP_USER_SID = $DesktopUserSid
$paths = Ensure-ImmoAppRuntimeLayout
Repair-ImmoAppHostRuntimePermissions -DesktopUserSid $DesktopUserSid
Initialize-ImmoAppBootstrapSecretsFile | Out-Null

Write-Host "ImmoApp runtime permissions repaired for SID $DesktopUserSid" -ForegroundColor Green
Write-Host "Writable desktop roots: config, runtime, logs, cache, tools, media, tmp, backups, imports, offline_sync, api_write_queue"
Write-Host "The local secrets root remains scoped to the desktop owner, SYSTEM, and administrators through the bootstrap/identity helpers."
