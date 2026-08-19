param(
    [string]$Tag = "chaos_short",
    [int]$Tenants = 50,
    [int]$RowsPerTenant = 300,
    [string]$Duration = "120s",
    [int]$ReadRate = 45,
    [int]$ReadPreAllocatedVUs = 45,
    [int]$ReadMaxVUs = 180,
    [int]$RebuildVUs = 2,
    [int]$DbLatencyMs = 60,
    [int]$DbJitterMs = 30,
    [int]$RabbitLatencyMs = 30,
    [int]$RabbitJitterMs = 12
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

powershell -ExecutionPolicy Bypass -File ".\scripts\run_perf.ps1" `
  -Profile custom `
  -Tenants $Tenants `
  -RowsPerTenant $RowsPerTenant `
  -ReadRate $ReadRate `
  -ReadPreAllocatedVUs $ReadPreAllocatedVUs `
  -ReadMaxVUs $ReadMaxVUs `
  -RebuildVUs $RebuildVUs `
  -Duration $Duration `
  -DbLatencyMs $DbLatencyMs `
  -DbJitterMs $DbJitterMs `
  -RabbitLatencyMs $RabbitLatencyMs `
  -RabbitJitterMs $RabbitJitterMs `
  -Tag $Tag

if ($LASTEXITCODE -ne 0) {
  throw "Short chaos validation failed."
}
