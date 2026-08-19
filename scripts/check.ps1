param(
    [ValidateSet("fast", "pr", "full", "nightly")]
    [string]$Stage = "pr"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path $PSScriptRoot -Parent
& "$repoRoot\\checks.ps1" -Stage $Stage
