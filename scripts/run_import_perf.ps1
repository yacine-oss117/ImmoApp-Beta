param(
    [ValidateSet("custom", "quick", "quick_create", "quick_review", "medium_create", "medium_review", "baseline", "contention", "chaos")]
    [string]$Profile = "baseline",
    [int]$Tenants = 12,
    [int]$SeedRowsPerTenant = 400,
    [int]$ImportsPerTenant = 1,
    [int]$RowsPerImport = 800,
    [int]$Concurrency = 6,
    [int]$ImportWorkerReplicas = 1,
    [ValidateSet("demande", "offer", "child_mix")]
    [string]$Scenario = "child_mix",
    [int]$ReviewEvery = 0,
    [string]$DuplicateStrategy = "skip",
    [double]$PreviewFraction = 0.0,
    [double]$PollIntervalSeconds = 0.5,
    [double]$TimeoutSeconds = 600.0,
    [int]$DbLatencyMs = 8,
    [int]$DbJitterMs = 3,
    [int]$DbDownstreamBandwidthKbps = 0,
    [int]$RabbitLatencyMs = 6,
    [int]$RabbitJitterMs = 2,
    [string]$Tag = "",
    [switch]$Build,
    [switch]$KeepData,
    [switch]$KeepStack
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not $Tag) {
    $Tag = Get-Date -Format "yyyyMMddHHmmss"
}

$outputDir = Join-Path $repoRoot "scripts/perf_outputs"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

$seedFile = Join-Path $outputDir ("import_perf_users_{0}.json" -f $Tag)
$reportFile = Join-Path $outputDir ("import_perf_report_{0}.json" -f $Tag)

$composeArgs = (Get-ImmoAppComposeProjectArgs) + (Get-ImmoAppComposeArgs -Names @("compose.yml", "compose.perf.yml"))

function Apply-ImportPerfProfile {
    param([Parameter(Mandatory = $true)][string]$Name)
    switch ($Name) {
        "quick" {
            $script:Tenants = 4
            $script:SeedRowsPerTenant = 150
            $script:ImportsPerTenant = 1
            $script:RowsPerImport = 250
            $script:Concurrency = 3
            $script:ImportWorkerReplicas = 2
            $script:Scenario = "child_mix"
            $script:ReviewEvery = 17
            $script:DuplicateStrategy = "review"
            $script:DbLatencyMs = 12
            $script:DbJitterMs = 4
            $script:DbDownstreamBandwidthKbps = 0
            $script:RabbitLatencyMs = 8
            $script:RabbitJitterMs = 3
            $script:TimeoutSeconds = 180
        }
        "quick_review" {
            $script:Tenants = 4
            $script:SeedRowsPerTenant = 150
            $script:ImportsPerTenant = 1
            $script:RowsPerImport = 250
            $script:Concurrency = 3
            $script:ImportWorkerReplicas = 2
            $script:Scenario = "child_mix"
            $script:ReviewEvery = 17
            $script:DuplicateStrategy = "review"
            $script:DbLatencyMs = 12
            $script:DbJitterMs = 4
            $script:DbDownstreamBandwidthKbps = 0
            $script:RabbitLatencyMs = 8
            $script:RabbitJitterMs = 3
            $script:TimeoutSeconds = 180
        }
        "quick_create" {
            $script:Tenants = 4
            $script:SeedRowsPerTenant = 150
            $script:ImportsPerTenant = 1
            $script:RowsPerImport = 250
            $script:Concurrency = 3
            $script:ImportWorkerReplicas = 2
            $script:Scenario = "child_mix"
            $script:ReviewEvery = 0
            $script:DuplicateStrategy = "allow_all"
            $script:DbLatencyMs = 12
            $script:DbJitterMs = 4
            $script:DbDownstreamBandwidthKbps = 0
            $script:RabbitLatencyMs = 8
            $script:RabbitJitterMs = 3
            $script:TimeoutSeconds = 180
        }
        "medium_create" {
            $script:Tenants = 8
            $script:SeedRowsPerTenant = 250
            $script:ImportsPerTenant = 1
            $script:RowsPerImport = 400
            $script:Concurrency = 4
            $script:ImportWorkerReplicas = 2
            $script:Scenario = "child_mix"
            $script:ReviewEvery = 0
            $script:DuplicateStrategy = "allow_all"
            $script:DbLatencyMs = 15
            $script:DbJitterMs = 5
            $script:DbDownstreamBandwidthKbps = 0
            $script:RabbitLatencyMs = 10
            $script:RabbitJitterMs = 4
            $script:TimeoutSeconds = 300
        }
        "medium_review" {
            $script:Tenants = 8
            $script:SeedRowsPerTenant = 250
            $script:ImportsPerTenant = 1
            $script:RowsPerImport = 400
            $script:Concurrency = 4
            $script:ImportWorkerReplicas = 2
            $script:Scenario = "child_mix"
            $script:ReviewEvery = 15
            $script:DuplicateStrategy = "review"
            $script:DbLatencyMs = 15
            $script:DbJitterMs = 5
            $script:DbDownstreamBandwidthKbps = 0
            $script:RabbitLatencyMs = 10
            $script:RabbitJitterMs = 4
            $script:TimeoutSeconds = 300
        }
        "baseline" {
            $script:Tenants = 12
            $script:SeedRowsPerTenant = 400
            $script:ImportsPerTenant = 1
            $script:RowsPerImport = 800
            $script:Concurrency = 6
            $script:ImportWorkerReplicas = 1
            $script:Scenario = "child_mix"
            $script:ReviewEvery = 0
            $script:DbLatencyMs = 8
            $script:DbJitterMs = 3
            $script:DbDownstreamBandwidthKbps = 0
            $script:RabbitLatencyMs = 6
            $script:RabbitJitterMs = 2
        }
        "contention" {
            $script:Tenants = 16
            $script:SeedRowsPerTenant = 500
            $script:ImportsPerTenant = 1
            $script:RowsPerImport = 1000
            $script:Concurrency = 8
            $script:ImportWorkerReplicas = 1
            $script:Scenario = "child_mix"
            $script:ReviewEvery = 23
            $script:DbLatencyMs = 25
            $script:DbJitterMs = 8
            $script:DbDownstreamBandwidthKbps = 4096
            $script:RabbitLatencyMs = 14
            $script:RabbitJitterMs = 5
        }
        "chaos" {
            $script:Tenants = 20
            $script:SeedRowsPerTenant = 600
            $script:ImportsPerTenant = 1
            $script:RowsPerImport = 1200
            $script:Concurrency = 10
            $script:ImportWorkerReplicas = 3
            $script:Scenario = "child_mix"
            $script:ReviewEvery = 19
            $script:DbLatencyMs = 60
            $script:DbJitterMs = 30
            $script:DbDownstreamBandwidthKbps = 2048
            $script:RabbitLatencyMs = 30
            $script:RabbitJitterMs = 12
        }
        default {
            return
        }
    }
}

function Restore-ExplicitImportPerfOverrides {
    param([Parameter(Mandatory = $true)][hashtable]$Bound)
    $keys = @(
        "Tenants",
        "SeedRowsPerTenant",
        "ImportsPerTenant",
        "RowsPerImport",
        "Concurrency",
        "Scenario",
        "ImportWorkerReplicas",
        "ReviewEvery",
        "DuplicateStrategy",
        "PreviewFraction",
        "PollIntervalSeconds",
        "TimeoutSeconds",
        "DbLatencyMs",
        "DbJitterMs",
        "DbDownstreamBandwidthKbps",
        "RabbitLatencyMs",
        "RabbitJitterMs"
    )
    foreach ($key in $keys) {
        if ($Bound.ContainsKey($key)) {
            Set-Variable -Name $key -Value $Bound[$key] -Scope Script
        }
    }
}

function Set-PerfRuntimeToxiproxyEnv {
    Set-Item -Path "Env:PERF_DB_LATENCY_MS" -Value ([string]$DbLatencyMs)
    Set-Item -Path "Env:PERF_DB_JITTER_MS" -Value ([string]$DbJitterMs)
    Set-Item -Path "Env:PERF_DB_DOWNSTREAM_BANDWIDTH_KBPS" -Value ([string]$DbDownstreamBandwidthKbps)
    Set-Item -Path "Env:PERF_RABBIT_LATENCY_MS" -Value ([string]$RabbitLatencyMs)
    Set-Item -Path "Env:PERF_RABBIT_JITTER_MS" -Value ([string]$RabbitJitterMs)
}

function Import-PerfEnvFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path $Path)) {
        return
    }
    foreach ($rawLine in Get-Content -Path $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }
        $idx = $line.IndexOf("=")
        if ($idx -le 0) {
            continue
        }
        $key = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim()
        if ($value.StartsWith('"') -and $value.EndsWith('"') -and $value.Length -ge 2) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if (-not (Get-Item -Path ("Env:{0}" -f $key) -ErrorAction SilentlyContinue)) {
            Set-Item -Path ("Env:{0}" -f $key) -Value $value
        }
    }
}

function Assert-RequiredEnv {
    param([Parameter(Mandatory = $true)][string[]]$Names)
    foreach ($name in $Names) {
        $item = Get-Item -Path ("Env:{0}" -f $name) -ErrorAction SilentlyContinue
        $value = if ($null -ne $item) { [string]$item.Value } else { "" }
        if (-not $value) {
            throw "Missing required env for import perf run: $name"
        }
    }
}

function Set-DefaultPerfSecretsIfMissing {
    $defaults = @{
        POSTGRES_ADMIN_PASSWORD = "immoapp_admin_password"
        POSTGRES_PASSWORD = "immoapp_app_password"
        RABBITMQ_PASSWORD = "immoapp_rabbit_password"
        DJANGO_SECRET_KEY = "immoapp-local-perf-secret-key-change-me"
        DJANGO_ALLOWED_HOSTS = "127.0.0.1,localhost,web"
    }
    foreach ($entry in $defaults.GetEnumerator()) {
        $name = [string]$entry.Key
        $item = Get-Item -Path ("Env:{0}" -f $name) -ErrorAction SilentlyContinue
        $value = if ($null -ne $item) { [string]$item.Value } else { "" }
        if (-not $value) {
            Set-Item -Path ("Env:{0}" -f $name) -Value ([string]$entry.Value)
            Write-Warning "Import perf runner set local fallback for missing $name"
        }
    }
}

function Get-ServerPythonPath {
    $python = Get-ImmoAppVenvPython -Kind "server"
    if (-not (Test-Path $python)) {
        throw "Server venv python was not found: $python"
    }
    return $python
}

function Invoke-PerfSeeder {
    param([Parameter(Mandatory = $true)][string[]]$Args)
    $serverPython = Get-ServerPythonPath
    & $serverPython "scripts/perf/perf_seed_multitenant.py" @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Perf seeder failed."
    }
}

function Invoke-Compose {
    param([Parameter(Mandatory = $true)][string[]]$Args)
    & docker compose @composeArgs @Args
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed: $($Args -join ' ')"
    }
}

function Wait-WebReadiness {
    param([int]$TimeoutSeconds = 420)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $port = if ($env:WEB_PORT) { [string]$env:WEB_PORT } else { "8000" }
    $baseUrl = "http://127.0.0.1:{0}" -f $port
    $readyUrl = "$baseUrl/api/v1/health/ready/"
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-RestMethod -Method Get -Uri $readyUrl -TimeoutSec 5
            if ($resp.ready -eq $true) {
                return $baseUrl
            }
        }
        catch {
            Start-Sleep -Seconds 2
            continue
        }
        Start-Sleep -Seconds 2
    }
    throw "Web readiness timed out after $TimeoutSeconds seconds."
}

function Ensure-DatabaseSchema {
    Invoke-Compose -Args @("exec", "-T", "web", "python", "server/manage.py", "immoapp_db_prepare")
}

function Clear-PerfBrokerQueues {
    Invoke-Compose -Args @(
        "exec", "-T", "rabbitmq", "sh", "-ec",
        'for q in default maintenance rebuild_batch match_pairs imports celery; do rabbitmqctl purge_queue "$q" >/dev/null 2>&1 || true; done'
    )
}

if ($Profile -ne "custom") {
    Apply-ImportPerfProfile -Name $Profile
    Restore-ExplicitImportPerfOverrides -Bound $PSBoundParameters
}
Set-PerfRuntimeToxiproxyEnv

$runtimeEnvFile = if ($env:IMMOAPP_RUNTIME_ENV_FILE) {
    [string]$env:IMMOAPP_RUNTIME_ENV_FILE
}
else {
    "C:/ProgramData/ImmoApp/config/.env.local"
}
Import-PerfEnvFile -Path $runtimeEnvFile
Set-DefaultPerfSecretsIfMissing
Assert-RequiredEnv -Names @("POSTGRES_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "RABBITMQ_PASSWORD")

$startedStack = $false
try {
    try {
        Invoke-Compose -Args @("down", "--remove-orphans")
    }
    catch {
        Write-Warning "Initial compose down failed: $($_.Exception.Message)"
    }

    $bootServices = @(
        "db", "rabbitmq", "valkey",
        "openbao", "openbao-init", "openbao-seed",
        "minio", "minio-init", "clamav",
        "app-data-init",
        "toxiproxy", "toxiproxy-init"
    )
    $bootArgs = @("up", "-d", "--yes")
    if ($Build) {
        $bootArgs += "--build"
    }
    $bootArgs += $bootServices
    Invoke-Compose -Args $bootArgs

    $runtimeServices = @("web", "worker", "worker-import", "worker-rebuild", "worker-match", "beat")
    $runtimeArgs = @("up", "-d", "--yes")
    if ($Build) {
        $runtimeArgs += "--build"
    }
    $runtimeArgs += $runtimeServices
    Invoke-Compose -Args $runtimeArgs
    if ($ImportWorkerReplicas -gt 1) {
        Invoke-Compose -Args @("up", "-d", "--scale", "worker-import=$ImportWorkerReplicas", "worker-import")
    }
    $startedStack = $true

    $baseUrl = Wait-WebReadiness -TimeoutSeconds 420
    Ensure-DatabaseSchema
    Clear-PerfBrokerQueues

    if (-not $KeepData) {
        Invoke-PerfSeeder -Args @("--cleanup-all")
    }

    Invoke-PerfSeeder -Args @(
        "--tag", $Tag,
        "--tenants", "$Tenants",
        "--rows-per-tenant", "$SeedRowsPerTenant",
        "--output-file", $seedFile
    )
    Clear-PerfBrokerQueues

    $serverPython = Get-ServerPythonPath
    & $serverPython "scripts/perf/import_benchmark.py" `
        --base-url $baseUrl `
        --seed-file $seedFile `
        --output-file $reportFile `
        --scenario $Scenario `
        --tenants $Tenants `
        --imports-per-tenant $ImportsPerTenant `
        --rows-per-import $RowsPerImport `
        --review-every $ReviewEvery `
        --concurrency $Concurrency `
        --duplicate-strategy $DuplicateStrategy `
        --preview-fraction $PreviewFraction `
        --poll-interval-seconds $PollIntervalSeconds `
        --timeout-seconds $TimeoutSeconds `
        --host-header "localhost"
    if ($LASTEXITCODE -ne 0) {
        throw "Importer benchmark failed."
    }

    Write-Host ""
    Write-Host "[import-perf] report: $reportFile" -ForegroundColor Cyan
}
finally {
    if (-not $KeepData -and $startedStack) {
        try {
            Invoke-PerfSeeder -Args @("--cleanup", "--tag", $Tag)
        }
        catch {
            Write-Warning "Import perf cleanup failed: $($_.Exception.Message)"
        }
    }
    if (-not $KeepStack -and $startedStack) {
        try {
            Invoke-Compose -Args @("stop", "web", "worker", "worker-import", "worker-rebuild", "worker-match", "beat", "toxiproxy")
        }
        catch {
            Write-Warning "Import perf stack stop failed: $($_.Exception.Message)"
        }
    }
}
