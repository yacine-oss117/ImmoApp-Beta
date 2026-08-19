[CmdletBinding()]
param(
    [switch]$PlanOnly,
    [switch]$Apply,
    [switch]$ConfirmGlobalWslConfigChange,
    [switch]$AllowMergeExistingWslConfig,
    [switch]$ApplyShutdown,
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

function Get-WslConfigPath {
    param([string]$ExplicitPath)
    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        return [System.IO.Path]::GetFullPath($ExplicitPath)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $env:USERPROFILE ".wslconfig"))
}

function Get-Wsl2SettingLines {
    param([string[]]$Lines)
    $inWsl2 = $false
    $settings = @{}
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        $line = [string]$Lines[$i]
        $trimmed = $line.Trim()
        if ($trimmed -match "^\[(?<section>[^\]]+)\]$") {
            $inWsl2 = ($Matches["section"].Trim().ToLowerInvariant() -eq "wsl2")
            continue
        }
        if ($inWsl2 -and $trimmed -match "^(?<key>[A-Za-z0-9_.-]+)\s*=") {
            $settings[$Matches["key"].Trim().ToLowerInvariant()] = $i
        }
    }
    return $settings
}

function Get-WslConfigAmbiguity {
    param([string[]]$Lines)
    $managedKeys = @("memory", "processors", "swap", "automemoryreclaim")
    $wsl2SectionCount = 0
    $inWsl2 = $false
    $seenManagedKeys = @{}
    $duplicateKeys = New-Object System.Collections.Generic.List[string]
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        $line = [string]$Lines[$i]
        $trimmed = $line.Trim()
        if ($trimmed -match "^\[(?<section>[^\]]+)\]$") {
            $section = $Matches["section"].Trim().ToLowerInvariant()
            $inWsl2 = ($section -eq "wsl2")
            if ($inWsl2) { $wsl2SectionCount += 1 }
            continue
        }
        if ($inWsl2 -and $trimmed -match "^(?<key>[A-Za-z0-9_.-]+)\s*=") {
            $key = $Matches["key"].Trim().ToLowerInvariant()
            if ($managedKeys -contains $key) {
                if ($seenManagedKeys.ContainsKey($key) -and -not $duplicateKeys.Contains($key)) {
                    $duplicateKeys.Add($key) | Out-Null
                }
                $seenManagedKeys[$key] = $true
            }
        }
    }
    return [ordered]@{
        duplicate_wsl2_sections = ($wsl2SectionCount -gt 1)
        duplicate_managed_keys = @($duplicateKeys.ToArray())
    }
}

function Get-Wsl2SectionSettings {
    param([string[]]$Lines)
    $inWsl2 = $false
    $settings = @{}
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        $line = [string]$Lines[$i]
        $trimmed = $line.Trim()
        if ($trimmed -match "^\[(?<section>[^\]]+)\]$") {
            $inWsl2 = ($Matches["section"].Trim().ToLowerInvariant() -eq "wsl2")
            continue
        }
        if ($inWsl2 -and $trimmed -match "^(?<key>[A-Za-z0-9_.-]+)\s*=\s*(?<value>.*)$") {
            $settings[$Matches["key"].Trim().ToLowerInvariant()] = $Matches["value"].Trim()
        }
    }
    return $settings
}

function Test-WslConfigContainsDesiredSettings {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][hashtable]$Desired
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ verified = $false; missing_keys = @("wslconfig_missing") }
    }
    $lines = @(Get-Content -LiteralPath $Path)
    $settings = Get-Wsl2SectionSettings -Lines $lines
    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($key in @("memory", "processors", "swap", "autoMemoryReclaim")) {
        $lookup = $key.ToLowerInvariant()
        if (-not $settings.ContainsKey($lookup) -or [string]$settings[$lookup] -ne [string]$Desired[$key]) {
            $missing.Add($key) | Out-Null
        }
    }
    return [ordered]@{
        verified = ($missing.Count -eq 0)
        missing_keys = @($missing.ToArray())
    }
}

function Merge-WslConfig {
    param(
        [string[]]$Lines,
        [hashtable]$Desired
    )
    $output = New-Object System.Collections.Generic.List[string]
    foreach ($line in $Lines) { $output.Add($line) | Out-Null }
    $settings = Get-Wsl2SettingLines -Lines @($output.ToArray())
    $wsl2Start = -1
    $wsl2End = $output.Count
    for ($i = 0; $i -lt $output.Count; $i++) {
        $line = [string]$output[$i]
        if ($line -match "^\s*\[(?<section>[^\]]+)\]\s*$") {
            $section = $Matches["section"].Trim().ToLowerInvariant()
            if ($section -eq "wsl2") {
                $wsl2Start = $i
                $wsl2End = $output.Count
                continue
            }
            if ($wsl2Start -ge 0 -and $i -gt $wsl2Start) {
                $wsl2End = $i
                break
            }
        }
    }
    if ($wsl2Start -lt 0) {
        if ($output.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($output[$output.Count - 1])) {
            $output.Add("") | Out-Null
        }
        $output.Add("[wsl2]") | Out-Null
        $wsl2Start = $output.Count - 1
        $wsl2End = $output.Count
    }
    foreach ($key in @("memory", "processors", "swap", "autoMemoryReclaim")) {
        $line = "$key=$($Desired[$key])"
        $lookup = $key.ToLowerInvariant()
        if ($settings.ContainsKey($lookup)) {
            $output[[int]$settings[$lookup]] = $line
        }
        else {
            $output.Insert($wsl2End, $line)
            $wsl2End += 1
        }
    }
    return @($output.ToArray())
}

function Test-WslConfigPathSafeForWrite {
    param([Parameter(Mandatory = $true)][string]$Path)
    $full = [System.IO.Path]::GetFullPath($Path)
    $expected = [System.IO.Path]::GetFullPath((Join-Path $env:USERPROFILE ".wslconfig"))
    if (-not $full.Equals($expected, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "wslconfig_path_not_user_profile|Managed WSL2 config writes are allowed only to the current user's .wslconfig: $expected"
    }
    $parent = Split-Path -Parent $full
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "wslconfig_parent_missing|User profile directory does not exist: $parent"
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $parent) {
        throw "wslconfig_reparse_point|.wslconfig parent contains a reparse point, symlink, or junction: $parent"
    }
    if ((Test-Path -LiteralPath $full) -and (Test-ImmoAppPathHasReparsePoint -Path $full)) {
        throw "wslconfig_reparse_point|.wslconfig contains a reparse point, symlink, or junction: $full"
    }
    return $full
}

$policyArgs = @("-PlanOnly", "-Format", "json")
if ($MachineTotalMemoryGb -gt 0) { $policyArgs += @("-MachineTotalMemoryGb", ([string]$MachineTotalMemoryGb)) }
if ($MachineLogicalProcessors -gt 0) { $policyArgs += @("-MachineLogicalProcessors", ([string]$MachineLogicalProcessors)) }
if (-not [string]::IsNullOrWhiteSpace($RuntimeProfileJson)) { $policyArgs += @("-RuntimeProfileJson", $RuntimeProfileJson) }
if (-not [string]::IsNullOrWhiteSpace($ExistingWslConfigPath)) { $policyArgs += @("-ExistingWslConfigPath", $ExistingWslConfigPath) }

$policyText = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "managed_wsl2_runtime_policy.ps1") @policyArgs
if ($LASTEXITCODE -ne 0) {
    throw "wsl_policy_failed|managed_wsl2_runtime_policy.ps1 failed."
}
$policy = ($policyText | Out-String).Trim() | ConvertFrom-Json

$wslConfigPath = Get-WslConfigPath -ExplicitPath $ExistingWslConfigPath
$existingPresent = Test-Path -LiteralPath $wslConfigPath -PathType Leaf
$existingLines = @()
if ($existingPresent) {
    if (Test-ImmoAppPathHasReparsePoint -Path $wslConfigPath) {
        throw "wslconfig_reparse_point|Existing .wslconfig contains a reparse point, symlink, or junction."
    }
    $existingLines = @(Get-Content -LiteralPath $wslConfigPath)
}

$desired = @{
    memory = "$([int]$policy.planned_wsl_memory_gb)GB"
    processors = [string]([int]$policy.planned_wsl_processors)
    swap = "$([int]$policy.planned_wsl_swap_gb)GB"
    autoMemoryReclaim = [string]$policy.planned_auto_memory_reclaim
}
$managedKeys = @("memory", "processors", "swap", "autoMemoryReclaim")
$managedKeyLookup = @("memory", "processors", "swap", "automemoryreclaim")
$existingSettings = Get-Wsl2SettingLines -Lines $existingLines
$conflictingKeys = @($managedKeyLookup | Where-Object { $existingSettings.ContainsKey($_) })
$ambiguity = Get-WslConfigAmbiguity -Lines $existingLines
$hasConflicts = $existingPresent -and $conflictingKeys.Count -gt 0
$hasDuplicateWsl2Sections = $existingPresent -and [bool]$ambiguity.duplicate_wsl2_sections
$duplicateManagedKeys = @($ambiguity.duplicate_managed_keys)
$hasDuplicateManagedKeys = $existingPresent -and $duplicateManagedKeys.Count -gt 0
$configChangeRequired = $true
$applyAllowed = $Apply -and $ConfirmGlobalWslConfigChange
$applyPerformed = $false
$backupPath = ""
$preserved = $existingPresent
$backupVerified = $false
$finalWslConfigVerified = $false
$finalWslConfigMissingKeys = @()
$tempRemoved = $true
$wslShutdownRequired = $false
$wslShutdownPerformed = $false
$reasonCode = if ([string]$policy.policy_result -eq "GO") { "wsl_config_plan_ready" } else { [string]$policy.reason_code }
$planResult = if ([string]$policy.policy_result -eq "GO") { "GO" } else { "NO-GO" }

if ($hasConflicts -and -not $AllowMergeExistingWslConfig) {
    $planResult = "NO-GO"
    $reasonCode = "existing_wslconfig_conflict_requires_allow_merge"
}
if ($hasDuplicateManagedKeys) {
    $planResult = "NO-GO"
    $reasonCode = "duplicate_wsl2_managed_key_requires_manual_cleanup"
}
if ($hasDuplicateWsl2Sections) {
    $planResult = "NO-GO"
    $reasonCode = "duplicate_wsl2_section_requires_manual_cleanup"
}

if ($Apply) {
    if (-not $ConfirmGlobalWslConfigChange) {
        $planResult = "NO-GO"
        $reasonCode = "confirm_global_wsl_config_change_required"
    }
    elseif ([string]$policy.policy_result -ne "GO") {
        $planResult = "NO-GO"
    }
    elseif ($hasDuplicateWsl2Sections) {
        $planResult = "NO-GO"
        $reasonCode = "duplicate_wsl2_section_requires_manual_cleanup"
    }
    elseif ($hasDuplicateManagedKeys) {
        $planResult = "NO-GO"
        $reasonCode = "duplicate_wsl2_managed_key_requires_manual_cleanup"
    }
    elseif ($hasConflicts -and -not $AllowMergeExistingWslConfig) {
        $planResult = "NO-GO"
    }
    else {
        $safePath = Test-WslConfigPathSafeForWrite -Path $wslConfigPath
        $parent = Split-Path -Parent $safePath
        $newLines = Merge-WslConfig -Lines $existingLines -Desired $desired
        if ($existingPresent) {
            $backupPath = "$safePath.immoapp-backup.$((Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmss")).bak"
            Copy-Item -LiteralPath $safePath -Destination $backupPath -Force
        }
        $temp = Join-Path $parent (".wslconfig.immoapp.tmp." + [System.Guid]::NewGuid().ToString("N"))
        try {
            [System.IO.File]::WriteAllLines($temp, $newLines, [System.Text.UTF8Encoding]::new($false))
            Move-Item -LiteralPath $temp -Destination $safePath -Force
            $tempRemoved = -not (Test-Path -LiteralPath $temp)
            $verification = Test-WslConfigContainsDesiredSettings -Path $safePath -Desired $desired
            $finalWslConfigVerified = [bool]$verification.verified
            $finalWslConfigMissingKeys = @($verification.missing_keys)
            if (-not $finalWslConfigVerified) {
                throw "wslconfig_apply_verification_failed|Final .wslconfig is missing desired [wsl2] keys: $($finalWslConfigMissingKeys -join ', ')"
            }
            if ($existingPresent) {
                $backupVerified = (Test-Path -LiteralPath $backupPath -PathType Leaf)
                if (-not $backupVerified) {
                    throw "wslconfig_backup_missing|Existing .wslconfig backup was not created: $backupPath"
                }
            }
            $applyPerformed = $true
            $wslShutdownRequired = $true
            if ($ApplyShutdown) {
                & wsl --shutdown
                if ($LASTEXITCODE -ne 0) {
                    throw "wsl_shutdown_failed|wsl --shutdown failed with exit code $LASTEXITCODE"
                }
                $wslShutdownPerformed = $true
                $wslShutdownRequired = $false
            }
        }
        finally {
            if (Test-Path -LiteralPath $temp) {
                Remove-Item -LiteralPath $temp -Force
            }
            $tempRemoved = -not (Test-Path -LiteralPath $temp)
        }
    }
}

$payload = [ordered]@{
    kind = "immoapp_managed_wsl2_runtime_config_plan"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    policy_json = $policy
    existing_wslconfig_present = [bool]$existingPresent
    existing_wslconfig_backup_path = $backupPath
    existing_wslconfig_backup_verified = [bool]$backupVerified
    existing_wslconfig_preserved = [bool]$preserved
    existing_wslconfig_conflicting_keys = @($conflictingKeys)
    duplicate_wsl2_sections = [bool]$hasDuplicateWsl2Sections
    duplicate_wsl2_managed_keys = @($duplicateManagedKeys)
    final_wslconfig_verified = [bool]$finalWslConfigVerified
    final_wslconfig_missing_keys = @($finalWslConfigMissingKeys)
    temp_wslconfig_removed = [bool]$tempRemoved
    global_wsl_config_change_required = [bool]$configChangeRequired
    apply_requested = [bool]$Apply
    apply_performed = [bool]$applyPerformed
    confirm_global_wsl_config_change = [bool]$ConfirmGlobalWslConfigChange
    allow_merge_existing_wslconfig = [bool]$AllowMergeExistingWslConfig
    wsl_shutdown_required = [bool]$wslShutdownRequired
    wsl_shutdown_performed = [bool]$wslShutdownPerformed
    plan_result = $planResult
    reason_code = $reasonCode
    agency_install_status = "NO_GO"
}

if ($OutputJson) {
    Write-ImmoAppSafeJson -Path $OutputJson -Payload $payload -ApprovedRoots (Get-ApprovedOutputRoots) -Depth 12 | Out-Null
}

if ($Format -eq "json") {
    $payload | ConvertTo-Json -Depth 12
}
else {
    "WSL2 config plan: $planResult ($reasonCode)"
    "Existing .wslconfig: $existingPresent"
    "Apply requested/performed: $Apply / $applyPerformed"
    "WSL shutdown required/performed: $wslShutdownRequired / $wslShutdownPerformed"
}
