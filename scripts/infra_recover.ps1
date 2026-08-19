param(
    [string]$EnvFile = "",
    [switch]$NoWindowsVolumes,
    [switch]$HardResetPgData,
    [switch]$SkipRebuildApp,
    [switch]$SeedAdmin,
    [string]$AdminUser = "admin",
    [string]$AdminPassword = "admin",
    [switch]$SkipVolumeMismatchFix,
    [switch]$RunPrChecks,
    [switch]$RunFullChecks
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

if (-not $EnvFile) {
    $EnvFile = Get-ImmoAppDefaultEnvFile
}
if (-not (Test-Path $EnvFile)) {
    throw "Env file not found: $EnvFile"
}

$repoRoot = Get-ImmoAppRepoRoot
Set-Location $repoRoot

$composeNames = @("compose.yml")
if (-not $NoWindowsVolumes) {
    $composeNames += "compose.windows.yml"
}
$composeFiles = Get-ImmoAppComposeArgs -Names $composeNames
$script:ComposeArgs = (Get-ImmoAppComposeProjectArgs) + @("--env-file", $EnvFile) + $composeFiles

function Invoke-Compose {
    param([Parameter(Mandatory = $true)][string[]]$ComposeCmd)
    if ($ComposeCmd.Count -eq 0) {
        throw "Invoke-Compose called without a subcommand."
    }
    & docker compose @script:ComposeArgs @ComposeCmd
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed: $($ComposeCmd -join ' ')"
    }
}

function Wait-ServiceReady {
    param(
        [Parameter(Mandatory = $true)][string]$Service,
        [int]$TimeoutSec = 240
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $containerId = (& docker compose @script:ComposeArgs ps -q $Service).Trim()
        if (-not $containerId) {
            Start-Sleep -Seconds 2
            continue
        }
        $status = (& docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" $containerId).Trim()
        if ($LASTEXITCODE -ne 0) {
            Start-Sleep -Seconds 2
            continue
        }
        if ($status -in @("healthy", "running")) {
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "Service '$Service' did not become ready within ${TimeoutSec}s."
}

Write-Host "Infra recover start"
Write-Host "Repo:    $repoRoot"
Write-Host "Env:     $EnvFile"
Write-Host "Volumes: $(if ($NoWindowsVolumes) { 'deployment/compose/compose.yml only' } else { 'deployment/compose/compose.yml + deployment/compose/compose.windows.yml' })"

Write-Host "`n[1/7] Stopping stack..."
Invoke-Compose @("down", "--remove-orphans")

if ($HardResetPgData) {
    Write-Host "[2/7] Hard reset pgdata (with backup)..."
    $appDataRoot = Get-ImmoAppAppDataRoot
    $pgdataPath = Join-Path $appDataRoot "data\pgdata"
    $backupRoot = Join-Path $appDataRoot ("backups\pgdata_reinit_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    if (Test-Path -LiteralPath $pgdataPath) {
        Move-Item -LiteralPath $pgdataPath -Destination (Join-Path $backupRoot "pgdata_old")
    }
    New-Item -ItemType Directory -Path $pgdataPath -Force | Out-Null
    Write-Host "PGDATA backup: $backupRoot"
}
else {
    Write-Host "[2/7] Hard reset pgdata skipped."
}

if (-not $SkipVolumeMismatchFix) {
    Write-Host "[3/7] Checking/fixing windows bind-volume mismatch..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "fix_windows_volume_bind_mismatch.ps1") -EnvFile $EnvFile -NoRestart
    if ($LASTEXITCODE -ne 0) {
        throw "fix_windows_volume_bind_mismatch.ps1 failed."
    }
}
else {
    Write-Host "[3/7] Volume mismatch fix skipped."
}

Write-Host "[4/7] Starting infra + OpenBao init/seed..."
Invoke-Compose @("up", "-d", "db", "rabbitmq", "valkey", "minio", "minio-init", "clamav", "openbao", "openbao-init", "openbao-seed", "app-data-init")
Wait-ServiceReady -Service "db" -TimeoutSec 300
Wait-ServiceReady -Service "rabbitmq" -TimeoutSec 300
Wait-ServiceReady -Service "valkey" -TimeoutSec 180
Wait-ServiceReady -Service "minio" -TimeoutSec 300
Wait-ServiceReady -Service "clamav" -TimeoutSec 420
Wait-ServiceReady -Service "openbao" -TimeoutSec 300

if (-not $SkipRebuildApp) {
    Write-Host "[5/7] Rebuilding app images (web/worker/beat)..."
    Invoke-Compose @("build", "web", "worker", "beat")
}
else {
    Write-Host "[5/7] Rebuild skipped."
}

Write-Host "[6/7] Recreating app services..."
Invoke-Compose @("up", "-d", "--force-recreate", "web", "worker", "beat", "caddy")
Wait-ServiceReady -Service "web" -TimeoutSec 300

Write-Host "[7/7] Preparing DB schema..."
Invoke-Compose @("exec", "-T", "web", "python", "server/manage.py", "immoapp_db_prepare")
Invoke-Compose @("exec", "-T", "web", "python", "-m", "alembic", "current")

if ($SeedAdmin) {
    Write-Host "Seeding/updating admin user..."
    $adminShell = "from django.contrib.auth import get_user_model;U=get_user_model();u=U.objects.filter(username='$AdminUser').first() or U(username='$AdminUser', email='${AdminUser}@example.com');created=(u.pk is None);u.is_staff=True;u.is_superuser=True;u.role='super_admin';u.set_password('$AdminPassword');u.save(validate=False);print('admin_user', 'created' if created else 'updated')"
    Invoke-Compose @("exec", "-T", "web", "python", "server/manage.py", "shell", "-c", $adminShell)
}

$health = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8000/api/v1/health/" -TimeoutSec 10
if ($health.StatusCode -ne 200) {
    throw "Health probe failed with HTTP $($health.StatusCode)."
}
Write-Host "Health check: HTTP $($health.StatusCode)"

if ($RunPrChecks) {
    Write-Host "Running PR checks..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "checks.ps1") -Stage pr
    if ($LASTEXITCODE -ne 0) {
        throw "PR checks failed."
    }
}

if ($RunFullChecks) {
    Write-Host "Running FULL checks..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "checks.ps1") -Stage full
    if ($LASTEXITCODE -ne 0) {
        throw "FULL checks failed."
    }
}

Write-Host "`nInfra recovery completed successfully."
