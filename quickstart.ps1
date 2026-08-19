param(
    [string]$DesktopUserSid = "",
    [switch]$BootstrapOnly,
    [string]$BootstrapLogPath = "",
    [switch]$DetachClient
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$repoRoot = $PSScriptRoot
Set-Location $repoRoot

function Write-Step {
    param(
        [int]$Number,
        [int]$Total,
        [string]$Text
    )
    Write-Host ""
    Write-Host ("[{0}/{1}] {2}" -f $Number, $Total, $Text) -ForegroundColor Cyan
}

function Test-IsAdministrator {
    try {
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
        return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
    }
    catch {
        return $false
    }
}

function Get-DesktopUserSid {
    if (-not [string]::IsNullOrWhiteSpace($DesktopUserSid) -and $DesktopUserSid.Trim() -match '^S-\d(?:-\d+)+$') {
        return $DesktopUserSid.Trim()
    }
    try {
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
        if ($identity -and $identity.User -and -not [string]::IsNullOrWhiteSpace($identity.User.Value)) {
            return [string]$identity.User.Value
        }
    }
    catch {
    }
    throw "Could not resolve the Windows desktop user SID."
}

function New-RandomHex {
    param([int]$Bytes = 32)
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($buffer)
    }
    finally {
        $rng.Dispose()
    }
    return (($buffer | ForEach-Object { $_.ToString("x2") }) -join "")
}

function New-RandomBase64 {
    param([int]$Bytes = 32)
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($buffer)
    }
    finally {
        $rng.Dispose()
    }
    return [Convert]::ToBase64String($buffer)
}

function Get-DotEnvValue {
    param(
        [string]$Path,
        [string]$Name
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }
    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = [string]$rawLine
        if ($line -match ("^\s*" + [Regex]::Escape($Name) + "\s*=(.*)$")) {
            return [string]$Matches[1]
        }
    }
    return ""
}

function Set-DotEnvValue {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )
    $lines = @(Get-Content -LiteralPath $Path)
    $pattern = "^\s*" + [Regex]::Escape($Name) + "\s*="
    $found = $false
    $updated = New-Object System.Collections.Generic.List[string]

    foreach ($rawLine in $lines) {
        $line = [string]$rawLine
        if ($line -match $pattern) {
            $updated.Add("$Name=$Value")
            $found = $true
        }
        else {
            $updated.Add($line)
        }
    }

    if (-not $found) {
        $updated.Add("$Name=$Value")
    }

    $utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
    [System.IO.File]::WriteAllLines($Path, $updated.ToArray(), $utf8NoBom)
}

function Ensure-BetaEnvValue {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value,
        [string[]]$InvalidMarkers = @("<REPLACE_ME", "<BASE64_32_BYTES>")
    )

    $current = (Get-DotEnvValue -Path $Path -Name $Name).Trim()
    $needsValue = [string]::IsNullOrWhiteSpace($current)
    foreach ($marker in $InvalidMarkers) {
        if (-not [string]::IsNullOrWhiteSpace($marker) -and $current.Contains($marker)) {
            $needsValue = $true
            break
        }
    }

    if ($needsValue) {
        Set-DotEnvValue -Path $Path -Name $Name -Value $Value
        return $Value
    }
    return $current
}

function Get-BetaBootstrapStatePath {
    return "C:\ProgramData\ImmoApp\config\beta_quickstart_state.json"
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Test-DirectoryWritable {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $false
    }
    $probe = Join-Path $Path (".immoapp-quickstart-write-{0}-{1}.tmp" -f $PID, [Guid]::NewGuid().ToString("N"))
    try {
        [System.IO.File]::WriteAllText($probe, "ok", [System.Text.UTF8Encoding]::new($false))
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
        return $true
    }
    catch {
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
        return $false
    }
}

function Test-BetaBootstrapCurrent {
    $statePath = Get-BetaBootstrapStatePath
    $serverRequirements = Join-Path $repoRoot "requirements\server.txt"
    $clientRequirements = Join-Path $repoRoot "requirements\client.txt"
    $serverPython = "C:\ProgramData\ImmoApp\venvs\server\Scripts\python.exe"
    $clientPython = "C:\ProgramData\ImmoApp\venvs\client\Scripts\python.exe"
    $envPath = "C:\ProgramData\ImmoApp\config\.env.local"

    foreach ($requiredPath in @($statePath, $serverRequirements, $clientRequirements, $serverPython, $clientPython, $envPath)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            return $false
        }
    }
    foreach ($writableRoot in @(
        "C:\ProgramData\ImmoApp\config",
        "C:\ProgramData\ImmoApp\logs",
        "C:\ProgramData\ImmoApp\cache"
    )) {
        if (-not (Test-DirectoryWritable -Path $writableRoot)) {
            return $false
        }
    }

    try {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        if ([int]$state.schema_version -ne 1) { return $false }
        if ([string]$state.python_version -ne "3.14") { return $false }
        if ([string]$state.server_requirements_sha256 -ne (Get-FileSha256 -Path $serverRequirements)) { return $false }
        if ([string]$state.client_requirements_sha256 -ne (Get-FileSha256 -Path $clientRequirements)) { return $false }
        return $true
    }
    catch {
        return $false
    }
}

function Invoke-BetaDockerText {
    param([Parameter(Mandatory = $true)][string[]]$DockerArgs)

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 promotes native stderr lines to ErrorRecord
        # objects. Docker uses stderr for normal progress, so normalize every
        # item to plain text and decide success only from the native exit code.
        $ErrorActionPreference = "Continue"
        $raw = & docker --context desktop-linux @DockerArgs 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    $global:LASTEXITCODE = $exitCode
    return @(
        $raw | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                [string]$_.Exception.Message
            }
            else {
                [string]$_
            }
        }
    )
}

function Test-BetaNonEmptyFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    try {
        return -not [string]::IsNullOrWhiteSpace([System.IO.File]::ReadAllText($Path))
    }
    catch {
        return $false
    }
}

function Repair-BetaOrphanedOpenBaoState {
    # OpenBao keeps its encrypted storage in Docker named volumes while the
    # local Beta keeps its unseal/admin credentials under ProgramData. If a
    # user removes containers or ProgramData independently, Docker can retain
    # an initialized OpenBao volume whose credentials no longer exist. That
    # state is unusable and causes openbao-init to fail on the next first run.
    # For the local evaluation build only, a missing token/unseal pair means
    # the OpenBao state must be treated as fresh and any orphaned OpenBao
    # containers/volumes for this Compose project are safely discarded.
    $tokenFile = "C:\ProgramData\ImmoApp\secrets\openbao.token"
    $unsealFile = "C:\ProgramData\ImmoApp\secrets\openbao.unseal"
    if ((Test-BetaNonEmptyFile -Path $tokenFile) -and (Test-BetaNonEmptyFile -Path $unsealFile)) {
        return
    }

    $projectName = if ([string]::IsNullOrWhiteSpace($env:COMPOSE_PROJECT_NAME)) {
        "immoapp-beta"
    }
    else {
        $env:COMPOSE_PROJECT_NAME
    }

    $removedAnything = $false
    foreach ($service in @("openbao-init", "openbao-seed", "openbao")) {
        # Force the *filtered pipeline result* to stay an array. Windows
        # PowerShell 5.1 otherwise unwraps a single matching container to a
        # scalar string; under StrictMode that makes `$ids.Count` fail.
        $ids = @(@(Invoke-BetaDockerText -DockerArgs @(
            "ps", "-aq",
            "--filter", "label=com.docker.compose.project=$projectName",
            "--filter", "label=com.docker.compose.service=$service"
        )) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        if ($ids.Count -gt 0) {
            $null = Invoke-BetaDockerText -DockerArgs (@("rm", "-f") + $ids)
            if ($LASTEXITCODE -ne 0) {
                throw "Could not remove stale local OpenBao container state for service '$service'."
            }
            $removedAnything = $true
        }
    }

    foreach ($logicalVolume in @("openbao_data", "openbao_logs")) {
        $volumes = @(@(Invoke-BetaDockerText -DockerArgs @(
            "volume", "ls", "-q",
            "--filter", "label=com.docker.compose.project=$projectName",
            "--filter", "label=com.docker.compose.volume=$logicalVolume"
        )) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        if ($volumes.Count -eq 0) {
            # Compose-created named volumes normally carry labels, but keep a
            # deterministic-name fallback for volumes created by older Compose
            # versions or partially migrated local setups.
            $candidate = "${projectName}_${logicalVolume}"
            $null = Invoke-BetaDockerText -DockerArgs @("volume", "inspect", $candidate)
            if ($LASTEXITCODE -eq 0) {
                $volumes = @($candidate)
            }
        }
        foreach ($volume in $volumes) {
            $null = Invoke-BetaDockerText -DockerArgs @("volume", "rm", "-f", $volume)
            if ($LASTEXITCODE -ne 0) {
                throw "Could not remove stale local OpenBao volume '$volume'."
            }
            $removedAnything = $true
        }
    }

    if ($removedAnything) {
        Write-Host "OK  Recovered orphaned local OpenBao state from an earlier/partial run" -ForegroundColor Yellow
    }
}

function Write-BetaBootstrapState {
    $statePath = Get-BetaBootstrapStatePath
    $serverRequirements = Join-Path $repoRoot "requirements\server.txt"
    $clientRequirements = Join-Path $repoRoot "requirements\client.txt"
    $state = [ordered]@{
        schema_version = 1
        python_version = "3.14"
        server_requirements_sha256 = (Get-FileSha256 -Path $serverRequirements)
        client_requirements_sha256 = (Get-FileSha256 -Path $clientRequirements)
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    $json = $state | ConvertTo-Json -Depth 4
    $utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
    [System.IO.File]::WriteAllText($statePath, $json + [Environment]::NewLine, $utf8NoBom)
}

Write-Host "========================================" -ForegroundColor DarkCyan
Write-Host "          ImmoApp Beta Quick Start" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor DarkCyan
Write-Host ""
Write-Host "This script prepares a local Beta environment and launches the desktop app."
Write-Host "No manual .env editing, database setup, or secret entry is required."
Write-Host "The first run may take several minutes because Docker images and Python packages are downloaded."

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "ImmoApp Beta quick start currently supports Windows 10/11 only."
}

$DesktopUserSid = Get-DesktopUserSid
$env:IMMOAPP_DESKTOP_USER_SID = $DesktopUserSid
# Keep Docker state stable even when the ZIP is extracted into a differently named folder.
if ([string]::IsNullOrWhiteSpace($env:COMPOSE_PROJECT_NAME)) {
    $env:COMPOSE_PROJECT_NAME = "immoapp-beta"
}

if ($BootstrapOnly) {
    if (-not (Test-IsAdministrator)) {
        throw "The Quick Start bootstrap helper must run with Windows administrator permission."
    }
    if ([string]::IsNullOrWhiteSpace($BootstrapLogPath)) {
        $BootstrapLogPath = Join-Path $env:TEMP ("ImmoApp-Beta-bootstrap-{0}.log" -f $PID)
    }
    try {
        & (Join-Path $repoRoot "scripts\bootstrap_local_runtime.ps1") -DesktopUserSid $DesktopUserSid *> $BootstrapLogPath
        Write-BetaBootstrapState
        exit 0
    }
    catch {
        try {
            ($_ | Out-String) | Add-Content -LiteralPath $BootstrapLogPath -Encoding UTF8
        }
        catch {
        }
        exit 1
    }
}

Write-Step -Number 1 -Total 5 -Text "Checking Python 3.14 and Docker Desktop"

$python314Found = $false
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.14 --version *> $null
    if ($LASTEXITCODE -eq 0) {
        $python314Found = $true
    }
}
if (-not $python314Found -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $pythonVersion = (& python --version 2>&1 | Out-String).Trim()
    if ($pythonVersion -match "^Python 3\.14(\.|$)") {
        $python314Found = $true
    }
}
if (-not $python314Found) {
    throw "Python 3.14 was not found. Install Python 3.14, then run quickstart.ps1 again."
}
Write-Host "OK  Python 3.14"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop was not found. Install Docker Desktop, start it, then run quickstart.ps1 again."
}

& docker --context desktop-linux info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is installed but its Linux engine is not ready. Start Docker Desktop and wait until it says it is running, then try again."
}
& docker --context desktop-linux compose version *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose is not available through Docker Desktop. Update Docker Desktop, then try again."
}
Write-Host "OK  Docker Desktop"

Write-Step -Number 2 -Total 5 -Text "Preparing isolated Python environments"
$quickStartLog = "C:\ProgramData\ImmoApp\logs\beta-quickstart.log"
$bootstrapLog = Join-Path $env:TEMP ("ImmoApp-Beta-bootstrap-{0}.log" -f $PID)
$bootstrapNeeded = -not (Test-BetaBootstrapCurrent)

if ($bootstrapNeeded) {
    Write-Host "The first run or a dependency change may spend a few minutes installing Python packages."
    try {
        if (Test-IsAdministrator) {
            & (Join-Path $repoRoot "scripts\bootstrap_local_runtime.ps1") -DesktopUserSid $DesktopUserSid *> $bootstrapLog
            Write-BetaBootstrapState
        }
        else {
            Write-Host "Windows will ask once for permission to prepare C:\ProgramData\ImmoApp." -ForegroundColor Yellow
            Write-Host "The desktop application itself will continue as your normal Windows user."
            $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -DesktopUserSid `"$DesktopUserSid`" -BootstrapOnly -BootstrapLogPath `"$bootstrapLog`""
            $process = Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -WorkingDirectory $repoRoot -Verb RunAs -WindowStyle Hidden -Wait -PassThru
            if ($null -eq $process -or $process.ExitCode -ne 0) {
                throw "Windows administrator permission was not granted or the local runtime bootstrap failed."
            }
        }
    }
    catch {
        Write-Host ""
        Write-Host "Setup failed. Last log lines:" -ForegroundColor Red
        if (Test-Path -LiteralPath $bootstrapLog) {
            Get-Content -LiteralPath $bootstrapLog -Tail 40
        }
        throw
    }
}
else {
    Write-Host "OK  Existing Python environments match this repository; no UAC prompt is needed."
}

$quickStartLogDir = Split-Path -Parent $quickStartLog
New-Item -ItemType Directory -Path $quickStartLogDir -Force | Out-Null
if (Test-Path -LiteralPath $bootstrapLog) {
    Copy-Item -LiteralPath $bootstrapLog -Destination $quickStartLog -Force
    Remove-Item -LiteralPath $bootstrapLog -Force -ErrorAction SilentlyContinue
}
elseif (-not (Test-Path -LiteralPath $quickStartLog)) {
    [System.IO.File]::WriteAllText($quickStartLog, "ImmoApp Beta Quick Start`r`n", [System.Text.UTF8Encoding]::new($false))
}
Write-Host "OK  Server and desktop-client virtual environments ready"

$envFile = "C:\ProgramData\ImmoApp\config\.env.local"
if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Quick start could not find the local environment file at $envFile."
}

Write-Step -Number 3 -Total 5 -Text "Generating local-only Beta credentials"

$postgresPassword = Ensure-BetaEnvValue -Path $envFile -Name "POSTGRES_PASSWORD" -Value (New-RandomHex -Bytes 24)
$postgresAdminPassword = Ensure-BetaEnvValue -Path $envFile -Name "POSTGRES_ADMIN_PASSWORD" -Value (New-RandomHex -Bytes 24)
$rabbitPassword = Ensure-BetaEnvValue -Path $envFile -Name "RABBITMQ_PASSWORD" -Value (New-RandomHex -Bytes 24)
$minioPassword = Ensure-BetaEnvValue -Path $envFile -Name "MINIO_ROOT_PASSWORD" -Value (New-RandomHex -Bytes 24)
$storageSecret = Ensure-BetaEnvValue -Path $envFile -Name "STORAGE_SECRET_KEY" -Value $minioPassword
$kmsValue = Ensure-BetaEnvValue -Path $envFile -Name "MINIO_KMS_SECRET_KEY" -Value ("immoapp-kms-key:" + (New-RandomBase64 -Bytes 32))

# OpenBao stores application secrets, not runtime network topology. Older Beta
# env files allowed VALKEY_URL/CHANNEL_LAYER_URL to be loaded from OpenBao.
# Those host-local URLs (localhost:6379) can overwrite the Docker service
# endpoints (valkey:6379) inside containers. Normalize the allowlist on every
# Quick Start run so existing installations self-heal as well as fresh ones.
$betaSecretsAllowlist = "ALE_,DJANGO_,IMMOAPP_,POSTGRES_,RABBITMQ_,CELERY_BROKER_URL,MINIO_,STORAGE_,SIGNOZ_,JWT_"
Set-DotEnvValue -Path $envFile -Name "IMMOAPP_SECRETS_ALLOWLIST" -Value $betaSecretsAllowlist
$env:IMMOAPP_SECRETS_ALLOWLIST = $betaSecretsAllowlist

# Docker Compose gives process environment variables precedence over --env-file values.
# Export the exact Beta values here so stack.ps1 cannot replace them with its
# internal bootstrap fallbacks during this one-command evaluation path.
$env:POSTGRES_PASSWORD = $postgresPassword
$env:POSTGRES_ADMIN_PASSWORD = $postgresAdminPassword
$env:RABBITMQ_PASSWORD = $rabbitPassword
$env:MINIO_ROOT_PASSWORD = $minioPassword
$env:STORAGE_SECRET_KEY = $storageSecret
$env:MINIO_KMS_SECRET_KEY = $kmsValue

Write-Host "OK  Local-only infrastructure credentials generated automatically"
Write-Host "    They stay on this machine under C:\ProgramData\ImmoApp."

Repair-BetaOrphanedOpenBaoState

Write-Step -Number 4 -Total 5 -Text "Starting the complete local backend"
Write-Host "Docker will download/build what is missing. The first run can take several minutes."
try {
    & (Join-Path $repoRoot "scripts\stack.ps1") -Action up -UseWindowsVolumes *>> $quickStartLog
}
catch {
    Write-Host ""
    Write-Host "Backend setup failed. Last log lines:" -ForegroundColor Red
    if (Test-Path -LiteralPath $quickStartLog) {
        Get-Content -LiteralPath $quickStartLog -Tail 40
    }
    Write-Host ""
    Write-Host "Container diagnostics:" -ForegroundColor Yellow
    foreach ($service in @("openbao-init", "openbao-seed")) {
        $ids = @(Invoke-BetaDockerText -DockerArgs @(
            "ps", "-aq",
            "--filter", "label=com.docker.compose.project=$($env:COMPOSE_PROJECT_NAME)",
            "--filter", "label=com.docker.compose.service=$service"
        )) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        foreach ($id in $ids) {
            Write-Host "--- $service ($id) ---"
            Invoke-BetaDockerText -DockerArgs @("logs", "--tail", "60", $id) | ForEach-Object { Write-Host $_ }
        }
    }
    throw
}

$healthUrl = "http://127.0.0.1:8000/api/v1/health/"
$deadline = (Get-Date).AddSeconds(60)
$healthy = $false
while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            break
        }
    }
    catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $healthy) {
    throw "The backend started, but the health check did not return HTTP 200 at $healthUrl."
}
Write-Host "OK  Backend healthy at $healthUrl"

Write-Step -Number 5 -Total 5 -Text "Launching ImmoApp Beta"
Write-Host ""
Write-Host "Beta demo login" -ForegroundColor Green
Write-Host "  Username: owner"
Write-Host "  Password: admin"
Write-Host ""
Write-Host "These credentials exist only in the local development database created by the Beta quick start."
Write-Host "Closing the desktop window does not delete your local Beta data."
Write-Host ""

$clientScript = Join-Path $repoRoot "scripts\run_client.ps1"
if ($DetachClient) {
    $clientArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$clientScript`" -BaseUrl `"http://127.0.0.1:8000`""
    $clientProcess = Start-Process -FilePath "powershell.exe" -ArgumentList $clientArguments -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
    Start-Sleep -Milliseconds 1500
    if ($clientProcess.HasExited) {
        Write-Host ""
        Write-Host "The desktop client exited during startup." -ForegroundColor Red
        $appLog = "C:\ProgramData\ImmoApp\logs\app.log"
        if (Test-Path -LiteralPath $appLog) {
            Write-Host "Last application log lines:" -ForegroundColor Yellow
            Get-Content -LiteralPath $appLog -Tail 30
        }
        throw "ImmoApp Beta did not remain running. Run scripts\run_client.ps1 manually for detailed console diagnostics."
    }
    Write-Host "OK  ImmoApp Beta launched. This setup window can close."
    return
}

& $clientScript -BaseUrl "http://127.0.0.1:8000"
