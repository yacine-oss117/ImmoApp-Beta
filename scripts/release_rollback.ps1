param(
    [Parameter(Mandatory = $true)][string]$PreviousImage,
    [string]$ComposeFile = "",
    [string]$ProjectName = "immoapp",
    [string]$HealthUrl = "http://127.0.0.1:8000/api/v1/health/",
    [int]$HealthTimeoutSeconds = 90
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

if (-not $PreviousImage.Trim()) {
    throw "PreviousImage must not be empty."
}

Write-Host "[ROLLBACK] Setting IMMOAPP_APP_IMAGE=$PreviousImage" -ForegroundColor Yellow
$env:IMMOAPP_APP_IMAGE = $PreviousImage

Write-Host "[ROLLBACK] Restarting web/worker/beat with previous image..." -ForegroundColor Yellow
docker compose @composeFileArgs -p $ProjectName up -d web worker beat
if ($LASTEXITCODE -ne 0) {
    throw "Rollback compose up failed."
}

$deadline = (Get-Date).AddSeconds([Math]::Max(10, $HealthTimeoutSeconds))
do {
    try {
        $response = Invoke-WebRequest -Uri $HealthUrl -TimeoutSec 5 -UseBasicParsing
        if ($response.StatusCode -eq 200) {
            Write-Host "[ROLLBACK] Health check passed." -ForegroundColor Green
            Write-Host "[ROLLBACK] Complete." -ForegroundColor Green
            exit 0
        }
    }
    catch {
        Start-Sleep -Seconds 2
    }
} while ((Get-Date) -lt $deadline)

throw "Rollback completed but health endpoint did not recover within timeout."
