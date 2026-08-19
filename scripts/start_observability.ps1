$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")
$RepoRoot = Get-ImmoAppRepoRoot

Push-Location $RepoRoot
try {
    $composeArgs = (Get-ImmoAppComposeProjectArgs) + (Get-ImmoAppComposeArgs -Names @("compose.observability.yml"))
    & docker compose @composeArgs up -d
} finally {
    Pop-Location
}
