[CmdletBinding()]
param(
    [switch]$PlanOnly,
    [string]$OutputJson = "",
    [double]$MachineTotalMemoryGb = 0,
    [int]$MachineLogicalProcessors = 0,
    [string]$RuntimeProfileJson = "",
    [string]$ExistingWslConfigPath = "",
    [ValidateSet("json", "text")]
    [string]$Format = "json"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

$MinimumHubRamGb = 8
$MinimumWslMemoryGb = 3
$MinimumWindowsReserveGb = 3
$LowMidWindowsReserveFraction = 0.35
$LargeWindowsReserveFraction = 0.25
$LargeMachineMinimumWindowsReserveGb = 6
$DefaultSwapGb = 2
$AutoMemoryReclaimMode = "gradual"

$ProfileCaps = @{
    tiny = @{ MemoryGb = 3; Processors = 2 }
    small = @{ MemoryGb = 5; Processors = 4 }
    medium = @{ MemoryGb = 8; Processors = 6 }
    large = @{ MemoryGb = 12; Processors = 8 }
}

$ProfileRank = @{
    tiny = 0
    small = 1
    medium = 2
    large = 3
}

function Get-CurrentTotalMemoryGb {
    $computer = Get-CimInstance -ClassName Win32_ComputerSystem
    return [math]::Round(([double]$computer.TotalPhysicalMemory / 1GB), 2)
}

function Get-CurrentLogicalProcessors {
    return [int]([Environment]::ProcessorCount)
}

function Select-LowerProfile {
    param(
        [Parameter(Mandatory = $true)][string]$A,
        [Parameter(Mandatory = $true)][string]$B
    )
    if ($ProfileRank[$A] -le $ProfileRank[$B]) { return $A }
    return $B
}

function Select-HubMachineTier {
    param(
        [Parameter(Mandatory = $true)][double]$NormalizedMemoryClassGb,
        [Parameter(Mandatory = $true)][int]$LogicalProcessors
    )
    $memoryProfile = Select-HubMemoryProfile -NormalizedMemoryClassGb $NormalizedMemoryClassGb
    $cpuProfile = Select-HubCpuProfile -LogicalProcessors $LogicalProcessors
    return (Select-LowerProfile -A $memoryProfile -B $cpuProfile)
}

function Select-HubMemoryProfile {
    param([Parameter(Mandatory = $true)][double]$NormalizedMemoryClassGb)
    if ($NormalizedMemoryClassGb -lt 16) { return "tiny" }
    if ($NormalizedMemoryClassGb -lt 32) { return "medium" }
    return "large"
}

function Select-HubCpuProfile {
    param([Parameter(Mandatory = $true)][int]$LogicalProcessors)
    if ($LogicalProcessors -le 2) { return "tiny" }
    if ($LogicalProcessors -le 4) { return "small" }
    if ($LogicalProcessors -le 7) { return "medium" }
    return "large"
}

function Normalize-InstalledMemoryClassGb {
    param([Parameter(Mandatory = $true)][double]$TotalMemoryGb)
    # Windows often reports usable RAM below the installed class because firmware
    # reserves memory. Normalize near common retail classes so 15.7 GB behaves as
    # a 16 GB Hub candidate, while 7.4 GB remains below the 8 GB minimum.
    if ($TotalMemoryGb -ge 31.5) { return 32.0 }
    if ($TotalMemoryGb -ge 15.0) { return 16.0 }
    if ($TotalMemoryGb -ge 7.5) { return 8.0 }
    return [math]::Round($TotalMemoryGb, 2)
}

function Resolve-HubRuntimeProfileEnvelope {
    param([string]$ExplicitPath)

    $source = "machine_capacity"
    $path = ""
    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        $source = "explicit_runtime_profile_json"
        $path = [System.IO.Path]::GetFullPath($ExplicitPath)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            return [ordered]@{
                profile = ""
                status = "missing"
                source = $source
                path = $path
                sha256 = ""
                error = "explicit_runtime_profile_missing"
            }
        }
    }
    else {
        $candidate = Join-Path (Get-ImmoAppRuntimePaths).ConfigRoot "hub_runtime_profile.json"
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return [ordered]@{
                profile = ""
                status = "missing"
                source = "machine_capacity"
                path = ""
                sha256 = ""
                error = ""
            }
        }
        $source = "default_persisted_config"
        $path = [System.IO.Path]::GetFullPath($candidate)
    }

    if (Test-ImmoAppPathHasReparsePoint -Path $path) {
        return [ordered]@{
            profile = ""
            status = "invalid_path"
            source = $source
            path = $path
            sha256 = ""
            error = "runtime_profile_reparse_point"
        }
    }

    $sha = Get-ImmoAppFileSha256 -Path $path
    try {
        $profileJson = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    }
    catch {
        return [ordered]@{
            profile = ""
            status = "invalid_json"
            source = $source
            path = $path
            sha256 = $sha
            error = "runtime_profile_invalid_json"
        }
    }

    $selected = [string](Get-ImmoAppObjectValue -Data $profileJson -Name "selected_profile")
    if ([string]::IsNullOrWhiteSpace($selected)) {
        $selected = [string](Get-ImmoAppObjectValue -Data $profileJson -Name "profile_name")
    }
    $selected = $selected.Trim().ToLowerInvariant()
    if (-not $ProfileRank.ContainsKey($selected)) {
        return [ordered]@{
            profile = ""
            status = "invalid_selected_profile"
            source = $source
            path = $path
            sha256 = $sha
            error = "runtime_profile_invalid_selected_profile"
        }
    }

    return [ordered]@{
        profile = $selected
        status = "valid"
        source = $source
        path = $path
        sha256 = $sha
        error = ""
    }
}

function Get-WindowsReserveGb {
    param([Parameter(Mandatory = $true)][double]$TotalMemoryGb)
    if ($TotalMemoryGb -ge 32) {
        return [math]::Max($LargeMachineMinimumWindowsReserveGb, [math]::Ceiling($TotalMemoryGb * $LargeWindowsReserveFraction))
    }
    return [math]::Max($MinimumWindowsReserveGb, [math]::Ceiling($TotalMemoryGb * $LowMidWindowsReserveFraction))
}

function Get-ApprovedOutputRoots {
    $repoTmp = Join-Path (Get-ImmoAppRepoRoot).Path ".tmp"
    $paths = Get-ImmoAppRuntimePaths
    $canonical = Get-ImmoAppCanonicalRuntimePaths
    return @(
        $repoTmp,
        $paths.ConfigRoot,
        $paths.RuntimeRoot,
        $paths.LogsRoot,
        $canonical.ConfigRoot,
        $canonical.RuntimeRoot,
        $canonical.LogsRoot
    ) | Select-Object -Unique
}

$totalMemory = if ($MachineTotalMemoryGb -gt 0) { [double]$MachineTotalMemoryGb } else { Get-CurrentTotalMemoryGb }
$normalizedMemoryClassGb = Normalize-InstalledMemoryClassGb -TotalMemoryGb $totalMemory
$logicalProcessors = if ($MachineLogicalProcessors -gt 0) { [int]$MachineLogicalProcessors } else { Get-CurrentLogicalProcessors }
$logicalProcessors = [math]::Max(1, $logicalProcessors)
$profileResolution = Resolve-HubRuntimeProfileEnvelope -ExplicitPath $RuntimeProfileJson
$profileFromRuntime = [string]$profileResolution.profile
$memoryDerivedProfile = if ($normalizedMemoryClassGb -ge $MinimumHubRamGb) { Select-HubMemoryProfile -NormalizedMemoryClassGb $normalizedMemoryClassGb } else { "workstation_only" }
$cpuDerivedProfile = if ($normalizedMemoryClassGb -ge $MinimumHubRamGb) { Select-HubCpuProfile -LogicalProcessors $logicalProcessors } else { "workstation_only" }

$policyResult = "GO"
$reasonCode = "managed_wsl2_runtime_policy_ready"
$warnings = New-Object System.Collections.Generic.List[string]
$selectedTier = "unsupported"
$selectedProfile = "unsupported"
$windowsReserve = Get-WindowsReserveGb -TotalMemoryGb $totalMemory
$plannedMemory = 0
$plannedProcessors = 0
$plannedSwap = $DefaultSwapGb

if (-not [string]::IsNullOrWhiteSpace([string]$profileResolution.error)) {
    $policyResult = "NO-GO"
    $reasonCode = [string]$profileResolution.error
}

if ($policyResult -eq "GO" -and $normalizedMemoryClassGb -lt $MinimumHubRamGb) {
    $policyResult = "NO-GO"
    $reasonCode = "machine_below_minimum_hub_ram"
    $selectedTier = "workstation_only"
    $selectedProfile = "workstation_only"
}
elseif ($policyResult -eq "GO") {
    $selectedTier = Select-HubMachineTier -NormalizedMemoryClassGb $normalizedMemoryClassGb -LogicalProcessors $logicalProcessors
    # Runtime profile is an envelope: machine capacity selects the upper bound,
    # and an existing Hub runtime profile may only lower the WSL cap.
    $selectedProfile = $selectedTier
    if (-not [string]::IsNullOrWhiteSpace($profileFromRuntime)) {
        $selectedProfile = Select-LowerProfile -A $selectedTier -B $profileFromRuntime
    }
    if ($normalizedMemoryClassGb -lt 16) {
        $warnings.Add("hub_on_minimum_ram") | Out-Null
    }
    $profileCap = $ProfileCaps[$selectedProfile]
    $availableForWsl = [math]::Max(0, [math]::Floor($totalMemory - $windowsReserve))
    $plannedMemory = [int]([math]::Min([double]$profileCap.MemoryGb, [double]$availableForWsl))
    if ($plannedMemory -lt $MinimumWslMemoryGb) {
        $plannedMemory = $MinimumWslMemoryGb
    }
    if ($normalizedMemoryClassGb -lt 16) {
        $plannedMemory = [math]::Min($plannedMemory, 3)
    }
    $cpuAfterReserve = [math]::Max(1, $logicalProcessors - 1)
    $plannedProcessors = [int]([math]::Min([double]$profileCap.Processors, [double]$cpuAfterReserve))
}

$wslConfigPath = if (-not [string]::IsNullOrWhiteSpace($ExistingWslConfigPath)) {
    $ExistingWslConfigPath
} else {
    Join-Path $env:USERPROFILE ".wslconfig"
}

$payload = [ordered]@{
    kind = "immoapp_managed_wsl2_runtime_policy"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    total_memory_gb = [math]::Round($totalMemory, 2)
    normalized_memory_class_gb = [math]::Round($normalizedMemoryClassGb, 2)
    logical_processors = [int]$logicalProcessors
    memory_derived_hub_profile = $memoryDerivedProfile
    cpu_derived_hub_profile = $cpuDerivedProfile
    selected_hub_machine_tier = $selectedTier
    selected_hub_runtime_profile = $selectedProfile
    hub_minimum_ram_gb = $MinimumHubRamGb
    policy_result = $policyResult
    reason_code = $reasonCode
    warning_codes = @($warnings.ToArray())
    windows_memory_reserve_gb = [int]$windowsReserve
    planned_wsl_memory_gb = [int]$plannedMemory
    planned_wsl_processors = [int]$plannedProcessors
    planned_wsl_swap_gb = [int]$plannedSwap
    planned_auto_memory_reclaim = $AutoMemoryReclaimMode
    cap_is_ceiling_not_reservation = $true
    startup_spike_not_failure = $true
    sustained_pressure_backoff_required = $true
    global_wsl_config_scope = $true
    wslconfig_path = [System.IO.Path]::GetFullPath($wslConfigPath)
    apply_performed = $false
    agency_install_status = "NO_GO"
    runtime_profile_source = [string]$profileResolution.source
    runtime_profile_status = [string]$profileResolution.status
    runtime_profile_path = [string]$profileResolution.path
    runtime_profile_sha256 = [string]$profileResolution.sha256
    runtime_profile_error = [string]$profileResolution.error
    observed_hub_runtime_profile = $profileFromRuntime
}

if ($OutputJson) {
    Write-ImmoAppSafeJson -Path $OutputJson -Payload $payload -ApprovedRoots (Get-ApprovedOutputRoots) -Depth 8 | Out-Null
}

if ($Format -eq "json") {
    $payload | ConvertTo-Json -Depth 8
}
else {
    "WSL2 policy: $policyResult ($reasonCode)"
    "Tier/profile: $selectedTier / $selectedProfile"
    "Planned cap: memory=${plannedMemory}GB processors=$plannedProcessors swap=${plannedSwap}GB autoMemoryReclaim=$AutoMemoryReclaimMode"
    "Apply performed: false"
}
