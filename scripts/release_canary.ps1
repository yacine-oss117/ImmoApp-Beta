param(
    [Parameter(Mandatory = $true)][string]$NewImage,
    [string]$PreviousImage = "",
    [string]$ComposeFile = "",
    [string]$ProjectName = "immoapp",
    [string]$HealthUrl = "http://127.0.0.1:8000/api/v1/health/",
    [int]$HealthTimeoutSeconds = 120,
    [switch]$SkipLiveSmoke
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

$primaryCompose = Get-ImmoAppComposeFile -Name "compose.yml"
if (-not $ComposeFile) {
    $ComposeFile = $primaryCompose
}

$composeFileArgs = (Get-ImmoAppComposeProjectArgs) + @("-f", $ComposeFile)
if ($ComposeFile -eq $primaryCompose -and (Test-ImmoAppWindowsVolumeMode)) {
    $composeFileArgs += @("-f", (Get-ImmoAppComposeFile -Name "compose.windows.yml"))
}

function Get-ServiceImage([string]$serviceName) {
    $containerId = (docker compose @composeFileArgs -p $ProjectName ps -q $serviceName).Trim()
    if (-not $containerId) {
        return ""
    }
    $image = (docker inspect --format "{{.Config.Image}}" $containerId 2>$null)
    if ($LASTEXITCODE -ne 0) {
        return ""
    }
    return ($image | Out-String).Trim()
}

function Wait-Healthy([string]$url, [int]$timeoutSeconds) {
    $deadline = (Get-Date).AddSeconds([Math]::Max(10, $timeoutSeconds))
    do {
        try {
            $response = Invoke-WebRequest -Uri $url -TimeoutSec 5 -UseBasicParsing
            if ($response.StatusCode -eq 200) {
                return $true
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)
    return $false
}

if (-not $NewImage.Trim()) {
    throw "NewImage must not be empty."
}

$baselineImage = $PreviousImage.Trim()
if (-not $baselineImage) {
    $baselineImage = Get-ServiceImage "web"
}
if (-not $baselineImage) {
    throw "Could not resolve previous image. Pass -PreviousImage explicitly."
}

Write-Host "[CANARY] Baseline image: $baselineImage" -ForegroundColor DarkGray
Write-Host "[CANARY] Candidate image: $NewImage" -ForegroundColor DarkGray

$env:IMMOAPP_APP_IMAGE = $NewImage

Write-Host "[CANARY] Pulling candidate image (if remote)..." -ForegroundColor Yellow
docker compose @composeFileArgs -p $ProjectName pull web worker beat

Write-Host "[CANARY] Rolling canary web instance..." -ForegroundColor Yellow
docker compose @composeFileArgs -p $ProjectName up -d --no-deps web
if ($LASTEXITCODE -ne 0) {
    throw "Failed to start canary web service."
}

if (-not (Wait-Healthy -url $HealthUrl -timeoutSeconds $HealthTimeoutSeconds)) {
    Write-Host "[CANARY] Health failed; triggering rollback." -ForegroundColor Red
    & (Join-Path $PSScriptRoot "release_rollback.ps1") `
        -PreviousImage $baselineImage `
        -ComposeFile $ComposeFile `
        -ProjectName $ProjectName `
        -HealthUrl $HealthUrl `
        -HealthTimeoutSeconds $HealthTimeoutSeconds
    if ($LASTEXITCODE -ne 0) {
        throw "Canary failed and rollback did not recover."
    }
    throw "Canary health check failed; rolled back."
}

if (-not $SkipLiveSmoke) {
    Write-Host "[CANARY] Running live auth smoke..." -ForegroundColor Yellow
    $clientPython = Get-ImmoAppVenvPython -Kind client
    $serverPython = Get-ImmoAppVenvPython -Kind server
    if (-not (Test-Path $clientPython) -or -not (Test-Path $serverPython)) {
        throw "Required venv Python not found for live smoke."
    }
    & $clientPython scripts/check_live_auth_smoke.py --server-python $serverPython --seed
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[CANARY] Live smoke failed; triggering rollback." -ForegroundColor Red
        & (Join-Path $PSScriptRoot "release_rollback.ps1") `
            -PreviousImage $baselineImage `
            -ComposeFile $ComposeFile `
            -ProjectName $ProjectName `
            -HealthUrl $HealthUrl `
            -HealthTimeoutSeconds $HealthTimeoutSeconds
        if ($LASTEXITCODE -ne 0) {
            throw "Canary smoke failed and rollback did not recover."
        }
        throw "Canary smoke failed; rolled back."
    }
}

Write-Host "[CANARY] Canary succeeded; rolling worker and beat..." -ForegroundColor Yellow
docker compose @composeFileArgs -p $ProjectName up -d --no-deps worker beat
if ($LASTEXITCODE -ne 0) {
    Write-Host "[CANARY] worker/beat rollout failed; triggering rollback." -ForegroundColor Red
    & (Join-Path $PSScriptRoot "release_rollback.ps1") `
        -PreviousImage $baselineImage `
        -ComposeFile $ComposeFile `
        -ProjectName $ProjectName `
        -HealthUrl $HealthUrl `
        -HealthTimeoutSeconds $HealthTimeoutSeconds
    if ($LASTEXITCODE -ne 0) {
        throw "Canary finalize failed and rollback did not recover."
    }
    throw "Canary finalize failed; rolled back."
}

Write-Host "[CANARY] Release succeeded." -ForegroundColor Green
