param(
    [string]$Duration = "120s",
    [switch]$Build,
    [string]$OutputTag = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

if (-not $OutputTag) {
    $OutputTag = Get-Date -Format "yyyyMMddHHmmss"
}

$tiers = @(
    @{ name = "tier1"; tenants = 100; rows = 400; rate = 60; pre = 60; max = 220; rebuild = 2; active_managers = 40; active_owners = 8 },
    @{ name = "tier2"; tenants = 250; rows = 250; rate = 75; pre = 75; max = 260; rebuild = 2; active_managers = 80; active_owners = 16 },
    @{ name = "tier3"; tenants = 500; rows = 150; rate = 90; pre = 90; max = 320; rebuild = 2; active_managers = 120; active_owners = 24 },
    @{ name = "tier4"; tenants = 1000; rows = 100; rate = 110; pre = 110; max = 380; rebuild = 2; active_managers = 200; active_owners = 40 }
)

$results = @()
$didBuild = $false
foreach ($tier in $tiers) {
    $tag = "{0}_{1}" -f $OutputTag, $tier.name
    $args = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "scripts/run_perf.ps1",
        "-Profile", "custom",
        "-Tag", $tag,
        "-Duration", $Duration,
        "-Tenants", ([string]$tier.tenants),
        "-RowsPerTenant", ([string]$tier.rows),
        "-ActiveManagers", ([string]$tier.active_managers),
        "-ActiveOwners", ([string]$tier.active_owners),
        "-ReadRate", ([string]$tier.rate),
        "-ReadPreAllocatedVUs", ([string]$tier.pre),
        "-ReadMaxVUs", ([string]$tier.max),
        "-RebuildVUs", ([string]$tier.rebuild),
        "-DbLatencyMs", "30",
        "-DbJitterMs", "10",
        "-DbDownstreamBandwidthKbps", "2048",
        "-RabbitLatencyMs", "20",
        "-RabbitJitterMs", "8",
        "-ReadP95Ms", "700",
        "-ReadP99Ms", "1400",
        "-HttpFailedRate", "0.02"
    )
    if ($Build -and -not $didBuild) {
        $args += "-Build"
        $didBuild = $true
    }

    Write-Host ("[capacity] running {0}: tenants={1} rows={2} rate={3}" -f $tier.name, $tier.tenants, $tier.rows, $tier.rate) -ForegroundColor Cyan
    & powershell @args
    if ($LASTEXITCODE -ne 0) {
        throw "Capacity tier failed to execute: $($tier.name)"
    }

    $reportPath = Join-Path $repoRoot ("scripts/perf_outputs/perf_report_{0}.json" -f $tag)
    $report = Get-Content -Path $reportPath -Raw | ConvertFrom-Json
    $results += [pscustomobject]@{
        tier = $tier.name
        tag = $tag
        tenants = $tier.tenants
        rows_per_tenant = $tier.rows
        active_managers = $tier.active_managers
        active_owners = $tier.active_owners
        read_rate = $tier.rate
        read_p95_ms = [double]$report.slo.read_p95_ms.value
        read_p99_ms = [double]$report.slo.read_p99_ms.value
        read_p95_pass = [bool]$report.slo.read_p95_ms.pass
        read_p99_pass = [bool]$report.slo.read_p99_ms.pass
        http_failed_rate = [double]$report.slo.http_failed_rate.value
        http_failed_pass = [bool]$report.slo.http_failed_rate.pass
    }
}

$summaryPath = Join-Path $repoRoot ("scripts/perf_outputs/capacity_matrix_{0}.json" -f $OutputTag)
$results | ConvertTo-Json -Depth 5 | Set-Content -Path $summaryPath -Encoding UTF8
Write-Host ("[capacity] summary written: {0}" -f $summaryPath) -ForegroundColor Green
$results | Format-Table -AutoSize
