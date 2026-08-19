param(
    [string]$EnvFile = "C:\ProgramData\ImmoApp\config\.env.local",
    [switch]$SkipDbDump,
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

function Normalize-PathString {
    param([string]$Value)
    $normalized = ($Value -replace "\\", "/").Trim()
    while ($normalized.EndsWith("/")) {
        $normalized = $normalized.Substring(0, $normalized.Length - 1)
    }
    return $normalized.ToLowerInvariant()
}

function To-DockerHostPath {
    param([string]$PathValue)
    $full = [System.IO.Path]::GetFullPath($PathValue)
    return ($full -replace "\\", "/")
}

function Invoke-Docker {
    param([string[]]$Args)
    & docker @Args
    if ($LASTEXITCODE -ne 0) {
        throw "docker command failed: docker $($Args -join ' ')"
    }
}

function Invoke-Compose {
    param([string[]]$Args)
    Invoke-Docker -Args (@("compose") + $script:ComposeArgs + $Args)
}

function Get-ComposeVolumeName {
    param([string]$LogicalName)
    $name = (
        & docker volume ls `
            --filter "label=com.docker.compose.project=$script:ProjectName" `
            --filter "label=com.docker.compose.volume=$LogicalName" `
            --format "{{.Name}}"
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to query docker volume list for '$LogicalName'"
    }
    return ($name | Select-Object -First 1).Trim()
}

function Get-VolumeOptions {
    param([string]$VolumeName)
    if (-not $VolumeName) {
        return $null
    }
    $inspect = & docker volume inspect $VolumeName | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to inspect volume '$VolumeName'"
    }
    return $inspect[0].Options
}

function Ensure-Directory {
    param([string]$PathValue)
    if (-not (Test-Path -LiteralPath $PathValue)) {
        New-Item -ItemType Directory -Path $PathValue -Force | Out-Null
    }
}

function Copy-VolumeContentToHost {
    param(
        [string]$VolumeName,
        [string]$HostPath
    )
    Ensure-Directory -PathValue $HostPath
    $hostPathDocker = To-DockerHostPath -PathValue $HostPath
    Invoke-Docker -Args @(
        "run",
        "--rm",
        "-v", "$VolumeName`:/from:ro",
        "-v", "$hostPathDocker`:/to",
        "busybox:1.36",
        "sh",
        "-ec",
        "mkdir -p /to && cd /from && tar cf - . | (cd /to && tar xpf -)"
    )
}

function Clear-DirectoryContent {
    param([string]$PathValue)
    if (-not (Test-Path -LiteralPath $PathValue)) {
        return
    }
    Get-ChildItem -LiteralPath $PathValue -Force | Remove-Item -Recurse -Force
}

$script:RepoRoot = Get-ImmoAppRepoRoot
$script:ProjectName = if ($env:COMPOSE_PROJECT_NAME) {
    $env:COMPOSE_PROJECT_NAME.Trim()
}
else {
    (Split-Path -Leaf $script:RepoRoot).ToLowerInvariant()
}
$script:ComposeArgs = (Get-ImmoAppComposeProjectArgs) + @("--env-file", $EnvFile) + (Get-ImmoAppComposeArgs -Names @("compose.yml", "compose.windows.yml"))

Write-Host "Project: $script:ProjectName"
Write-Host "Repo:    $script:RepoRoot"
Write-Host "Env:     $EnvFile"

Set-Location $script:RepoRoot

$volumeTargets = [ordered]@{
    "pgdata"        = "C:\ProgramData\ImmoApp\data\pgdata"
    "rabbitmq_data" = "C:\ProgramData\ImmoApp\data\rabbitmq"
    "valkey_data"   = "C:\ProgramData\ImmoApp\data\valkey"
    "minio_data"    = "C:\ProgramData\ImmoApp\data\minio"
    "clamav_data"   = "C:\ProgramData\ImmoApp\data\clamav"
    "app_data"      = "C:\ProgramData\ImmoApp\data\app"
    "caddy_data"    = "C:\ProgramData\ImmoApp\data\caddy\data"
    "caddy_config"  = "C:\ProgramData\ImmoApp\data\caddy\config"
}

$mismatched = @()
foreach ($logicalName in $volumeTargets.Keys) {
    $expectedPath = $volumeTargets[$logicalName]
    $volumeName = Get-ComposeVolumeName -LogicalName $logicalName
    if (-not $volumeName) {
        continue
    }
    $options = Get-VolumeOptions -VolumeName $volumeName
    $expectedNorm = Normalize-PathString -Value $expectedPath
    $actualDevice = if ($options) { [string]$options.device } else { "" }
    $actualNorm = Normalize-PathString -Value $actualDevice
    $isBind = $options -and ($options.o -eq "bind") -and ($options.type -eq "none")
    if (-not $isBind -or $actualNorm -ne $expectedNorm) {
        $mismatched += [pscustomobject]@{
            LogicalName   = $logicalName
            VolumeName    = $volumeName
            ExpectedPath  = $expectedPath
            ActualDevice  = $actualDevice
            IsBind        = [bool]$isBind
        }
    }
}

if (-not $mismatched) {
    Write-Host "No mismatched volumes found. Nothing to migrate." -ForegroundColor Green
    exit 0
}

Write-Host "Found mismatched volumes:" -ForegroundColor Yellow
$mismatched | ForEach-Object {
    Write-Host " - $($_.LogicalName): $($_.VolumeName) (actual='$($_.ActualDevice)', expected='$($_.ExpectedPath)')"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupRoot = "C:\ProgramData\ImmoApp\backups\volume_mismatch_fix_$stamp"
Ensure-Directory -PathValue $backupRoot
Ensure-Directory -PathValue (Join-Path $backupRoot "volumes")
Ensure-Directory -PathValue (Join-Path $backupRoot "targets_before")

if (-not $SkipDbDump) {
    try {
        Write-Host "Creating DB dump backup..." -ForegroundColor Cyan
        Invoke-Compose -Args @(
            "exec",
            "-T",
            "db",
            "sh",
            "-lc",
            "pg_dump -U `"$POSTGRES_USER`" -d `"$POSTGRES_DB`" -Fc -f /tmp/pre_volume_fix.dump"
        )
        $dbContainer = (& docker compose @($script:ComposeArgs) ps -q db).Trim()
        if ($dbContainer) {
            Invoke-Docker -Args @(
                "cp",
                "$dbContainer`:/tmp/pre_volume_fix.dump",
                (Join-Path $backupRoot "pre_volume_fix.dump")
            )
        }
    }
    catch {
        Write-Warning "DB dump backup failed: $($_.Exception.Message)"
    }
}

Write-Host "Stopping compose stack (containers only; volumes retained)..." -ForegroundColor Cyan
Invoke-Compose -Args @("down")

foreach ($entry in $mismatched) {
    $logicalName = [string]$entry.LogicalName
    $volumeName = [string]$entry.VolumeName
    $targetPath = [string]$entry.ExpectedPath

    Write-Host "Migrating $logicalName ($volumeName)..." -ForegroundColor Cyan

    $volumeBackupPath = Join-Path (Join-Path $backupRoot "volumes") $logicalName
    Ensure-Directory -PathValue $volumeBackupPath
    Copy-VolumeContentToHost -VolumeName $volumeName -HostPath $volumeBackupPath

    Ensure-Directory -PathValue $targetPath
    $targetHasData = (Get-ChildItem -LiteralPath $targetPath -Force -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0
    if ($targetHasData) {
        $targetBackupPath = Join-Path (Join-Path $backupRoot "targets_before") $logicalName
        Ensure-Directory -PathValue $targetBackupPath
        Write-Host " - Backing up existing target content for $logicalName"
        $targetPathDocker = To-DockerHostPath -PathValue $targetPath
        $targetBackupDocker = To-DockerHostPath -PathValue $targetBackupPath
        Invoke-Docker -Args @(
            "run",
            "--rm",
            "-v", "$targetPathDocker`:/from:ro",
            "-v", "$targetBackupDocker`:/to",
            "busybox:1.36",
            "sh",
            "-ec",
            "mkdir -p /to && cd /from && tar cf - . | (cd /to && tar xpf -)"
        )
        Clear-DirectoryContent -PathValue $targetPath
    }

    Copy-VolumeContentToHost -VolumeName $volumeName -HostPath $targetPath
    Invoke-Docker -Args @("volume", "rm", $volumeName)
}

if (-not $NoRestart) {
    Write-Host "Recreating stack with windows bind-volume compose config..." -ForegroundColor Cyan
    Invoke-Compose -Args @("up", "-d")
}

Write-Host "Verifying migrated volumes..." -ForegroundColor Cyan
foreach ($logicalName in $volumeTargets.Keys) {
    $expectedPath = $volumeTargets[$logicalName]
    $volumeName = Get-ComposeVolumeName -LogicalName $logicalName
    if (-not $volumeName) {
        throw "Expected volume '$logicalName' was not recreated."
    }
    $options = Get-VolumeOptions -VolumeName $volumeName
    if (-not $options -or $options.o -ne "bind" -or $options.type -ne "none") {
        throw "Volume '$volumeName' is not bind-configured after migration."
    }
    $actualNorm = Normalize-PathString -Value ([string]$options.device)
    $expectedNorm = Normalize-PathString -Value $expectedPath
    if ($actualNorm -ne $expectedNorm) {
        throw "Volume '$volumeName' device mismatch after migration: '$($options.device)' != '$expectedPath'"
    }
}

Write-Host "Volume mismatch migration complete." -ForegroundColor Green
Write-Host "Backup root: $backupRoot"
