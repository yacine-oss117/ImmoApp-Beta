param(
    [switch]$ValidateOnly,
    [string]$DesktopUserSid = ""
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

if ([string]::IsNullOrWhiteSpace($DesktopUserSid)) {
    $DesktopUserSid = Get-ImmoAppDesktopUserSid
}
$env:IMMOAPP_DESKTOP_USER_SID = $DesktopUserSid

if (-not $ValidateOnly -and (Test-ImmoAppUsingCanonicalRuntimeRoot) -and -not (Test-ImmoAppIsAdministrator)) {
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -DesktopUserSid `"$DesktopUserSid`""
    $process = Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -WorkingDirectory (Get-ImmoAppRepoRoot) -Verb RunAs -Wait -PassThru
    if ($null -eq $process -or $process.ExitCode -ne 0) {
        throw "Windows administrator permission was not granted or bootstrap failed."
    }
    exit 0
}

$repoRoot = Get-ImmoAppRepoRoot
$runtimePaths = Get-ImmoAppRuntimePaths
$serverRequirements = Join-Path $repoRoot "requirements\server.txt"
$clientRequirements = Join-Path $repoRoot "requirements\client.txt"
$bootstrapScript = Join-Path $PSScriptRoot "bootstrap_local_runtime.ps1"

function Get-BootstrapDirectoryTargets {
    param([hashtable]$Paths)

    return @(
        $Paths.AppDataRoot,
        $Paths.ConfigRoot,
        $Paths.SecretsRoot,
        $Paths.DataRoot,
        $Paths.DataPgRoot,
        $Paths.DataRabbitMqRoot,
        $Paths.DataValkeyRoot,
        $Paths.DataMinioRoot,
        $Paths.DataClamAvRoot,
        $Paths.DataCaddyRoot,
        $Paths.DataCaddyDataRoot,
        $Paths.DataCaddyConfigRoot,
        $Paths.DataAppRoot,
        $Paths.DataAppCacheRoot,
        $Paths.DataAppMediaRoot,
        $Paths.DataAppStaticRoot,
        $Paths.DataAppLogsRoot,
        $Paths.DataAppBackupsRoot,
        $Paths.DataAppConfigRoot,
        $Paths.DataAppToolsRoot,
        $Paths.DataAppTmpRoot,
        $Paths.VenvsRoot,
        $Paths.ToolsRoot,
        $Paths.CacheRoot,
        $Paths.PycacheRoot,
        $Paths.LogsRoot,
        $Paths.MediaRoot,
        $Paths.TmpRoot,
        $Paths.BackupsRoot,
        $Paths.ImportsRoot,
        $Paths.OfflineSyncRoot,
        $Paths.ApiWriteQueueRoot
    )
}

function Write-StatusLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    Write-Host ("{0,-18} {1}" -f ($Label + ":"), $Value)
}

Write-Host "ImmoApp local runtime bootstrap" -ForegroundColor Cyan
Write-StatusLine -Label "Repo" -Value $repoRoot
Write-StatusLine -Label "ProgramData" -Value $runtimePaths.AppDataRoot
Write-StatusLine -Label "Mode" -Value $(if ($ValidateOnly) { "validate-only" } else { "bootstrap" })

$pythonCommand = Get-ImmoAppPython314Command
Write-StatusLine -Label "Python 3.14" -Value $pythonCommand.DisplayName

foreach ($requirementsPath in @($serverRequirements, $clientRequirements)) {
    if (-not (Test-Path $requirementsPath)) {
        throw "Requirements file not found: $requirementsPath"
    }
}

$directoryTargets = Get-BootstrapDirectoryTargets -Paths $runtimePaths
$missingDirectories = @($directoryTargets | Where-Object { -not (Test-Path $_) })

$envState = Initialize-ImmoAppEnvFileFromTemplate -ValidateOnly
$secretState = Initialize-ImmoAppBootstrapSecretsFile -ValidateOnly
$serverVenvState = Ensure-ImmoAppVenv -Kind server -RequirementsPath $serverRequirements -ValidateOnly
$clientVenvState = Ensure-ImmoAppVenv -Kind client -RequirementsPath $clientRequirements -ValidateOnly

if (-not $ValidateOnly) {
    $null = Ensure-ImmoAppRuntimeLayout
    $envState = Initialize-ImmoAppEnvFileFromTemplate
    $secretState = Initialize-ImmoAppBootstrapSecretsFile
    $serverVenvState = Ensure-ImmoAppVenv -Kind server -RequirementsPath $serverRequirements
    $clientVenvState = Ensure-ImmoAppVenv -Kind client -RequirementsPath $clientRequirements
    Repair-ImmoAppHostRuntimePermissions -DesktopUserSid $DesktopUserSid
    # Re-apply the stricter bootstrap-secret file ACL after the broader desktop
    # runtime grants have repaired existing ProgramData children.
    $secretState = Initialize-ImmoAppBootstrapSecretsFile
}

if ($missingDirectories.Count -gt 0) {
    Write-Host ""
    Write-Host "Runtime directories:" -ForegroundColor Yellow
    foreach ($path in $missingDirectories) {
        $action = if ($ValidateOnly) { "would create" } else { "created if missing" }
        Write-Host " - $action $path"
    }
}

Write-Host ""
Write-Host "Bootstrap files:" -ForegroundColor Yellow
Write-Host " - env file: $($envState.Path) ($(if ($envState.Created) { if ($ValidateOnly) { 'would create' } else { 'created' } } else { 'already present' }))"
Write-Host " - bootstrap secrets: $($secretState.Path) ($(if ($secretState.Created) { if ($ValidateOnly) { 'would create' } else { 'created' } } else { 'already present' }))"

Write-Host ""
Write-Host "Virtual environments:" -ForegroundColor Yellow
Write-Host " - server: $($serverVenvState.PythonPath) ($(if ($serverVenvState.Created) { if ($ValidateOnly) { 'would create/sync' } else { 'created/synced' } } else { if ($ValidateOnly) { 'would sync existing venv' } else { 'synced existing venv' } }))"
Write-Host " - client: $($clientVenvState.PythonPath) ($(if ($clientVenvState.Created) { if ($ValidateOnly) { 'would create/sync' } else { 'created/synced' } } else { if ($ValidateOnly) { 'would sync existing venv' } else { 'synced existing venv' } }))"

$envIssues = @()
if (Test-Path $envState.Path) {
    $envIssues = @(Get-ImmoAppEnvPlaceholderIssues -EnvFilePath $envState.Path)
}

if ($envIssues.Count -gt 0) {
    Write-Host ""
    Write-Warning "The canonical env file still contains operator-edit values."
    foreach ($issue in $envIssues) {
        Write-Host " - $($issue.Key): $($issue.Message)"
    }
}
else {
    Write-Host ""
    Write-Host "Canonical env file has no unresolved required operator-edit placeholders." -ForegroundColor Green
}

if ($ValidateOnly) {
    Write-Host ""
    Write-Host "Validation completed with no repo mutations." -ForegroundColor Green
    return
}

Write-Host ""
Write-Host "Bootstrap completed." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Edit $($envState.Path) and replace the required operator-edit values."
Write-Host "  2. powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-infra -UseWindowsVolumes"
Write-Host "  3. powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_openbao_identity.ps1"
Write-Host "  4. powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action sync-secrets -UseWindowsVolumes"
