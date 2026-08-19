param(
    [ValidateSet("fast", "pr", "full", "nightly")]
    [string]$Stage = "pr"
)

$ErrorActionPreference = "Stop"

$stageScript = Join-Path $PSScriptRoot ("scripts/checks_{0}.ps1" -f $Stage)
if (-not (Test-Path $stageScript)) {
    throw "Unknown checks stage '$Stage'. Missing script: $stageScript"
}

Write-Host ("Running checks stage: {0}" -f $Stage) -ForegroundColor Cyan
& $stageScript
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
