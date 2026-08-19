$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")
Set-ImmoAppSecurityEnv

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Script
    )
    & $Script
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

$clientPython = Get-ImmoAppVenvPython -Kind client
if (-not (Test-Path $clientPython)) {
    throw "Client venv python not found at $clientPython"
}

Invoke-Step "pytest app/tests/ui_tests" { & $clientPython -m pytest app\tests\ui_tests }
