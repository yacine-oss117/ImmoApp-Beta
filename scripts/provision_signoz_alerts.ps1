param(
    [string]$EnvFile = "",
    [string]$BaseUrl = "",
    [string]$ConfigPath = "",
    [switch]$DryRun,
    [switch]$EnsurePat
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")
if (-not $EnvFile) {
    $EnvFile = Get-ImmoAppDefaultEnvFile
}
if (-not $ConfigPath) {
    $ConfigPath = Join-Path (Join-Path (Get-ImmoAppDeploymentRoot) "docker") "signoz\provisioning\alerts.json"
}
if (-not (Test-Path $EnvFile)) {
    throw "Env file not found: $EnvFile"
}

function Import-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path $Path)) {
        return
    }

    foreach ($rawLine in Get-Content -Path $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }

        $sep = $line.IndexOf("=")
        if ($sep -le 0) {
            continue
        }

        $name = $line.Substring(0, $sep).Trim()
        $value = $line.Substring($sep + 1).Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        Set-Item -Path "Env:$name" -Value $value
    }
}

$repoRoot = Get-ImmoAppRepoRoot
Push-Location $repoRoot
try {
    Import-DotEnv -Path $EnvFile

    if ($BaseUrl) {
        $env:SIGNOZ_URL = $BaseUrl
    }

    $python = Get-ImmoAppVenvPython -Kind server
    if (-not (Test-Path $python)) {
        throw "Server venv Python not found at: $python"
    }

    $args = @(
        "scripts/provision_signoz_alerts.py",
        "--config", $ConfigPath
    )
    if ($DryRun) { $args += "--dry-run" }
    if ($EnsurePat) { $args += "--ensure-pat" }

    & $python @args
    if ($LASTEXITCODE -ne 0) {
        throw "provision_signoz_alerts.py failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
