param(
    [string]$OutputJson = "",
    [string]$ProviderConfigPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

function Convert-ProviderBoolStrict {
    param(
        [object]$Value,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if ($null -eq $Value) { throw "Provider config is missing boolean field '$Name'." }
    if ($Value -is [bool]) { return [bool]$Value }
    $text = ([string]$Value).Trim().ToLowerInvariant()
    if ($text -eq "true" -or $text -eq "1") { return $true }
    if ($text -eq "false" -or $text -eq "0") { return $false }
    throw "Provider config field '$Name' must be a boolean."
}

function Convert-OptionalProviderBoolStrict {
    param(
        [object]$Value,
        [Parameter(Mandatory = $true)][string]$Name,
        [bool]$Default = $false
    )
    if ($null -eq $Value) { return $Default }
    return Convert-ProviderBoolStrict -Value $Value -Name $Name
}

function Get-RequiredProviderString {
    param(
        [object]$Provider,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $value = [string](Get-ImmoAppObjectValue -Data $Provider -Name $Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Provider config is missing required field '$Name'."
    }
    return $value.Trim()
}

function Get-OptionalProviderString {
    param(
        [object]$Provider,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $value = [string](Get-ImmoAppObjectValue -Data $Provider -Name $Name)
    if ([string]::IsNullOrWhiteSpace($value)) { return "" }
    return $value.Trim()
}

function Assert-ExistingPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [switch]$Directory
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Provider config field '$Name' points to a missing path: $Path"
    }
    $item = Get-Item -LiteralPath $Path
    if ($Directory -and -not $item.PSIsContainer) {
        throw "Provider config field '$Name' must point to a directory: $Path"
    }
    if (-not $Directory -and $item.PSIsContainer) {
        throw "Provider config field '$Name' must point to an executable file: $Path"
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $item.FullName) {
        Throw-ProviderValidation -ReasonCode "managed_runtime_reparse_point_not_allowed" -Message "Provider config field '$Name' contains a reparse point: $Path"
    }
    return $item.FullName
}

function Test-UserVisibleRuntimePath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    $clean = $Path.ToLowerInvariant()
    return (
        $clean.EndsWith("docker desktop.exe") -or
        $clean.Contains("\docker\docker\") -or
        $clean.Contains("/docker/docker/")
    )
}

function Throw-ProviderValidation {
    param(
        [Parameter(Mandatory = $true)][string]$ReasonCode,
        [Parameter(Mandatory = $true)][string]$Message
    )
    throw "$ReasonCode|$Message"
}

function Join-ImmoAppUrlPath {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Parameter(Mandatory = $true)][string]$Path
    )
    return $BaseUrl.TrimEnd("/") + "/" + $Path.TrimStart("/")
}

function Test-ImmoAppLiveFrontDoorIdentity {
    param([string]$BaseUrl = "")
    $probeUrl = if ([string]::IsNullOrWhiteSpace($BaseUrl)) { (Get-ImmoAppHubBaseUrl -PreferLan).TrimEnd("/") } else { $BaseUrl.TrimEnd("/") }
    $healthStatus = 0
    $identityStatus = 0
    $frontDoorHeader = ""
    $identityKind = ""
    $identitySchema = 0
    $failure = ""
    try {
        $health = Invoke-WebRequest -Method Get -Uri (Join-ImmoAppUrlPath -BaseUrl $probeUrl -Path "/api/v1/health/") -TimeoutSec 8 -UseBasicParsing
        $healthStatus = [int]$health.StatusCode
        $identity = Invoke-WebRequest -Method Get -Uri (Join-ImmoAppUrlPath -BaseUrl $probeUrl -Path "/api/v1/hub/front-door/identity/") -TimeoutSec 8 -UseBasicParsing
        $identityStatus = [int]$identity.StatusCode
        $frontDoorHeader = [string]$identity.Headers["X-ImmoApp-Front-Door"]
        $identityJson = $identity.Content | ConvertFrom-Json
        $identityKind = [string](Get-ImmoAppObjectValue -Data $identityJson -Name "kind")
        $identitySchema = [int](Get-ImmoAppObjectValue -Data $identityJson -Name "schema_version")
    }
    catch {
        $failure = $_.Exception.Message
    }
    $go = (
        $healthStatus -eq 200 -and
        $identityStatus -eq 200 -and
        $frontDoorHeader.ToLowerInvariant() -eq "caddy" -and
        $identityKind -eq "immoapp_hub_front_door_identity" -and
        $identitySchema -eq 1
    )
    return [ordered]@{
        front_door_url = $probeUrl
        health_status = $healthStatus
        identity_status = $identityStatus
        front_door_header = $frontDoorHeader
        identity_kind = $identityKind
        identity_schema_version = $identitySchema
        front_door_health_status = if ($go) { "GO" } else { "NO-GO" }
        failure_reason = $failure
    }
}

function Assert-NoProviderSecretFields {
    param(
        [Parameter(Mandatory = $true)][object]$Node,
        [string]$Path = "provider"
    )
    if ($null -eq $Node) { return }
    foreach ($property in @($Node.PSObject.Properties)) {
        $name = [string]$property.Name
        $childPath = "$Path.$name"
        if ($name -match (Get-ImmoAppSensitiveFieldPattern)) {
            Throw-ProviderValidation -ReasonCode "managed_runtime_secret_in_config" -Message "Provider config contains a sensitive field name: $childPath"
        }
        $value = $property.Value
        if ($null -eq $value -or $value -is [string] -or $value -is [ValueType]) {
            continue
        }
        if ($value -is [System.Collections.IEnumerable]) {
            $index = 0
            foreach ($item in @($value)) {
                if ($null -ne $item -and -not ($item -is [string]) -and -not ($item -is [ValueType])) {
                    Assert-NoProviderSecretFields -Node $item -Path "${childPath}[$index]"
                }
                $index += 1
            }
        }
        else {
            Assert-NoProviderSecretFields -Node $value -Path $childPath
        }
    }
}

function Assert-PathUnderApprovedRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if (-not (Test-ImmoAppPathUnderRoot -Root $Root -Path $Path)) {
        Throw-ProviderValidation -ReasonCode "managed_runtime_outside_approved_root" -Message "Provider config field '$Name' must be under approved root '$Root': $Path"
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $Path) {
        Throw-ProviderValidation -ReasonCode "managed_runtime_reparse_point_not_allowed" -Message "Provider config field '$Name' contains a reparse point: $Path"
    }
    if (-not (Test-ImmoAppResolvedPathUnderRoot -Root $Root -Path $Path)) {
        Throw-ProviderValidation -ReasonCode "managed_runtime_resolved_path_outside_approved_root" -Message "Provider config field '$Name' resolves outside approved root '$Root': $Path"
    }
}

function Test-PathUnderAnyApprovedRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$Roots
    )
    foreach ($root in $Roots) {
        if (
            (Test-ImmoAppPathUnderRoot -Root $root -Path $Path) -and
            (Test-ImmoAppResolvedPathUnderRoot -Root $root -Path $Path)
        ) {
            return $true
        }
    }
    return $false
}

function Assert-ProofPathUnderApprovedRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$Roots,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if (Test-ImmoAppPathHasReparsePoint -Path $Path) {
        Throw-ProviderValidation -ReasonCode "managed_runtime_reparse_point_not_allowed" -Message "Provider config field '$Name' contains a reparse point: $Path"
    }
    if (-not (Test-PathUnderAnyApprovedRoot -Path $Path -Roots $Roots)) {
        Throw-ProviderValidation -ReasonCode "managed_runtime_proof_provider_path_not_approved" -Message "Proof-only provider field '$Name' must be under canonical ProgramData runtime roots or the explicit test ProgramData root: $Path"
    }
}

function Get-ProofApprovedRoots {
    param(
        [Parameter(Mandatory = $true)][object]$CanonicalPaths,
        [Parameter(Mandatory = $true)][object]$ActivePaths,
        [Parameter(Mandatory = $true)][string]$Kind
    )
    $roots = New-Object System.Collections.Generic.List[string]
    if ($Kind -eq "runtime") {
        $roots.Add([string]$CanonicalPaths.RuntimeRoot)
    }
    elseif ($Kind -eq "data") {
        $roots.Add([string]$CanonicalPaths.DataRoot)
    }
    elseif ($Kind -eq "logs") {
        $roots.Add([string]$CanonicalPaths.LogsRoot)
    }
    elseif ($Kind -eq "config") {
        $roots.Add([string]$CanonicalPaths.ConfigRoot)
        $roots.Add([string]$CanonicalPaths.RuntimeRoot)
    }
    if ((Get-ImmoAppRuntimeRootSource) -eq "test_programdata_root") {
        if ($Kind -eq "runtime") {
            $roots.Add([string]$ActivePaths.RuntimeRoot)
        }
        elseif ($Kind -eq "data") {
            $roots.Add([string]$ActivePaths.DataRoot)
        }
        elseif ($Kind -eq "logs") {
            $roots.Add([string]$ActivePaths.LogsRoot)
        }
        elseif ($Kind -eq "config") {
            $roots.Add([string]$ActivePaths.ConfigRoot)
            $roots.Add([string]$ActivePaths.RuntimeRoot)
        }
    }
    return @($roots.ToArray() | Select-Object -Unique)
}

function Assert-LowerHexSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if ($Value -notmatch "^[0-9a-f]{64}$") {
        Throw-ProviderValidation -ReasonCode "invalid_provider_config" -Message "Provider config field '$Name' must be 64 lowercase hex characters."
    }
}

function Assert-LowerGitSha {
    param(
        [string]$Value,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if ($Value -notmatch "^[0-9a-f]{40}$") {
        Throw-ProviderValidation -ReasonCode "managed_runtime_missing_source_provenance" -Message "Provider config field '$Name' must be a 40-character lowercase git SHA."
    }
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-RelativePathUnderRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd("\", "/")
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    $separator = [System.IO.Path]::DirectorySeparatorChar
    if ($pathFull.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return ""
    }
    if ($pathFull.StartsWith($rootFull + $separator, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $pathFull.Substring($rootFull.Length + 1).Replace("\", "/")
    }
    return $pathFull.Replace("\", "/")
}

function Get-InventoryFileEntry {
    param(
        [Parameter(Mandatory = $true)]$Inventory,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )
    $normalized = $RelativePath.Replace("\", "/")
    foreach ($entry in @($Inventory.files)) {
        if ([string]$entry.path -eq $normalized) {
            return $entry
        }
    }
    return $null
}

function Assert-InstalledFileMatchesInventory {
    param(
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [Parameter(Mandatory = $true)][string]$InstalledPath,
        [Parameter(Mandatory = $true)]$Inventory,
        [Parameter(Mandatory = $true)][string]$CriticalPath,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $relative = Get-RelativePathUnderRoot -Root $InstallRoot -Path $InstalledPath
    if ($relative -ne $CriticalPath) {
        Throw-ProviderValidation -ReasonCode "managed_runtime_missing_inventory" -Message "$Label must match inventory critical executable path '$CriticalPath'. actual=$relative"
    }
    $entry = Get-InventoryFileEntry -Inventory $Inventory -RelativePath $relative
    if ($null -eq $entry) {
        Throw-ProviderValidation -ReasonCode "managed_runtime_missing_inventory" -Message "$Label is not listed in package inventory files: $relative"
    }
    $actualSha = Get-FileSha256 -Path $InstalledPath
    if ($actualSha -ne [string]$entry.sha256) {
        Throw-ProviderValidation -ReasonCode "managed_runtime_installed_file_hash_mismatch" -Message "$Label hash does not match package inventory for $relative."
    }
}

function Get-DockerDesktopPath {
    $candidates = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Docker\Docker\Docker Desktop.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return ""
}

function Invoke-NativeText {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    try {
        $output = & $Command @Arguments 2>$null
        if ($LASTEXITCODE -ne 0) { return "" }
        return (($output | Out-String).Trim())
    }
    catch {
        return ""
    }
}

function Test-NativeCommandOk {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    try {
        & $Command @Arguments *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Get-WslPolicyDefaultPath {
    return (Join-Path (Get-ImmoAppRuntimePaths).ConfigRoot "managed_wsl2_runtime_policy.json")
}

function Read-ImmoAppManagedWslPolicy {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    if (Test-ImmoAppPathHasReparsePoint -Path $Path) {
        throw "wsl_policy_reparse_point|WSL2 policy path contains a reparse point, symlink, or junction: $Path"
    }
    $policy = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ([string](Get-ImmoAppObjectValue -Data $policy -Name "kind") -ne "immoapp_managed_wsl2_runtime_policy") {
        throw "wsl_policy_invalid|WSL2 policy JSON has the wrong kind."
    }
    if ([int](Get-ImmoAppObjectValue -Data $policy -Name "schema_version") -ne 1) {
        throw "wsl_policy_invalid|WSL2 policy JSON has an unsupported schema_version."
    }
    return $policy
}

$paths = Get-ImmoAppRuntimePaths
$canonicalPaths = Get-ImmoAppCanonicalRuntimePaths
$runtimeRootSource = Get-ImmoAppRuntimeRootSource
$runtimeRootIsCanonical = Test-ImmoAppUsingCanonicalRuntimeRoot
$runtimeRoot = [System.IO.Path]::GetFullPath($canonicalPaths.RuntimeRoot)
$dataRootApproved = [System.IO.Path]::GetFullPath($canonicalPaths.DataRoot)
$logsRootApproved = [System.IO.Path]::GetFullPath($canonicalPaths.LogsRoot)
$configRootApproved = [System.IO.Path]::GetFullPath($canonicalPaths.ConfigRoot)
$activeProviderConfigPath = [System.IO.Path]::GetFullPath((Get-ImmoAppHubRuntimeProviderConfigPath))
$canonicalProviderConfigPath = [System.IO.Path]::GetFullPath((Get-ImmoAppCanonicalHubRuntimeProviderConfigPath))
if ([string]::IsNullOrWhiteSpace($ProviderConfigPath)) {
    $ProviderConfigPath = $activeProviderConfigPath
}
else {
    $ProviderConfigPath = [System.IO.Path]::GetFullPath($ProviderConfigPath)
}
$providerConfigIsCanonical = $ProviderConfigPath.Equals($canonicalProviderConfigPath, [System.StringComparison]::OrdinalIgnoreCase)
$providerPathSafe = $true
$providerPathSafetyError = ""
try {
    if ($providerConfigIsCanonical) {
        Assert-ImmoAppCanonicalProviderConfigPathSafe -Path $ProviderConfigPath | Out-Null
    }
    else {
        Assert-ImmoAppCanonicalProviderConfigPathSafe -Path $ProviderConfigPath -AllowNonCanonical | Out-Null
    }
}
catch {
    $providerPathSafe = $false
    $providerPathSafetyError = $_.Exception.Message
}

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
$dockerCliAvailable = $null -ne $dockerCommand
$dockerDesktopPath = Get-DockerDesktopPath
$dockerDesktopProcess = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
$dockerDesktopDetected = -not [string]::IsNullOrWhiteSpace($dockerDesktopPath) -or $null -ne $dockerDesktopProcess
$dockerEngineVersion = if ($dockerCliAvailable) { Invoke-NativeText -Command "docker" -Arguments @("version", "--format", "{{.Server.Version}}") } else { "" }
$dockerEngineReachable = -not [string]::IsNullOrWhiteSpace($dockerEngineVersion)
$composeVersion = if ($dockerCliAvailable) { Invoke-NativeText -Command "docker" -Arguments @("compose", "version", "--short") } else { "" }
$composeAvailable = -not [string]::IsNullOrWhiteSpace($composeVersion)

$wslCommand = Get-Command wsl -ErrorAction SilentlyContinue
$wslExePresent = $null -ne $wslCommand
$wslStatusText = if ($wslExePresent) { Invoke-NativeText -Command "wsl" -Arguments @("--status") } else { "" }
$wslStatusAvailable = -not [string]::IsNullOrWhiteSpace($wslStatusText)
$wslVersionText = if ($wslExePresent) { Invoke-NativeText -Command "wsl" -Arguments @("--version") } else { "" }
$wslVersionAvailable = -not [string]::IsNullOrWhiteSpace($wslVersionText)
$wslDefaultVersion = ""
if ($wslStatusText -match "Default Version:\s*(?<version>\d+)") {
    $wslDefaultVersion = $Matches["version"]
}
$wslDistributionsText = if ($wslExePresent) { Invoke-NativeText -Command "wsl" -Arguments @("-l", "-q") } else { "" }
$wslDistributions = @()
if (-not [string]::IsNullOrWhiteSpace($wslDistributionsText)) {
    $wslDistributions = @($wslDistributionsText.Replace([string][char]0, "") -split "(`r`n|`n|`r)" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { [string]$_.Trim() })
}
$wslConfigPath = [System.IO.Path]::GetFullPath((Join-Path $env:USERPROFILE ".wslconfig"))
$wslConfigPresent = Test-Path -LiteralPath $wslConfigPath -PathType Leaf
$wslPolicyPath = [System.IO.Path]::GetFullPath((Get-WslPolicyDefaultPath))
$wslPolicyPresent = Test-Path -LiteralPath $wslPolicyPath -PathType Leaf
$wslPolicy = $null
$wslPolicyError = ""
$wslPolicySha = ""
$managedWslPolicyStatus = "missing"
$managedWslRuntimeCandidateStatus = "NO_GO"
$runtimeArtifactStatus = "NO-GO"
$runtimeStartStatus = "NO-GO"
$runtimeStartReasonCode = ""
$runtimeStartEvidencePath = ""
$runtimeStartEvidenceSha256 = ""
$managedRuntimeCommandPath = ""
$managedComposeCommandPath = ""
$frontDoorHealthStatus = "NO-GO"
$frontDoorLiveProbe = [ordered]@{
    front_door_url = ""
    health_status = 0
    identity_status = 0
    front_door_header = ""
    identity_kind = ""
    identity_schema_version = 0
    front_door_health_status = "not_checked"
    failure_reason = ""
}
if ($wslPolicyPresent) {
    try {
        $wslPolicy = Read-ImmoAppManagedWslPolicy -Path $wslPolicyPath
        $wslPolicySha = Get-FileSha256 -Path $wslPolicyPath
        $managedWslPolicyStatus = if ([string](Get-ImmoAppObjectValue -Data $wslPolicy -Name "policy_result") -eq "GO") { "GO" } else { "NO-GO" }
    }
    catch {
        $wslPolicyError = $_.Exception.Message
        $managedWslPolicyStatus = "invalid"
    }
}

$provider = $null
$providerError = ""
$providerPresent = $providerPathSafe -and (Test-Path -LiteralPath $ProviderConfigPath)
if ($providerPresent) {
    try {
        $provider = Get-Content -LiteralPath $ProviderConfigPath -Raw | ConvertFrom-Json
    }
    catch {
        $providerError = "Provider config could not be parsed: $($_.Exception.Message)"
    }
}
elseif (-not $providerPathSafe) {
    $providerError = $providerPathSafetyError
}

$runtimeMode = "unavailable"
$agencyStatus = "NO_GO"
$runtimeVisible = $false
$internalProofStatus = "NO_GO"
$reasonCode = "runtime_unavailable"
$reason = "No approved Hub runtime provider was detected."
$nextAction = "Install or configure an ImmoApp-managed container runtime before real agency proof."
$runtimeVersion = if ($dockerEngineReachable) { "docker=$dockerEngineVersion; compose=$composeVersion" } else { "" }
$runtimeInstallPath = $dockerDesktopPath
$runtimeCommand = if ($dockerCliAvailable) { "docker" } else { "" }
$composeCommand = if ($dockerCliAvailable) { "docker" } else { "" }
$composePrefix = if ($dockerCliAvailable) { @("compose") } else { @() }
$providerValid = $false
$providerSummary = [ordered]@{}

if ($providerPresent -and [string]::IsNullOrWhiteSpace($providerError)) {
    try {
        Assert-NoProviderSecretFields -Node $provider
        $kind = Get-RequiredProviderString -Provider $provider -Name "kind"
        if ($kind -ne "immoapp_hub_runtime_provider") {
            throw "Provider config kind must be immoapp_hub_runtime_provider."
        }
        $schemaVersion = [int](Get-ImmoAppObjectValue -Data $provider -Name "schema_version")
        if ($schemaVersion -ne 1) {
            throw "Provider config schema_version must be 1."
        }
        $providerMode = Get-RequiredProviderString -Provider $provider -Name "provider_mode"
        if ($providerMode -eq "managed_wsl2_container_runtime_candidate") {
            $runtimeDependencyMode = Get-RequiredProviderString -Provider $provider -Name "runtime_dependency_mode"
            if ($runtimeDependencyMode -ne "managed_wsl2_container_runtime_candidate") {
                Throw-ProviderValidation -ReasonCode "invalid_provider_config" -Message "WSL2 candidate provider requires runtime_dependency_mode=managed_wsl2_container_runtime_candidate."
            }
            $runtimeProvider = Get-RequiredProviderString -Provider $provider -Name "runtime_provider"
            if ($runtimeProvider -ne "wsl2") {
                Throw-ProviderValidation -ReasonCode "invalid_provider_config" -Message "WSL2 candidate provider requires runtime_provider=wsl2."
            }
            $policyPath = Get-RequiredProviderString -Provider $provider -Name "wsl_policy_json_path"
            $policySha = Get-RequiredProviderString -Provider $provider -Name "wsl_policy_sha256"
            $configPlanPath = Get-RequiredProviderString -Provider $provider -Name "wsl_config_plan_json_path"
            $configPlanSha = Get-RequiredProviderString -Provider $provider -Name "wsl_config_plan_sha256"
            Assert-LowerHexSha256 -Value $policySha -Name "wsl_policy_sha256"
            Assert-LowerHexSha256 -Value $configPlanSha -Name "wsl_config_plan_sha256"
            $policyPath = Assert-ExistingPath -Path $policyPath -Name "wsl_policy_json_path"
            $configPlanPath = Assert-ExistingPath -Path $configPlanPath -Name "wsl_config_plan_json_path"
            $policyRoots = Get-ProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "config"
            $configPlanRoots = @(
                (Get-ProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "config") +
                (Get-ProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "logs")
            ) | Select-Object -Unique
            Assert-ProofPathUnderApprovedRoot -Path $policyPath -Roots $policyRoots -Name "wsl_policy_json_path"
            Assert-ProofPathUnderApprovedRoot -Path $configPlanPath -Roots $configPlanRoots -Name "wsl_config_plan_json_path"
            $actualPolicySha = Get-FileSha256 -Path $policyPath
            if ($actualPolicySha -ne $policySha) {
                Throw-ProviderValidation -ReasonCode "wsl_policy_hash_mismatch" -Message "WSL2 policy hash does not match provider config."
            }
            $actualConfigPlanSha = Get-FileSha256 -Path $configPlanPath
            if ($actualConfigPlanSha -ne $configPlanSha) {
                Throw-ProviderValidation -ReasonCode "wsl_config_plan_hash_mismatch" -Message "WSL2 config plan hash does not match provider config."
            }
            $policy = Read-ImmoAppManagedWslPolicy -Path $policyPath
            $configPlan = Get-Content -LiteralPath $configPlanPath -Raw | ConvertFrom-Json
            if ([string](Get-ImmoAppObjectValue -Data $configPlan -Name "kind") -ne "immoapp_managed_wsl2_runtime_config_plan") {
                Throw-ProviderValidation -ReasonCode "wsl_config_plan_invalid" -Message "WSL2 config plan JSON has the wrong kind."
            }
            if ([int](Get-ImmoAppObjectValue -Data $configPlan -Name "schema_version") -ne 1) {
                Throw-ProviderValidation -ReasonCode "wsl_config_plan_invalid" -Message "WSL2 config plan JSON has an unsupported schema_version."
            }
            if ([string](Get-ImmoAppObjectValue -Data $configPlan -Name "plan_result") -ne "GO") {
                Throw-ProviderValidation -ReasonCode "wsl_config_plan_not_go" -Message "WSL2 config plan must be GO for candidate runtime proof."
            }
            if ([string](Get-ImmoAppObjectValue -Data $policy -Name "policy_result") -ne "GO") {
                Throw-ProviderValidation -ReasonCode "wsl_policy_not_go" -Message "WSL2 policy must be GO before candidate runtime proof."
            }
            if ([double](Get-ImmoAppObjectValue -Data $policy -Name "total_memory_gb") -lt 8) {
                Throw-ProviderValidation -ReasonCode "machine_below_minimum_hub_ram" -Message "Machine is below the 8 GB minimum Hub RAM policy."
            }
            if ([string](Get-ImmoAppObjectValue -Data $policy -Name "global_wsl_config_scope") -ne "True") {
                Throw-ProviderValidation -ReasonCode "wsl_policy_invalid" -Message "WSL2 policy must record global_wsl_config_scope=true."
            }
            $configPolicy = Get-ImmoAppObjectValue -Data $configPlan -Name "policy_json"
            if (
                [int](Get-ImmoAppObjectValue -Data $configPolicy -Name "planned_wsl_memory_gb") -ne [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_memory_gb") -or
                [int](Get-ImmoAppObjectValue -Data $configPolicy -Name "planned_wsl_processors") -ne [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_processors") -or
                [int](Get-ImmoAppObjectValue -Data $configPolicy -Name "planned_wsl_swap_gb") -ne [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_swap_gb") -or
                [string](Get-ImmoAppObjectValue -Data $configPolicy -Name "planned_auto_memory_reclaim") -ne [string](Get-ImmoAppObjectValue -Data $policy -Name "planned_auto_memory_reclaim") -or
                [string](Get-ImmoAppObjectValue -Data $configPolicy -Name "selected_hub_runtime_profile") -ne [string](Get-ImmoAppObjectValue -Data $policy -Name "selected_hub_runtime_profile")
            ) {
                Throw-ProviderValidation -ReasonCode "wsl_config_plan_policy_mismatch" -Message "WSL2 config plan does not match the registered policy evidence."
            }
            $runtimeMode = "managed_wsl2_container_runtime_candidate"
            $agencyStatus = "NO_GO"
            $internalProofStatus = if ($wslExePresent -and [string](Get-ImmoAppObjectValue -Data $policy -Name "policy_result") -eq "GO") { "GO" } else { "NO_GO" }
            $runtimeArtifactStatus = "NO-GO"
            $runtimeStartStatus = "NO-GO"
            $runtimeStartReasonCode = "managed_wsl2_runtime_artifact_missing"
            $runtimeVisible = $false
            $reasonCode = if ($wslExePresent) { "managed_wsl2_runtime_artifact_missing" } else { "wsl2_unavailable" }
            $reason = if ($wslExePresent) {
                "Managed WSL2 runtime policy is valid, but no ImmoApp-managed runtime artifact has been installed or started."
            } else {
                "Managed WSL2 runtime policy is valid, but wsl.exe is unavailable on this machine."
            }
            $nextAction = "Install and prove a real ImmoApp-managed WSL2/container runtime artifact before agency proof."
            $runtimeVersion = if ($wslVersionAvailable) { $wslVersionText } else { "" }
            $runtimeInstallPath = ""
            $runtimeCommand = ""
            $composeCommand = ""
            $composePrefix = @()
            $providerValid = $true
            $managedWslRuntimeCandidateStatus = if ($wslExePresent) { "GO" } else { "NO-GO" }
            $providerSummary = [ordered]@{
                kind = $kind
                schema_version = $schemaVersion
                provider_mode = $providerMode
                runtime_dependency_mode = $runtimeDependencyMode
                runtime_provider = $runtimeProvider
                proof_only = $true
                wsl_policy_json_path = $policyPath
                wsl_policy_sha256 = $policySha
                wsl_config_plan_json_path = $configPlanPath
                wsl_config_plan_sha256 = $configPlanSha
                planned_wsl_memory_gb = [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_memory_gb")
                planned_wsl_processors = [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_processors")
                planned_wsl_swap_gb = [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_swap_gb")
                planned_auto_memory_reclaim = [string](Get-ImmoAppObjectValue -Data $policy -Name "planned_auto_memory_reclaim")
                wsl_config_apply_performed = [bool](Get-ImmoAppObjectValue -Data $configPlan -Name "apply_performed")
                wsl_shutdown_required = [bool](Get-ImmoAppObjectValue -Data $configPlan -Name "wsl_shutdown_required")
                global_wsl_config_scope = $true
                provider_config_is_canonical = [bool]$providerConfigIsCanonical
                runtime_root_source = $runtimeRootSource
                runtime_root_is_canonical = [bool]$runtimeRootIsCanonical
                effective_proof_only = $true
                provider_validation_status = "valid"
            }
        }
        elseif ($providerMode -eq "managed_wsl2_container_runtime_artifact") {
            $runtimeDependencyMode = Get-RequiredProviderString -Provider $provider -Name "runtime_dependency_mode"
            if ($runtimeDependencyMode -ne "managed_wsl2_container_runtime_artifact") {
                Throw-ProviderValidation -ReasonCode "invalid_provider_config" -Message "Managed WSL2 artifact provider requires runtime_dependency_mode=managed_wsl2_container_runtime_artifact."
            }
            $runtimeProvider = Get-RequiredProviderString -Provider $provider -Name "runtime_provider"
            if ($runtimeProvider -ne "wsl2") {
                Throw-ProviderValidation -ReasonCode "invalid_provider_config" -Message "Managed WSL2 artifact provider requires runtime_provider=wsl2."
            }
            $installedByImmoApp = Convert-ProviderBoolStrict -Value (Get-ImmoAppObjectValue -Data $provider -Name "installed_by_immoapp") -Name "installed_by_immoapp"
            $userVisibleRuntime = Convert-ProviderBoolStrict -Value (Get-ImmoAppObjectValue -Data $provider -Name "user_visible_runtime") -Name "user_visible_runtime"
            $proofOnly = Convert-OptionalProviderBoolStrict -Value (Get-ImmoAppObjectValue -Data $provider -Name "proof_only") -Name "proof_only" -Default $true
            if (-not $installedByImmoApp) {
                Throw-ProviderValidation -ReasonCode "invalid_provider_config" -Message "Managed WSL2 artifact provider requires installed_by_immoapp=true."
            }
            if ($userVisibleRuntime) {
                Throw-ProviderValidation -ReasonCode "invalid_provider_config" -Message "Managed WSL2 artifact provider requires user_visible_runtime=false."
            }
            $policyPath = Get-RequiredProviderString -Provider $provider -Name "wsl_policy_json_path"
            $policySha = Get-RequiredProviderString -Provider $provider -Name "wsl_policy_sha256"
            $configPlanPath = Get-RequiredProviderString -Provider $provider -Name "wsl_config_plan_json_path"
            $configPlanSha = Get-RequiredProviderString -Provider $provider -Name "wsl_config_plan_sha256"
            $artifactInventoryPath = Get-RequiredProviderString -Provider $provider -Name "runtime_artifact_inventory_path"
            $artifactInventorySha = Get-RequiredProviderString -Provider $provider -Name "runtime_artifact_inventory_sha256"
            $sourceCommitSha = Get-OptionalProviderString -Provider $provider -Name "source_commit_sha"
            Assert-LowerHexSha256 -Value $policySha -Name "wsl_policy_sha256"
            Assert-LowerHexSha256 -Value $configPlanSha -Name "wsl_config_plan_sha256"
            Assert-LowerHexSha256 -Value $artifactInventorySha -Name "runtime_artifact_inventory_sha256"
            $policyPath = Assert-ExistingPath -Path $policyPath -Name "wsl_policy_json_path"
            $configPlanPath = Assert-ExistingPath -Path $configPlanPath -Name "wsl_config_plan_json_path"
            $artifactInventoryPath = Assert-ExistingPath -Path $artifactInventoryPath -Name "runtime_artifact_inventory_path"
            $policyRoots = Get-ProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "config"
            $configPlanRoots = @(
                (Get-ProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "config") +
                (Get-ProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "logs")
            ) | Select-Object -Unique
            Assert-ProofPathUnderApprovedRoot -Path $policyPath -Roots $policyRoots -Name "wsl_policy_json_path"
            Assert-ProofPathUnderApprovedRoot -Path $configPlanPath -Roots $configPlanRoots -Name "wsl_config_plan_json_path"
            Assert-ProofPathUnderApprovedRoot -Path $artifactInventoryPath -Roots $configPlanRoots -Name "runtime_artifact_inventory_path"
            if ((Get-FileSha256 -Path $policyPath) -ne $policySha) {
                Throw-ProviderValidation -ReasonCode "wsl_policy_hash_mismatch" -Message "WSL2 policy hash does not match provider config."
            }
            if ((Get-FileSha256 -Path $configPlanPath) -ne $configPlanSha) {
                Throw-ProviderValidation -ReasonCode "wsl_config_plan_hash_mismatch" -Message "WSL2 config plan hash does not match provider config."
            }
            if ((Get-FileSha256 -Path $artifactInventoryPath) -ne $artifactInventorySha) {
                Throw-ProviderValidation -ReasonCode "managed_wsl2_runtime_artifact_inventory_hash_mismatch" -Message "Managed WSL2 runtime artifact inventory hash does not match provider config."
            }
            $policy = Read-ImmoAppManagedWslPolicy -Path $policyPath
            $configPlan = Get-Content -LiteralPath $configPlanPath -Raw | ConvertFrom-Json
            if ([string](Get-ImmoAppObjectValue -Data $configPlan -Name "kind") -ne "immoapp_managed_wsl2_runtime_config_plan") {
                Throw-ProviderValidation -ReasonCode "wsl_config_plan_invalid" -Message "WSL2 config plan JSON has the wrong kind."
            }
            if ([int](Get-ImmoAppObjectValue -Data $configPlan -Name "schema_version") -ne 1) {
                Throw-ProviderValidation -ReasonCode "wsl_config_plan_invalid" -Message "WSL2 config plan JSON has an unsupported schema_version."
            }
            if ([string](Get-ImmoAppObjectValue -Data $configPlan -Name "plan_result") -ne "GO") {
                Throw-ProviderValidation -ReasonCode "wsl_config_plan_not_go" -Message "WSL2 config plan must be GO for managed WSL2 artifact proof."
            }
            if ([string](Get-ImmoAppObjectValue -Data $policy -Name "policy_result") -ne "GO") {
                Throw-ProviderValidation -ReasonCode "wsl_policy_not_go" -Message "WSL2 policy must be GO before managed WSL2 artifact proof."
            }
            $configPolicy = Get-ImmoAppObjectValue -Data $configPlan -Name "policy_json"
            if (
                [int](Get-ImmoAppObjectValue -Data $configPolicy -Name "planned_wsl_memory_gb") -ne [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_memory_gb") -or
                [int](Get-ImmoAppObjectValue -Data $configPolicy -Name "planned_wsl_processors") -ne [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_processors") -or
                [int](Get-ImmoAppObjectValue -Data $configPolicy -Name "planned_wsl_swap_gb") -ne [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_swap_gb") -or
                [string](Get-ImmoAppObjectValue -Data $configPolicy -Name "planned_auto_memory_reclaim") -ne [string](Get-ImmoAppObjectValue -Data $policy -Name "planned_auto_memory_reclaim") -or
                [string](Get-ImmoAppObjectValue -Data $configPolicy -Name "selected_hub_runtime_profile") -ne [string](Get-ImmoAppObjectValue -Data $policy -Name "selected_hub_runtime_profile")
            ) {
                Throw-ProviderValidation -ReasonCode "wsl_config_plan_policy_mismatch" -Message "WSL2 config plan does not match the registered policy evidence."
            }
            $artifactInventory = Get-Content -LiteralPath $artifactInventoryPath -Raw | ConvertFrom-Json
            try {
                $artifactSummary = Assert-ImmoAppManagedWsl2RuntimeArtifactInventoryReady `
                    -Inventory $artifactInventory `
                    -ExpectedInventorySha256 $artifactInventorySha `
                    -ExpectedSourceCommitSha $sourceCommitSha `
                    -ArtifactInventoryPath $artifactInventoryPath `
                    -AllowTestOnlyPath:($proofOnly -or -not $providerConfigIsCanonical -or -not $runtimeRootIsCanonical)
            }
            catch {
                $errorText = $_.Exception.Message
                if ($errorText -match "^(?<code>[a-z0-9_]+)\|(?<message>.*)$") {
                    Throw-ProviderValidation -ReasonCode $Matches["code"] -Message $Matches["message"]
                }
                Throw-ProviderValidation -ReasonCode "managed_wsl2_runtime_artifact_inventory_invalid" -Message $errorText
            }
            $runtimeMode = "managed_wsl2_container_runtime_artifact"
            $agencyStatus = "NO_GO"
            $internalProofStatus = "GO"
            $runtimeArtifactStatus = "GO"
            $runtimeStartStatus = "NO-GO"
            $runtimeStartReasonCode = "managed_wsl2_runtime_start_not_proven"
            $managedRuntimeCommandPath = [string]$artifactSummary.start_command_path
            $managedComposeCommandPath = [string]$artifactSummary.status_command_path
            $managedRestartCommandPath = [string]$artifactSummary.restart_command_path
            $runtimeStartEvidencePath = Join-Path $paths.LogsRoot "managed_wsl2_runtime_start_evidence.json"
            if (Test-Path -LiteralPath $runtimeStartEvidencePath -PathType Leaf) {
                $runtimeStartEvidenceSha256 = Get-FileSha256 -Path $runtimeStartEvidencePath
                try {
                    $startEvidence = Get-Content -LiteralPath $runtimeStartEvidencePath -Raw | ConvertFrom-Json
                    $providerConfigSha = if (Test-Path -LiteralPath $ProviderConfigPath -PathType Leaf) { Get-FileSha256 -Path $ProviderConfigPath } else { "" }
                    if ([string](Get-ImmoAppObjectValue -Data $startEvidence -Name "kind") -ne "immoapp_managed_wsl2_runtime_start_evidence") {
                        throw "wrong kind"
                    }
                    if ([int](Get-ImmoAppObjectValue -Data $startEvidence -Name "schema_version") -ne 1) {
                        throw "wrong schema"
                    }
                    $startEvidenceAction = [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "action")
                    if ($startEvidenceAction -notin @("start", "restart")) {
                        throw "wrong action"
                    }
                    $expectedCommandPath = if ($startEvidenceAction -eq "restart") { $managedRestartCommandPath } else { $managedRuntimeCommandPath }
                    $currentCommandSha = if (Test-Path -LiteralPath $expectedCommandPath -PathType Leaf) { Get-FileSha256 -Path $expectedCommandPath } else { "" }
                    if ([string]::IsNullOrWhiteSpace([string](Get-ImmoAppObjectValue -Data $startEvidence -Name "start_run_id"))) {
                        throw "missing start_run_id"
                    }
                    if ([string](Get-ImmoAppObjectValue -Data $startEvidence -Name "provider_config_sha256") -ne $providerConfigSha) {
                        throw "provider hash mismatch"
                    }
                    if ([string](Get-ImmoAppObjectValue -Data $startEvidence -Name "runtime_artifact_inventory_sha256") -ne $artifactInventorySha) {
                        throw "artifact inventory hash mismatch"
                    }
                    if ([string](Get-ImmoAppObjectValue -Data $startEvidence -Name "managed_runtime_command_sha256") -ne $currentCommandSha) {
                        throw "managed command hash mismatch"
                    }
                    $evidenceImageInventoryPath = [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "image_bundle_inventory_host_path")
                    if ([string]::IsNullOrWhiteSpace($evidenceImageInventoryPath)) {
                        $evidenceImageInventoryPath = [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "image_bundle_inventory_path")
                    }
                    $evidenceImageInventorySha = [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "image_bundle_inventory_sha256")
                    $evidenceImageArchivePath = [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "image_archive_host_path")
                    if ([string]::IsNullOrWhiteSpace($evidenceImageArchivePath)) {
                        $evidenceImageArchivePath = [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "image_archive_path")
                    }
                    $evidenceImageArchiveSha = [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "image_archive_sha256")
                    if (
                        [string]::IsNullOrWhiteSpace($evidenceImageInventoryPath) -or
                        [string]::IsNullOrWhiteSpace($evidenceImageInventorySha) -or
                        [string]::IsNullOrWhiteSpace($evidenceImageArchivePath) -or
                        [string]::IsNullOrWhiteSpace($evidenceImageArchiveSha)
                    ) {
                        throw "missing image bundle proof"
                    }
                    if (-not (Test-Path -LiteralPath $evidenceImageInventoryPath -PathType Leaf)) {
                        throw "image bundle inventory missing"
                    }
                    if (-not (Test-Path -LiteralPath $evidenceImageArchivePath -PathType Leaf)) {
                        throw "image archive missing"
                    }
                    if ((Get-FileSha256 -Path $evidenceImageInventoryPath) -ne $evidenceImageInventorySha) {
                        throw "image bundle inventory hash mismatch"
                    }
                    if ((Get-FileSha256 -Path $evidenceImageArchivePath) -ne $evidenceImageArchiveSha) {
                        throw "image archive hash mismatch"
                    }
                    $frontDoorHealthStatus = [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "front_door_health_status")
                    $storedEvidenceIsGo = (
                        [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "proof_result") -eq "GO" -and
                        [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "runtime_command_status") -eq "GO" -and
                        [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "distro_identity_status") -eq "GO" -and
                        [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "docker_daemon_status") -eq "GO" -and
                        [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "docker_info_status") -eq "GO" -and
                        [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "image_archive_status") -eq "GO" -and
                        [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "image_inventory_status") -eq "GO" -and
                        [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "image_presence_status") -eq "GO" -and
                        [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "compose_payload_status") -eq "GO" -and
                        [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "compose_pull_policy_status") -eq "GO" -and
                        [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "compose_up_status") -eq "GO" -and
                        [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "compose_service_status") -eq "GO" -and
                        $frontDoorHealthStatus -eq "GO" -and
                        [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "front_door_header") -eq "caddy" -and
                        [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "identity_kind") -eq "immoapp_hub_front_door_identity" -and
                        [int](Get-ImmoAppObjectValue -Data $startEvidence -Name "identity_schema_version") -eq 1
                    )
                    if ($storedEvidenceIsGo) {
                        $frontDoorLiveProbe = Test-ImmoAppLiveFrontDoorIdentity -BaseUrl ([string](Get-ImmoAppObjectValue -Data $startEvidence -Name "front_door_url"))
                        $frontDoorHealthStatus = [string]$frontDoorLiveProbe.front_door_health_status
                        if ($frontDoorHealthStatus -eq "GO") {
                            $runtimeStartStatus = "GO"
                            $runtimeStartReasonCode = "managed_wsl2_runtime_start_ready"
                        }
                        else {
                            $runtimeStartStatus = "NO-GO"
                            $runtimeStartReasonCode = "managed_wsl2_front_door_live_probe_failed"
                        }
                    }
                    else {
                        $runtimeStartReasonCode = [string](Get-ImmoAppObjectValue -Data $startEvidence -Name "reason_code")
                        if ([string]::IsNullOrWhiteSpace($runtimeStartReasonCode)) {
                            $runtimeStartReasonCode = "managed_wsl2_runtime_start_not_go"
                        }
                    }
                }
                catch {
                    $runtimeStartStatus = "NO-GO"
                    $runtimeStartReasonCode = "managed_wsl2_runtime_start_evidence_invalid"
                    $frontDoorHealthStatus = "NO-GO"
                }
            }
            $runtimeVisible = $false
            $reasonCode = if ($runtimeStartStatus -eq "GO") { "managed_wsl2_runtime_internal_start_ready" } else { $runtimeStartReasonCode }
            $reason = if ($runtimeStartStatus -eq "GO") {
                "ImmoApp-managed WSL2 runtime artifact has fresh start evidence and Caddy front-door health proof, but agency proof is still blocked by release gates."
            } else {
                "ImmoApp-managed WSL2 runtime artifact inventory is valid, but Hub startup/front-door health is not GO."
            }
            $nextAction = if ($runtimeStartStatus -eq "GO") {
                "Collect network boundary, backup/restore, lifecycle, support, LAN workstation, signing, and HTTPS/cert evidence before agency proof."
            } else {
                "Run Hub Manager start/status/health through the managed WSL2 artifact and fix the reported start/front-door reason."
            }
            $runtimeVersion = if ($wslVersionAvailable) { $wslVersionText } else { "" }
            $runtimeInstallPath = [string]$artifactSummary.artifact_root
            $runtimeCommand = [string]$artifactSummary.runtime_executable_path
            $composeCommand = [string]$artifactSummary.compose_executable_path
            $composePrefix = @()
            $providerValid = $true
            $providerSummary = [ordered]@{
                kind = $kind
                schema_version = $schemaVersion
                provider_mode = $providerMode
                runtime_dependency_mode = $runtimeDependencyMode
                runtime_provider = $runtimeProvider
                installed_by_immoapp = $true
                user_visible_runtime = $false
                proof_only = [bool]$proofOnly
                runtime_artifact_status = "GO"
                runtime_start_status = $runtimeStartStatus
                runtime_start_reason_code = $runtimeStartReasonCode
                runtime_start_evidence_path = $runtimeStartEvidencePath
                runtime_start_evidence_sha256 = $runtimeStartEvidenceSha256
                runtime_artifact_root = [string]$artifactSummary.artifact_root
                runtime_artifact_tree_sha256 = [string]$artifactSummary.artifact_tree_sha256
                runtime_artifact_inventory_path = $artifactInventoryPath
                runtime_artifact_inventory_sha256 = $artifactInventorySha
                runtime_executable_path = [string]$artifactSummary.runtime_executable_path
                compose_executable_path = [string]$artifactSummary.compose_executable_path
                managed_runtime_command_path = $managedRuntimeCommandPath
                managed_compose_command_path = $managedComposeCommandPath
                managed_logs_command_path = [string](Get-ImmoAppObjectValue -Data $Provider -Name "managed_logs_command_path")
                managed_backup_command_path = [string](Get-ImmoAppObjectValue -Data $Provider -Name "managed_backup_command_path")
                managed_health_command_path = [string](Get-ImmoAppObjectValue -Data $Provider -Name "managed_health_command_path")
                managed_stop_command_path = [string](Get-ImmoAppObjectValue -Data $Provider -Name "managed_stop_command_path")
                managed_restart_command_path = [string](Get-ImmoAppObjectValue -Data $Provider -Name "managed_restart_command_path")
                managed_bootstrap_command_path = [string](Get-ImmoAppObjectValue -Data $Provider -Name "managed_bootstrap_command_path")
                image_bundle_archive_path = [string](Get-ImmoAppObjectValue -Data $Provider -Name "image_bundle_archive_path")
                image_bundle_inventory_path = [string](Get-ImmoAppObjectValue -Data $Provider -Name "image_bundle_inventory_path")
                compose_payload_path = [string](Get-ImmoAppObjectValue -Data $Provider -Name "compose_payload_path")
                compose_pull_policy = [string](Get-ImmoAppObjectValue -Data $Provider -Name "compose_pull_policy")
                required_compose_services = @(Get-ImmoAppObjectValue -Data $Provider -Name "required_compose_services")
                expected_distro_name = [string](Get-ImmoAppObjectValue -Data $Provider -Name "expected_distro_name")
                front_door_health_status = $frontDoorHealthStatus
                front_door_live_probe = $frontDoorLiveProbe
                source_commit_sha = $sourceCommitSha
                wsl_policy_json_path = $policyPath
                wsl_policy_sha256 = $policySha
                wsl_config_plan_json_path = $configPlanPath
                wsl_config_plan_sha256 = $configPlanSha
                planned_wsl_memory_gb = [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_memory_gb")
                planned_wsl_processors = [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_processors")
                planned_wsl_swap_gb = [int](Get-ImmoAppObjectValue -Data $policy -Name "planned_wsl_swap_gb")
                planned_auto_memory_reclaim = [string](Get-ImmoAppObjectValue -Data $policy -Name "planned_auto_memory_reclaim")
                selected_hub_runtime_profile = [string](Get-ImmoAppObjectValue -Data $policy -Name "selected_hub_runtime_profile")
                provider_config_is_canonical = [bool]$providerConfigIsCanonical
                runtime_root_source = $runtimeRootSource
                runtime_root_is_canonical = [bool]$runtimeRootIsCanonical
                effective_proof_only = $true
                provider_validation_status = "valid"
            }
        }
        else {
        $installedByImmoApp = Convert-ProviderBoolStrict -Value (Get-ImmoAppObjectValue -Data $provider -Name "installed_by_immoapp") -Name "installed_by_immoapp"
        $userVisibleRuntime = Convert-ProviderBoolStrict -Value (Get-ImmoAppObjectValue -Data $provider -Name "user_visible_runtime") -Name "user_visible_runtime"
        $runtimeExecutablePath = Get-RequiredProviderString -Provider $provider -Name "runtime_executable_path"
        $installRoot = Get-RequiredProviderString -Provider $provider -Name "install_root"
        $dataRoot = Get-RequiredProviderString -Provider $provider -Name "data_root"
        $logsRoot = Get-RequiredProviderString -Provider $provider -Name "logs_root"
        $managedServiceName = Get-OptionalProviderString -Provider $provider -Name "managed_service_name"
        $composeExecutablePath = Get-OptionalProviderString -Provider $provider -Name "compose_executable_path"
        $composeMode = Get-OptionalProviderString -Provider $provider -Name "compose_mode"
        $proofOnly = Convert-OptionalProviderBoolStrict -Value (Get-ImmoAppObjectValue -Data $provider -Name "proof_only") -Name "proof_only" -Default $false
        $effectiveProofOnly = ($proofOnly -or -not $providerConfigIsCanonical -or -not $runtimeRootIsCanonical)
        $packageSha256 = Get-OptionalProviderString -Provider $provider -Name "package_sha256"
        $packageInventoryPath = Get-OptionalProviderString -Provider $provider -Name "package_inventory_path"
        $sourceCommitSha = Get-OptionalProviderString -Provider $provider -Name "source_commit_sha"
        $installerSha256 = Get-OptionalProviderString -Provider $provider -Name "installer_sha256"
        if ([string]::IsNullOrWhiteSpace($composeMode)) {
            $composeMode = if ($composeExecutablePath) { "standalone" } else { "docker_cli_plugin" }
        }

        $runtimeExecutablePath = Assert-ExistingPath -Path $runtimeExecutablePath -Name "runtime_executable_path"
        $installRoot = Assert-ExistingPath -Path $installRoot -Name "install_root" -Directory
        $dataRoot = Assert-ExistingPath -Path $dataRoot -Name "data_root" -Directory
        $logsRoot = Assert-ExistingPath -Path $logsRoot -Name "logs_root" -Directory
        if ($composeMode -eq "standalone") {
            if ([string]::IsNullOrWhiteSpace($composeExecutablePath)) {
                throw "compose_mode=standalone requires compose_executable_path."
            }
            $composeExecutablePath = Assert-ExistingPath -Path $composeExecutablePath -Name "compose_executable_path"
        }
        if ($packageInventoryPath) {
            $packageInventoryPath = Assert-ExistingPath -Path $packageInventoryPath -Name "package_inventory_path"
        }

        if ($providerMode -eq "managed_container_runtime") {
            if (-not $installedByImmoApp) {
                throw "managed_container_runtime requires installed_by_immoapp=true."
            }
            if ($userVisibleRuntime) {
                throw "managed_container_runtime requires user_visible_runtime=false."
            }
            if (Test-UserVisibleRuntimePath -Path $runtimeExecutablePath) {
                throw "managed_container_runtime cannot use a user-visible Docker Desktop executable path."
            }
            if (-not $effectiveProofOnly) {
                Assert-PathUnderApprovedRoot -Path $runtimeExecutablePath -Root $runtimeRoot -Name "runtime_executable_path"
                Assert-PathUnderApprovedRoot -Path $installRoot -Root $runtimeRoot -Name "install_root"
                Assert-PathUnderApprovedRoot -Path $dataRoot -Root $dataRootApproved -Name "data_root"
                Assert-PathUnderApprovedRoot -Path $logsRoot -Root $logsRootApproved -Name "logs_root"
                if ([string]::IsNullOrWhiteSpace($packageInventoryPath)) {
                    Throw-ProviderValidation -ReasonCode "managed_runtime_missing_inventory" -Message "Production managed runtime requires package_inventory_path."
                }
                if (-not (Test-ImmoAppPathUnderRoot -Root $runtimeRoot -Path $packageInventoryPath) -and -not (Test-ImmoAppPathUnderRoot -Root $configRootApproved -Path $packageInventoryPath)) {
                    Throw-ProviderValidation -ReasonCode "managed_runtime_outside_approved_root" -Message "Provider config field 'package_inventory_path' must be under runtime or config root: $packageInventoryPath"
                }
                if ([string]::IsNullOrWhiteSpace($packageSha256)) {
                    Throw-ProviderValidation -ReasonCode "managed_runtime_missing_inventory" -Message "Production managed runtime requires package_sha256."
                }
                Assert-LowerHexSha256 -Value $packageSha256 -Name "package_sha256"
                if ([string]::IsNullOrWhiteSpace($installerSha256)) {
                    Throw-ProviderValidation -ReasonCode "invalid_provider_config" -Message "Production managed runtime requires installer_sha256."
                }
                Assert-LowerHexSha256 -Value $installerSha256 -Name "installer_sha256"
                $inventory = Get-Content -LiteralPath $packageInventoryPath -Raw | ConvertFrom-Json
                try {
                    Assert-ImmoAppManagedRuntimePackageInventoryReady `
                        -Inventory $inventory `
                        -ExpectedPackageSha256 $packageSha256 `
                        -ExpectedSourceCommitSha $sourceCommitSha `
                        -PackageInventoryPath $packageInventoryPath `
                        -InstallRoot $installRoot `
                        -RuntimeExecutablePath $runtimeExecutablePath `
                        -ComposeExecutablePath $composeExecutablePath `
                        -RuntimePaths $canonicalPaths
                }
                catch {
                    $errorText = $_.Exception.Message
                    if ($errorText -match "^(?<code>[a-z0-9_]+)\|(?<message>.*)$") {
                        Throw-ProviderValidation -ReasonCode $Matches["code"] -Message $Matches["message"]
                    }
                    Throw-ProviderValidation -ReasonCode "invalid_provider_config" -Message $errorText
                }
            }
            else {
                $proofRuntimeRoots = Get-ProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "runtime"
                $proofDataRoots = Get-ProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "data"
                $proofLogsRoots = Get-ProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "logs"
                $proofInventoryRoots = Get-ProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "config"
                Assert-ProofPathUnderApprovedRoot -Path $runtimeExecutablePath -Roots $proofRuntimeRoots -Name "runtime_executable_path"
                Assert-ProofPathUnderApprovedRoot -Path $installRoot -Roots $proofRuntimeRoots -Name "install_root"
                Assert-ProofPathUnderApprovedRoot -Path $dataRoot -Roots $proofDataRoots -Name "data_root"
                Assert-ProofPathUnderApprovedRoot -Path $logsRoot -Roots $proofLogsRoots -Name "logs_root"
                if ($packageInventoryPath) {
                    Assert-ProofPathUnderApprovedRoot -Path $packageInventoryPath -Roots $proofInventoryRoots -Name "package_inventory_path"
                }
                if ($packageSha256) {
                    Assert-LowerHexSha256 -Value $packageSha256 -Name "package_sha256"
                }
                if ($installerSha256) {
                    Assert-LowerHexSha256 -Value $installerSha256 -Name "installer_sha256"
                }
            }
            if ($composeMode -eq "standalone") {
                if (-not $effectiveProofOnly) {
                    Assert-PathUnderApprovedRoot -Path $composeExecutablePath -Root $runtimeRoot -Name "compose_executable_path"
                }
                else {
                    $proofRuntimeRoots = Get-ProofApprovedRoots -CanonicalPaths $canonicalPaths -ActivePaths $paths -Kind "runtime"
                    Assert-ProofPathUnderApprovedRoot -Path $composeExecutablePath -Roots $proofRuntimeRoots -Name "compose_executable_path"
                }
                $composeCommand = $composeExecutablePath
                $composePrefix = @()
                $composeOk = Test-NativeCommandOk -Command $composeCommand -Arguments @("version")
            }
            elseif ($composeMode -eq "docker_cli_plugin") {
                $composeCommand = $runtimeExecutablePath
                $composePrefix = @("compose")
                $composeOk = Test-NativeCommandOk -Command $runtimeExecutablePath -Arguments @("compose", "version")
            }
            else {
                throw "compose_mode must be docker_cli_plugin or standalone."
            }
            $engineVersion = Invoke-NativeText -Command $runtimeExecutablePath -Arguments @("version", "--format", "{{.Server.Version}}")
            if ([string]::IsNullOrWhiteSpace($engineVersion)) {
                Throw-ProviderValidation -ReasonCode "managed_runtime_command_failed" -Message "Managed runtime executable did not return a server version."
            }
            if (-not $composeOk) {
                Throw-ProviderValidation -ReasonCode "managed_runtime_compose_failed" -Message "Managed runtime Compose command did not pass version check."
            }
            $runtimeMode = "managed_container_runtime"
            $agencyStatus = if ($effectiveProofOnly) { "NO_GO" } else { "GO" }
            $internalProofStatus = "GO"
            $runtimeArtifactStatus = "GO"
            $runtimeStartStatus = "GO"
            $runtimeStartReasonCode = ""
            $runtimeVisible = $false
            $reasonCode = if (-not $providerConfigIsCanonical) {
                "managed_runtime_noncanonical_provider_config"
            } elseif (-not $runtimeRootIsCanonical) {
                "noncanonical_runtime_root"
            } elseif ($proofOnly) {
                "managed_runtime_proof_only"
            } else {
                "managed_runtime_ready"
            }
            $reason = if (-not $providerConfigIsCanonical) {
                "ImmoApp-managed runtime provider is reachable, but the provider config path is non-canonical and cannot satisfy agency readiness."
            } elseif (-not $runtimeRootIsCanonical) {
                "ImmoApp-managed runtime provider is reachable, but the active runtime root is not the canonical ProgramData root and cannot satisfy agency readiness."
            } elseif ($proofOnly) {
                "ImmoApp-managed runtime proof provider is configured and reachable, but it is marked proof_only and is not agency-ready."
            } else {
                "ImmoApp-managed hidden container runtime is configured and reachable."
            }
            $nextAction = if (-not $providerConfigIsCanonical) {
                "Write the provider to the canonical ProgramData config path before real agency proof."
            } elseif (-not $runtimeRootIsCanonical) {
                "Install the managed runtime under the canonical C:\ProgramData\ImmoApp roots before real agency proof."
            } elseif ($proofOnly) {
                "Replace proof-only provider with a production managed runtime package before real agency proof."
            } else {
                "Run Hub setup/status proof and LAN workstation proof."
            }
            $runtimeVersion = "runtime=$engineVersion"
            $runtimeInstallPath = $installRoot
            $runtimeCommand = $runtimeExecutablePath
            $providerValid = $true
        }
        elseif ($providerMode -eq "native_windows_services") {
            $runtimeMode = "native_windows_services"
            $runtimeVisible = $false
            $agencyStatus = "NO_GO"
            $internalProofStatus = "NO_GO"
            $reasonCode = "native_services_deferred"
            $reason = "Native Windows services runtime is deferred and cannot be agency-ready until a real service verifier exists."
            $nextAction = "Do not use native services for agency proof until the service runtime exists and is verified by code, not provider booleans."
            $providerValid = $false
        }
        else {
            throw "Unsupported provider_mode '$providerMode'."
        }

        $providerSummary = [ordered]@{
            kind = $kind
            schema_version = $schemaVersion
            provider_mode = $providerMode
            installed_by_immoapp = [bool]$installedByImmoApp
            user_visible_runtime = [bool]$userVisibleRuntime
            proof_only = [bool]$proofOnly
            runtime_executable_path = $runtimeExecutablePath
            compose_executable_path = $composeExecutablePath
            compose_mode = $composeMode
            install_root = $installRoot
            data_root = $dataRoot
            logs_root = $logsRoot
            managed_service_name = $managedServiceName
            source_commit_sha = $sourceCommitSha
            installer_sha256 = $installerSha256
            package_sha256 = $packageSha256
            package_inventory_path = $packageInventoryPath
            vendor_provenance_path = if ($packageInventoryPath -and (Test-Path -LiteralPath $packageInventoryPath)) {
                $inventoryForSummary = Get-Content -LiteralPath $packageInventoryPath -Raw | ConvertFrom-Json
                [string](Get-ImmoAppObjectValue -Data $inventoryForSummary -Name "vendor_provenance_path")
            } else { "" }
            provider_config_is_canonical = [bool]$providerConfigIsCanonical
            runtime_root_source = $runtimeRootSource
            runtime_root_is_canonical = [bool]$runtimeRootIsCanonical
            effective_proof_only = [bool]$effectiveProofOnly
            provider_validation_status = if ($providerValid) { "valid" } else { "invalid" }
            approved_runtime_root = $runtimeRoot
            approved_data_root = $dataRootApproved
            approved_logs_root = $logsRootApproved
        }
        }
    }
    catch {
        $providerError = $_.Exception.Message
        $providerReasonCode = "invalid_provider_config"
        if ($providerError -match "^(?<code>[a-z0-9_]+)\|(?<message>.*)$") {
            $providerReasonCode = $Matches["code"]
            $providerError = $Matches["message"]
        }
        $runtimeMode = "unavailable"
        $agencyStatus = "NO_GO"
        $runtimeVisible = $false
        $internalProofStatus = "NO_GO"
        $reasonCode = $providerReasonCode
        $reason = "Hub runtime provider config is invalid: $providerError"
        $nextAction = "Fix or remove the malformed provider config, then rerun runtime detection."
        $runtimeVersion = ""
        $runtimeInstallPath = ""
        $runtimeCommand = ""
        $composeCommand = ""
        $composePrefix = @()
    }
}
elseif ($providerError) {
    $reasonCode = "invalid_provider_config"
    if ($providerError -match "^(?<code>[a-z0-9_]+)\|(?<message>.*)$") {
        $reasonCode = $Matches["code"]
        $providerError = $Matches["message"]
    }
    $reason = $providerError
    $nextAction = "Fix or remove the malformed provider config, then rerun runtime detection."
}
elseif ($dockerDesktopDetected) {
    $runtimeMode = "manual_docker_desktop"
    $runtimeVisible = $true
    $internalProofStatus = if ($dockerEngineReachable -and $composeAvailable) { "GO" } else { "NO_GO" }
    $reasonCode = if ($dockerEngineReachable -and $composeAvailable) { "manual_docker_desktop" } else { "manual_docker_desktop_unreachable" }
    $reason = if ($dockerEngineReachable -and $composeAvailable) {
        "Docker Desktop is installed and reachable, but it is a user-visible manual dependency."
    }
    else {
        "Docker Desktop is installed but the engine or compose is not reachable."
    }
    $nextAction = "Use only for developer/internal proof; package a managed runtime before agency install."
}
elseif ($dockerCliAvailable -and $dockerEngineReachable) {
    $reasonCode = "unmanaged_container_runtime"
    $reason = "A Docker-compatible engine is reachable, but it is not identified as an ImmoApp-managed hidden runtime."
    $nextAction = "Add an explicit managed runtime provider config after packaging the supported runtime."
    $runtimeCommand = ""
    $composeCommand = ""
    $composePrefix = @()
}

$result = [ordered]@{
    kind = "immoapp_hub_runtime_detection"
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    machine_name = $env:COMPUTERNAME
    runtime_dependency_mode = $runtimeMode
    docker_cli_available = [bool]$dockerCliAvailable
    docker_engine_reachable = [bool]$dockerEngineReachable
    docker_desktop_detected = [bool]$dockerDesktopDetected
    compose_available = [bool]$composeAvailable
    runtime_version = $runtimeVersion
    runtime_install_path = $runtimeInstallPath
    runtime_command = $runtimeCommand
    runtime_executable_path = $runtimeCommand
    compose_command = $composeCommand
    compose_arguments_prefix = @($composePrefix)
    runtime_is_user_visible = [bool]$runtimeVisible
    agency_install_status = $agencyStatus
    internal_proof_status = $internalProofStatus
    runtime_artifact_status = $runtimeArtifactStatus
    runtime_start_status = $runtimeStartStatus
    runtime_start_reason_code = $runtimeStartReasonCode
    runtime_start_evidence_path = $runtimeStartEvidencePath
    runtime_start_evidence_sha256 = $runtimeStartEvidenceSha256
    managed_runtime_command_path = $managedRuntimeCommandPath
    managed_compose_command_path = $managedComposeCommandPath
    front_door_health_status = $frontDoorHealthStatus
    front_door_live_probe = $frontDoorLiveProbe
    reason_code = $reasonCode
    reason = $reason
    recommended_next_action = $nextAction
    provider_config_path = $ProviderConfigPath
    canonical_provider_config_path = $canonicalProviderConfigPath
    provider_config_is_canonical = [bool]$providerConfigIsCanonical
    runtime_root_source = $runtimeRootSource
    runtime_root_is_canonical = [bool]$runtimeRootIsCanonical
    active_runtime_root = [System.IO.Path]::GetFullPath($paths.AppDataRoot)
    canonical_runtime_root = [System.IO.Path]::GetFullPath($canonicalPaths.AppDataRoot)
    provider_config_present = [bool]$providerPresent
    provider_config_valid = [bool]$providerValid
    provider_config_error = $providerError
    provider_validation_status = if ($providerValid) { "valid" } elseif ($providerPresent) { "invalid" } else { "missing" }
    provider = $providerSummary
    wsl_exe_present = [bool]$wslExePresent
    wsl_status_available = [bool]$wslStatusAvailable
    wsl_version_available = [bool]$wslVersionAvailable
    wsl_default_version = $wslDefaultVersion
    wsl_distributions = @($wslDistributions)
    wslconfig_path = $wslConfigPath
    wslconfig_present = [bool]$wslConfigPresent
    immoapp_wsl_policy_present = [bool]$wslPolicyPresent
    immoapp_wsl_policy_path = if ($wslPolicyPresent) { $wslPolicyPath } else { "" }
    immoapp_wsl_policy_sha256 = $wslPolicySha
    managed_wsl2_policy_status = $managedWslPolicyStatus
    managed_wsl2_policy_error = $wslPolicyError
    managed_wsl2_runtime_candidate_status = $managedWslRuntimeCandidateStatus
}

if ($OutputJson) {
    $outputDir = Split-Path -Parent $OutputJson
    if ($outputDir -and -not (Test-Path -LiteralPath $outputDir)) {
        New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    }
    Write-ImmoAppSafeJson -Path $OutputJson -Payload $result -ApprovedRoots @($paths.LogsRoot, $paths.ConfigRoot, $paths.TmpRoot) -Depth 12 | Out-Null
}

$result | ConvertTo-Json -Depth 12
