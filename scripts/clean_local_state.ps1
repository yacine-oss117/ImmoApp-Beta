param(
    [switch]$PurgeToolCaches
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

$repoRoot = Get-ImmoAppRepoRoot
$cacheRoot = Join-Path $repoRoot ".cache"
$targets = @((Join-Path $cacheRoot "root-scratch"))

if ($PurgeToolCaches) {
    $targets += @(
        (Join-Path $cacheRoot "mypy"),
        (Join-Path $cacheRoot "pytest"),
        (Join-Path $cacheRoot "ruff")
    )
}

foreach ($target in $targets) {
    if (-not (Test-Path $target)) {
        continue
    }
    Get-ChildItem -LiteralPath $target -Force | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force
    }
    Write-Host "Cleaned $target"
}
