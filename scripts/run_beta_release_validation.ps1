param(
    [string]$FreshMachineEvidenceJson = "",
    [string]$LanEvidenceJson = "",
    [string]$HubInstallEvidenceJson = "",
    [string]$HubStatusEvidenceJson = "",
    [string]$HubIdentityEvidenceJson = "",
    [string]$HubNetworkBoundaryEvidenceJson = "",
    [string]$HubDiscoveryEvidenceJson = "",
    [string]$InstallerRoleEvidenceJson = "",
    [string]$WslPolicyEvidenceJson = "",
    [ValidateSet("desktop_only", "hub_only", "desktop_and_hub")]
    [string]$ValidationScope = "desktop_and_hub",
    [string]$SetupWizardFrontDoorE2eEvidenceJson = "",
    [string]$InstalledDesktopFrontDoorEvidenceJson = "",
    [string]$InstalledInventoryEvidenceJson = "",
    [string]$InstallLifecycleEvidenceJson = "",
    [string]$DesktopInstallerBuildSummaryJson = "",
    [string]$SelfSignedSignatureEvidenceJson = "",
    [string]$HubRuntimeReadinessSummaryJson = "",
    [string]$ManualProductProofEvidenceJson = "",
    [string]$ReleaseArtifactRoot = "C:\ProgramData\ImmoApp\release_artifacts\beta",
    [int]$WarnFreeMemoryGb = 6,
    [int]$MinCriticalFreeMemoryGb = 1,
    [int]$MinCommitHeadroomGb = 2,
    [switch]$AllowReplaceReleaseArtifacts,
    [switch]$CleanPreviousValidationArtifacts
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")
Set-ImmoAppSecurityEnv
Import-ImmoAppEnvFile
Set-ImmoAppHostRuntimeEndpoints

function Test-Truthy {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    return $Value.Trim().ToLowerInvariant() -in @("1", "true", "yes", "on")
}

function Get-FullPathString {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Test-PathUnderRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $rootFull = (Get-FullPathString -Path $Root).TrimEnd("\", "/")
    $pathFull = Get-FullPathString -Path $Path
    $isRoot = $pathFull.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase)
    $isUnderRoot = $pathFull.StartsWith($rootFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
    return ($isRoot -or $isUnderRoot)
}

function Assert-PathUnderRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-PathUnderRoot -Root $Root -Path $Path)) {
        throw "$Label path is outside expected root: $(Get-FullPathString -Path $Path)"
    }
}

function Assert-PathOutsideRepo {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (Test-PathUnderRoot -Root $RepoRoot -Path $Path) {
        throw "$Label must not be inside the Git source tree: $(Get-FullPathString -Path $Path)"
    }
}

function Format-CommandLine {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [string[]]$Arguments = @()
    )
    $parts = @($Command)
    foreach ($arg in $Arguments) {
        if ($arg -match '[\s"`'']') {
            $parts += ('"' + $arg.Replace('"', '\"') + '"')
        }
        else {
            $parts += $arg
        }
    }
    return ($parts -join " ")
}

function ConvertTo-WindowsProcessArgument {
    param([AllowNull()][string]$Argument)
    if ($null -eq $Argument) { return '""' }
    if ($Argument -notmatch '[\s"]') { return $Argument }

    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($char in $Argument.ToCharArray()) {
        if ($char -eq "\") {
            $backslashes += 1
            continue
        }
        if ($char -eq '"') {
            if ($backslashes -gt 0) { [void]$builder.Append("\" * ($backslashes * 2)) }
            [void]$builder.Append('\"')
            $backslashes = 0
            continue
        }
        if ($backslashes -gt 0) {
            [void]$builder.Append("\" * $backslashes)
            $backslashes = 0
        }
        [void]$builder.Append($char)
    }
    if ($backslashes -gt 0) { [void]$builder.Append("\" * ($backslashes * 2)) }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Join-WindowsProcessArguments {
    param([string[]]$Arguments = @())
    $parts = foreach ($arg in $Arguments) { ConvertTo-WindowsProcessArgument -Argument $arg }
    return ($parts -join " ")
}

function New-Phase {
    param([Parameter(Mandatory = $true)][string]$Name)
    return [ordered]@{
        name = $Name
        status = "NOT_RUN"
        blocker_reason = $null
        started_at = $null
        finished_at = $null
        commands = @()
        artifact_paths = [ordered]@{}
    }
}

function Start-Phase {
    param([Parameter(Mandatory = $true)]$Phase)
    $Phase.status = "RUNNING"
    $Phase.started_at = (Get-Date).ToUniversalTime().ToString("o")
}

function Complete-Phase {
    param(
        [Parameter(Mandatory = $true)]$Phase,
        [Parameter(Mandatory = $true)][ValidateSet("GO", "NO-GO", "N/A")]$Status,
        [string]$Reason = ""
    )
    $Phase.status = $Status
    $Phase.blocker_reason = if ($Reason) { $Reason } else { $null }
    $Phase.finished_at = (Get-Date).ToUniversalTime().ToString("o")
}

function Save-BetaSummary {
    param(
        [Parameter(Mandatory = $true)]$Summary,
        [Parameter(Mandatory = $true)][string]$JsonPath,
        [Parameter(Mandatory = $true)][string]$TextPath
    )
    $Summary.finished_at = (Get-Date).ToUniversalTime().ToString("o")
    $Summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $JsonPath -Encoding UTF8

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("ImmoApp beta release validation")
    $lines.Add("started_at: $($Summary.started_at)")
    $lines.Add("finished_at: $($Summary.finished_at)")
    $lines.Add("machine_name: $($Summary.machine_name)")
    $lines.Add("repo_root: $($Summary.repo_root)")
    $lines.Add("app_data_root: $($Summary.app_data_root)")
    $lines.Add("commit_sha: $($Summary.commit_sha)")
    $lines.Add("git_path: $($Summary.git_path)")
    $lines.Add("iscc_path: $($Summary.iscc_path)")
    $lines.Add("iscc_version_text: $($Summary.iscc_version_text)")
    $lines.Add("iscc_product_version: $($Summary.iscc_product_version)")
    $lines.Add("iscc_file_version: $($Summary.iscc_file_version)")
    $lines.Add("iscc_version_source: $($Summary.iscc_version_source)")
    $lines.Add("backend_health_status: $($Summary.backend_health_status)")
    $lines.Add("hub_runtime_profile: $($Summary.hub_runtime_profile)")
    $lines.Add("hub_runtime_source: $($Summary.hub_runtime_source)")
    $lines.Add("hub_runtime_profile_source: $($Summary.hub_runtime_profile_source)")
    $lines.Add("hub_runtime_detection_source: $($Summary.hub_runtime_detection_source)")
    $lines.Add("hub_runtime_reason: $($Summary.hub_runtime_reason)")
    $lines.Add("hub_runtime_capacity_fingerprint: $($Summary.hub_runtime_capacity_fingerprint)")
    $lines.Add("hub_runtime_stale_config_regenerated: $($Summary.hub_runtime_stale_config_regenerated)")
    $lines.Add("hub_runtime_cpu_count: $($Summary.hub_runtime_cpu_count)")
    $lines.Add("hub_runtime_total_ram_gb: $($Summary.hub_runtime_total_ram_gb)")
    $lines.Add("hub_runtime_effective_cpu_budget: $($Summary.hub_runtime_effective_cpu_budget)")
    $lines.Add("hub_runtime_effective_memory_gb: $($Summary.hub_runtime_effective_memory_gb)")
    $lines.Add("hub_runtime_worker_concurrency: $($Summary.hub_runtime_worker_concurrency)")
    $lines.Add("hub_runtime_import_concurrency: $($Summary.hub_runtime_import_concurrency)")
    $lines.Add("hub_runtime_match_concurrency: $($Summary.hub_runtime_match_concurrency)")
    $lines.Add("hub_runtime_db_pool_size: $($Summary.hub_runtime_db_pool_size)")
    $lines.Add("hub_runtime_pressure_state: $($Summary.hub_runtime_pressure_state)")
    $lines.Add("hub_runtime_pressure_reason: $($Summary.hub_runtime_pressure_reason)")
    $lines.Add("hub_runtime_warnings: $($Summary.hub_runtime_warnings -join '; ')")
    $lines.Add("artifact_root: $($Summary.artifact_root)")
    $lines.Add("internal_validation_artifact_path: $($Summary.internal_validation_artifact_path)")
    $lines.Add("stable_release_artifact_path: $($Summary.stable_release_artifact_path)")
    $lines.Add("stable_release_artifacts_manifest: $($Summary.stable_release_artifacts_manifest)")
    $lines.Add("installer_signed: $($Summary.installer_signed)")
    $lines.Add("installer_signature_type: $($Summary.installer_signature_type)")
    $lines.Add("local_internal_signed_status: $($Summary.local_internal_signed_status)")
    $lines.Add("overall_beta_status: $($Summary.overall_beta_status)")
    $lines.Add("local_internal_beta_status: $($Summary.local_internal_beta_status)")
    $lines.Add("public_beta_distribution_status: $($Summary.public_beta_distribution_status)")
    $lines.Add("fresh_machine_status: $($Summary.fresh_machine_status)")
    $lines.Add("hub_install_status: $($Summary.hub_install_status)")
    $lines.Add("hub_status_status: $($Summary.hub_status_status)")
    $lines.Add("lan_hub_workstation_status: $($Summary.lan_hub_workstation_status)")
    $lines.Add("installed_app_inventory_status: $($Summary.installed_app_inventory_status)")
    $lines.Add("install_lifecycle_status: $($Summary.install_lifecycle_status)")
    $lines.Add("setup_wizard_front_door_e2e_status: $($Summary.setup_wizard_front_door_e2e_status)")
    $lines.Add("installed_app_front_door_connectivity_status: $($Summary.installed_app_front_door_connectivity_status)")
    $lines.Add("desktop_installer_release_proof_status: $($Summary.desktop_installer_release_proof_status)")
    $lines.Add("runtime_artifact_status: $($Summary.runtime_artifact_status)")
    $lines.Add("image_bundle_status: $($Summary.image_bundle_status)")
    $lines.Add("rootfs_status: $($Summary.rootfs_status)")
    $lines.Add("distro_import_status: $($Summary.distro_import_status)")
    $lines.Add("provider_registration_status: $($Summary.provider_registration_status)")
    $lines.Add("runtime_start_status: $($Summary.runtime_start_status)")
    $lines.Add("front_door_health_status: $($Summary.front_door_health_status)")
    $lines.Add("public_beta_distribution: $($Summary.public_beta_distribution)")
    if ($Summary.docker_service_status) {
        $lines.Add("docker_service_status:")
        foreach ($serviceEntry in $Summary.docker_service_status.GetEnumerator()) {
            $service = $serviceEntry.Key
            $entry = $serviceEntry.Value
            $lines.Add(" - ${service}: state=$($entry.state), health=$($entry.health), status=$($entry.status)")
        }
    }
    $lines.Add("")
    foreach ($phase in $Summary.phases) {
        $reason = if ($phase.blocker_reason) { " - $($phase.blocker_reason)" } else { "" }
        $lines.Add("$($phase.name): $($phase.status)$reason")
    }
    Set-Content -LiteralPath $TextPath -Encoding UTF8 -Value $lines
}

function Resolve-ExecutablePath {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$EnvironmentVariable = "",
        [string[]]$Fallbacks = @()
    )
    $candidates = @()
    if ($EnvironmentVariable -and (Get-Item "Env:$EnvironmentVariable" -ErrorAction SilentlyContinue)) {
        $candidates += (Get-Item "Env:$EnvironmentVariable").Value
    }
    if ($EnvironmentVariable) {
        $userValue = [Environment]::GetEnvironmentVariable($EnvironmentVariable, "User")
        if ($userValue) { $candidates += $userValue }
        $machineValue = [Environment]::GetEnvironmentVariable($EnvironmentVariable, "Machine")
        if ($machineValue) { $candidates += $machineValue }
    }
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    $candidates += $Fallbacks
    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
        $resolved = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($resolved) { return $resolved.Source }
    }
    return $null
}

function Resolve-GitForValidation {
    $git = Resolve-ExecutablePath -Name "git" -EnvironmentVariable "GIT_EXE" -Fallbacks @(
        "C:\Program Files\Git\cmd\git.exe",
        "C:\Program Files\Git\bin\git.exe",
        "C:\Program Files (x86)\Git\cmd\git.exe"
    )
    if (-not $git) { throw "Git executable not found. Install Git or set GIT_EXE." }
    $version = (& $git --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $version -notmatch "^git version ") {
        throw "Git executable failed verification: $git"
    }
    return $git
}

function Resolve-IsccForValidation {
    $fallbacks = @()
    if ($env:LOCALAPPDATA) {
        $fallbacks += (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    }
    $fallbacks += (Join-Path $env:USERPROFILE "AppData\Local\Programs\Inno Setup 6\ISCC.exe")
    $fallbacks += @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    $iscc = Resolve-ExecutablePath -Name "iscc.exe" -EnvironmentVariable "INNO_SETUP_ISCC" -Fallbacks $fallbacks
    if (-not $iscc) {
        $iscc = Resolve-ExecutablePath -Name "iscc" -EnvironmentVariable "INNO_SETUP_ISCC" -Fallbacks $fallbacks
    }
    if (-not $iscc) { return $null }
    return (Get-InnoSetupCompilerInfo -Path $iscc)
}

function Get-VersionMajor {
    param([string]$VersionText)
    if ([string]::IsNullOrWhiteSpace($VersionText)) { return $null }
    if ($VersionText -match "^\s*(\d+)(\.|$)") { return [int]$Matches[1] }
    return $null
}

function Get-InnoSetupCompilerInfo {
    param([Parameter(Mandatory = $true)][string]$Path)
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = (& $Path "/?" *>&1 | Out-String)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0 -and $exitCode -ne 1) {
        throw "ISCC verification failed at $Path with exit code $exitCode."
    }
    if ($output -notmatch "Inno Setup\s+\d+.*Command-Line Compiler") {
        throw "ISCC executable did not identify as the Inno Setup command-line compiler: $Path"
    }

    $versionInfo = (Get-Item -LiteralPath $Path).VersionInfo
    $productVersion = [string]$versionInfo.ProductVersion
    $fileVersion = [string]$versionInfo.FileVersion
    $metadataVersion = ""
    $versionSource = "unreliable_metadata"
    foreach ($candidate in @($productVersion, $fileVersion)) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and $candidate -ne "0.0.0.0") {
            $metadataVersion = $candidate
            $versionSource = if ($candidate -eq $productVersion) { "product_version" } else { "file_version" }
            break
        }
    }

    $helpMajor = $null
    if ($output -match "Inno Setup\s+(\d+).*Command-Line Compiler") {
        $helpMajor = [int]$Matches[1]
    }
    $metadataMajor = Get-VersionMajor -VersionText $metadataVersion
    foreach ($major in @($metadataMajor, $helpMajor)) {
        if ($null -ne $major -and $major -ne 6) {
            throw "Inno Setup compiler must be stable major version 6 for beta packaging. Detected major version $major at $Path."
        }
    }
    if ($null -eq $metadataMajor -and $null -eq $helpMajor) {
        throw "Inno Setup compiler major version could not be detected at $Path."
    }

    return [ordered]@{
        executable = $Path
        version_text = $output.Trim().Split([Environment]::NewLine)[0]
        product_version = $productVersion
        file_version = $fileVersion
        version_source = $versionSource
    }
}

function Get-BetaRequiredDockerServices {
    return Get-ImmoAppHubRequiredComposeServices
}

function Convert-ComposeJsonLines {
    param([string[]]$Lines)
    $rows = @()
    foreach ($line in $Lines) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $rows += ($line | ConvertFrom-Json)
    }
    return @($rows)
}

function Test-BetaDockerStackHealth {
    param(
        [Parameter(Mandatory = $true)][object]$ComposeInvocation,
        [Parameter(Mandatory = $true)][string[]]$ComposeArgs
    )
    $raw = & $ComposeInvocation.Command @(@($ComposeInvocation.PrefixArguments) + $ComposeArgs + @("ps", "--format", "json")) 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Hub Compose ps --format json failed: $($raw -join "`n")"
    }
    $rows = Convert-ComposeJsonLines -Lines @($raw)
    $statusByService = [ordered]@{}
    $bad = New-Object System.Collections.Generic.List[string]
    foreach ($service in (Get-BetaRequiredDockerServices)) {
        $row = @($rows | Where-Object { $_.Service -eq $service }) | Select-Object -First 1
        if (-not $row) {
            $statusByService[$service] = [ordered]@{ state = "missing"; health = ""; status = "missing" }
            $bad.Add("$service=missing")
            continue
        }
        $state = ([string]$row.State).Trim().ToLowerInvariant()
        $health = ([string]$row.Health).Trim().ToLowerInvariant()
        $status = [string]$row.Status
        $statusByService[$service] = [ordered]@{
            state = $state
            health = $health
            status = $status
            container = [string]$row.Name
        }
        if ($state -ne "running") {
            $bad.Add("$service=$state/$health")
        }
        elseif (-not [string]::IsNullOrWhiteSpace($health) -and $health -ne "healthy") {
            $bad.Add("$service=$state/$health")
        }
    }
    return [ordered]@{
        service_status = $statusByService
        unhealthy_or_missing = @($bad)
    }
}

function Remove-BetaValidationPath {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Path
    )
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    Assert-PathUnderRoot -Root $RepoRoot -Path $resolved -Label "Cleanup target"
    Write-Host "Deleting previous validation artifact: $resolved"
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

function Clear-PreviousValidationArtifacts {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $tmpRoot = Join-Path $RepoRoot ".tmp"
    $validationRoot = Join-Path $tmpRoot "beta_release_validation"
    if (Test-Path -LiteralPath $validationRoot) {
        foreach ($child in Get-ChildItem -LiteralPath $validationRoot -Force) {
            Remove-BetaValidationPath -RepoRoot $RepoRoot -Path $child.FullName
        }
    }

    if (Test-Path -LiteralPath $tmpRoot) {
        Remove-BetaValidationPath -RepoRoot $RepoRoot -Path (Join-Path $tmpRoot "desktop_e2e_artifacts")
        foreach ($buildDir in Get-ChildItem -LiteralPath $tmpRoot -Directory -Force -Filter "desktop_installer_build_*" -ErrorAction SilentlyContinue) {
            Remove-BetaValidationPath -RepoRoot $RepoRoot -Path $buildDir.FullName
        }
    }
    foreach ($relative in @(".cache", ".hypothesis")) {
        Remove-BetaValidationPath -RepoRoot $RepoRoot -Path (Join-Path $RepoRoot $relative)
    }
    Get-ChildItem -LiteralPath $RepoRoot -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch "\\\.git\\" } |
        ForEach-Object { Remove-BetaValidationPath -RepoRoot $RepoRoot -Path $_.FullName }
}

function Get-GeneratedResidue {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$ValidationRoot
    )
    $items = New-Object System.Collections.Generic.List[string]
    $fixed = @(".cache", ".hypothesis", "scripts\benchmark_outputs", "scripts\perf_outputs", "scripts\profiling")
    foreach ($relative in $fixed) {
        $path = Join-Path $RepoRoot $relative
        if (Test-Path -LiteralPath $path) { $items.Add($relative) }
    }
    $pycache = Get-ChildItem -LiteralPath $RepoRoot -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch "\\\.git\\" } |
        Select-Object -ExpandProperty FullName
    foreach ($path in $pycache) { $items.Add($path) }
    $tmpRoot = Join-Path $RepoRoot ".tmp"
    if (Test-Path -LiteralPath $tmpRoot) {
        $validationParent = Join-Path $tmpRoot "beta_release_validation"
        foreach ($child in Get-ChildItem -LiteralPath $tmpRoot -Force) {
            if ($child.FullName.Equals($validationParent, [System.StringComparison]::OrdinalIgnoreCase)) {
                foreach ($validationChild in Get-ChildItem -LiteralPath $validationParent -Force -ErrorAction SilentlyContinue) {
                    if (-not $validationChild.FullName.Equals($ValidationRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                        $items.Add($validationChild.FullName)
                    }
                }
            }
            else {
                $items.Add($child.FullName)
            }
        }
    }
    return @($items)
}

function Invoke-LoggedCommand {
    param(
        [Parameter(Mandatory = $true)]$Phase,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$Command,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory = $true)][string]$LogDirectory,
        [switch]$ReturnOutput
    )
    $safeLabel = ($Label -replace '[^A-Za-z0-9_.-]', '_').Trim("_")
    $logPath = Join-Path $LogDirectory "$safeLabel.log"
    $record = [ordered]@{
        label = $Label
        command = (Format-CommandLine -Command $Command -Arguments $Arguments)
        exit_code = $null
        started_at = (Get-Date).ToUniversalTime().ToString("o")
        finished_at = $null
        log_path = $logPath
    }
    $Phase.commands += $record
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Stop"
        $stdoutPath = Join-Path $LogDirectory "$safeLabel.stdout.tmp"
        $stderrPath = Join-Path $LogDirectory "$safeLabel.stderr.tmp"
        # Start-Process -Wait with redirected output can hang after large child
        # processes exit on Windows. Invoke directly so PowerShell owns the
        # redirection and the wrapper can always continue to summary writing.
        #
        # Windows PowerShell can promote redirected native stderr to error
        # records when ErrorActionPreference is Stop. Docker Compose writes
        # progress/status to stderr, so keep the child process bounded by exit
        # code instead of treating ordinary native stderr as a wrapper failure.
        $nativeInvokeErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $global:LASTEXITCODE = 0
            & $Command @Arguments 1> $stdoutPath 2> $stderrPath
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $nativeInvokeErrorActionPreference
        }
        $stdout = if (Test-Path -LiteralPath $stdoutPath) { Get-Content -LiteralPath $stdoutPath -Raw } else { "" }
        $stderr = if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Raw } else { "" }
        $output = ($stdout, $stderr | Where-Object { -not [string]::IsNullOrEmpty($_) }) -join [Environment]::NewLine
        Set-Content -LiteralPath $logPath -Value $output -NoNewline -Encoding UTF8
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
        if (-not [string]::IsNullOrWhiteSpace($output)) {
            Write-Host ($output.TrimEnd())
        }
        $record.exit_code = $exitCode
        $record.finished_at = (Get-Date).ToUniversalTime().ToString("o")
        if ($exitCode -ne 0) {
            throw "$Label failed with exit code $exitCode"
        }
    }
    catch {
        $record.exit_code = if ($null -eq $record.exit_code) { -1 } else { $record.exit_code }
        $record.finished_at = (Get-Date).ToUniversalTime().ToString("o")
        Add-Content -LiteralPath $logPath -Value $_.Exception.Message
        throw
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($ReturnOutput) {
        return (Get-Content -LiteralPath $logPath -Raw)
    }
    return ""
}

function Get-JsonPropertyValue {
    param(
        [Parameter(Mandatory = $true)]$Data,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $property = $Data.PSObject.Properties[$Name]
    if ($null -ne $property) {
        return ,$property.Value
    }
    return $null
}

function Assert-RequiredJsonField {
    param(
        [Parameter(Mandatory = $true)]$Data,
        [Parameter(Mandatory = $true)][string]$Field,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $value = Get-JsonPropertyValue -Data $Data -Name $Field
    if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) {
        throw "$Label evidence missing required field: $Field"
    }
    return $value
}

function Convert-JsonBoolean {
    param([AllowNull()]$Value)
    if ($null -eq $Value) { return $false }
    if ($Value -is [bool]) { return [bool]$Value }
    $text = ([string]$Value).Trim().ToLowerInvariant()
    if ($text -in @("1", "true", "yes", "on")) { return $true }
    if ($text -in @("0", "false", "no", "off")) { return $false }
    return [bool]$Value
}

function Import-EvidenceJson {
    param(
        [string]$Path,
        [string]$Label
    )
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "$Label evidence file was not provided."
    }
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Label evidence file not found: $Path"
    }
    $data = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    return $data
}

function Assert-HubIdentityEvidence {
    param([Parameter(Mandatory = $true)][string]$Path)
    $data = Import-EvidenceJson -Path $Path -Label "Hub identity"
    if ([string]$data.kind -ne "immoapp_hub_identity_evidence") { throw "Hub identity evidence has wrong kind." }
    if ([int]$data.schema_version -ne 1) { throw "Hub identity evidence schema_version must be 1." }
    if ([string]$data.proof_result -ne "GO") { throw "Hub identity evidence proof_result must be GO." }
    Assert-RequiredJsonField -Data $data -Field "hub_display_name" -Label "Hub identity" | Out-Null
    if (Convert-JsonBoolean -Value $data.hostname_mutated) { throw "Hub identity evidence cannot mutate Windows hostname." }
    return $data
}

function Assert-HubFrontDoorEvidence {
    param([Parameter(Mandatory = $true)][string]$Path)
    $data = Import-EvidenceJson -Path $Path -Label "Hub front-door network boundary"
    if ([string]$data.kind -ne "immoapp_hub_network_boundary_evidence") { throw "Hub front-door evidence has wrong kind." }
    if ([int]$data.schema_version -ne 1) { throw "Hub front-door evidence schema_version must be 1." }
    if ([string]$data.approved_lan_facing_service -ne "caddy") { throw "Hub front-door evidence must approve only caddy as LAN-facing." }
    if ([string]$data.backend_internal_status -eq "lan_bound") { throw "Hub front-door evidence shows backend direct port exposed to LAN." }
    if (Convert-JsonBoolean -Value $data.caddy_admin_lan_exposed) { throw "Hub front-door evidence shows Caddy admin exposed to LAN." }
    if ([string]$data.proof_result -ne "GO") { throw "Hub front-door evidence proof_result must be GO." }
    return $data
}

function Assert-HubDiscoveryEvidence {
    param([Parameter(Mandatory = $true)][string]$Path)
    $data = Import-EvidenceJson -Path $Path -Label "Hub discovery"
    if ([string]$data.kind -ne "immoapp_hub_discovery_evidence") { throw "Hub discovery evidence has wrong kind." }
    if ([int]$data.schema_version -ne 1) { throw "Hub discovery evidence schema_version must be 1." }
    if (Convert-JsonBoolean -Value $data.secrets_advertised) { throw "Hub discovery evidence advertises secrets." }
    if (Convert-JsonBoolean -Value $data.internal_ports_advertised) { throw "Hub discovery evidence advertises internal ports." }
    Assert-RequiredJsonField -Data $data -Field "advertised_display_name" -Label "Hub discovery" | Out-Null
    Assert-RequiredJsonField -Data $data -Field "advertised_front_door_url" -Label "Hub discovery" | Out-Null
    if ([string]$data.proof_result -ne "GO") { throw "Hub discovery evidence proof_result must be GO from real LAN discovery proof." }
    return $data
}

function Assert-InstallerRoleEvidence {
    param([Parameter(Mandatory = $true)][string]$Path)

    $data = Import-EvidenceJson -Path $Path -Label "Installer role flow"
    if ([string]$data.kind -notin @("immoapp_hub_installer_foundation_evidence", "immoapp_hub_setup_result", "immoapp_hub_install_evidence")) {
        throw "Installer role evidence has wrong kind."
    }
    if ([string]$data.kind -eq "immoapp_hub_installer_foundation_evidence") {
        if (Convert-JsonBoolean -Value $data.validate_only) {
            throw "Installer role foundation evidence cannot be validate-only planning evidence."
        }
        foreach ($field in @("setup_run_id", "install_mode", "selected_install_desktop", "selected_install_hub", "foundation_applied_status", "hub_foundation_status", "proof_result", "hub_identity_status", "hub_state_manifest_status", "directories_status", "front_door_status", "firewall_status", "lan_access_enabled")) {
            Assert-RequiredJsonField -Data $data -Field $field -Label "Installer role foundation" | Out-Null
        }
        if ([string]::IsNullOrWhiteSpace([string]$data.setup_run_id)) { throw "Installer role foundation setup_run_id is required." }
        if ([string]$data.install_mode -notin @("hub_only", "desktop_and_hub")) { throw "Installer role foundation install_mode must be hub_only or desktop_and_hub." }
        if (-not (Convert-JsonBoolean -Value $data.selected_install_hub)) { throw "Installer role foundation evidence requires selected_install_hub=true." }
        if ([string]$data.foundation_applied_status -ne "GO") { throw "Installer role foundation_applied_status must be GO." }
        if ([string]$data.hub_foundation_status -ne "GO") { throw "Installer role hub_foundation_status must be GO." }
        if ([string]$data.proof_result -ne "GO") { throw "Installer role evidence proof_result must be GO." }
        if ([string]$data.hub_identity_status -ne "GO") { throw "Installer role hub_identity_status must be GO." }
        if ([string]$data.hub_state_manifest_status -ne "GO") { throw "Installer role hub_state_manifest_status must be GO." }
        Assert-RequiredJsonField -Data $data -Field "hub_state_manifest_path" -Label "Installer role foundation" | Out-Null
        if ([string]$data.directories_status -ne "GO") { throw "Installer role directories_status must be GO." }
        if ([string]$data.front_door_status -ne "GO") { throw "Installer role front_door_status must be GO." }
        if (Convert-JsonBoolean -Value $data.lan_access_enabled) {
            if ([string]$data.firewall_status -notin @("created", "already_present_valid")) {
                throw "Installer role LAN foundation requires created/already_present_valid Caddy firewall rule."
            }
            $firewall = $data.firewall
            if ($null -eq $firewall) { throw "Installer role LAN foundation requires firewall evidence." }
            if (-not (Convert-JsonBoolean -Value $firewall.verified)) { throw "Installer role firewall evidence must be verified." }
            if ([string]$firewall.direction -ne "Inbound") { throw "Installer role firewall direction must be Inbound." }
            if ([string]$firewall.action -ne "Allow") { throw "Installer role firewall action must be Allow." }
            if ([string]$firewall.protocol -ne "TCP") { throw "Installer role firewall protocol must be TCP." }
            $expectedFirewallPort = [string](Get-JsonPropertyValue -Data $data -Name "front_door_port")
            if ([string]::IsNullOrWhiteSpace($expectedFirewallPort)) { $expectedFirewallPort = "8000" }
            if ([string]$firewall.local_port -ne $expectedFirewallPort) { throw "Installer role firewall local_port must match Hub front-door port $expectedFirewallPort." }
            if ([string]$firewall.profile -ne "Private") { throw "Installer role firewall profile must be Private." }
        }
        else {
            if ([string]$data.firewall_status -ne "skipped_local_only") {
                throw "Installer role local-only foundation requires skipped_local_only firewall status."
            }
        }
        Assert-RequiredJsonField -Data $data -Field "hub_display_name" -Label "Installer role flow" | Out-Null
        Assert-RequiredJsonField -Data $data -Field "hub_front_door_url" -Label "Installer role flow" | Out-Null
        return $data
    }
    if ([string]$data.proof_result -ne "GO") {
        throw "Installer role evidence proof_result must be GO."
    }
    Assert-RequiredJsonField -Data $data -Field "hub_display_name" -Label "Installer role flow" | Out-Null
    Assert-RequiredJsonField -Data $data -Field "hub_front_door_url" -Label "Installer role flow" | Out-Null
    return $data
}

function Assert-WslPolicyEvidence {
    param([Parameter(Mandatory = $true)][string]$Path)

    $data = Import-EvidenceJson -Path $Path -Label "WSL2 runtime policy"
    if ([string]$data.kind -ne "immoapp_managed_wsl2_runtime_policy") { throw "WSL2 policy evidence has wrong kind." }
    if ([int]$data.schema_version -ne 1) { throw "WSL2 policy evidence has wrong schema_version." }
    if ([string]$data.policy_result -ne "GO") { throw "WSL2 policy evidence must be GO to record a candidate policy." }
    if ([string]$data.agency_install_status -eq "GO") { throw "WSL2 policy planning cannot satisfy agency install." }
    if ([string]$data.cap_is_ceiling_not_reservation -ne "True") { throw "WSL2 policy must record cap_is_ceiling_not_reservation=true." }
    if ([string]$data.global_wsl_config_scope -ne "True") { throw "WSL2 policy must record global_wsl_config_scope=true." }
    if ([double]$data.total_memory_gb -lt [double]$data.hub_minimum_ram_gb) { throw "WSL2 policy evidence is below the Hub minimum RAM." }
    foreach ($field in @("runtime_profile_source", "runtime_profile_status", "runtime_profile_path", "runtime_profile_sha256", "runtime_profile_error", "observed_hub_runtime_profile")) {
        if (-not ($data.PSObject.Properties.Name -contains $field)) {
            throw "WSL2 policy evidence missing runtime profile provenance field: $field"
        }
    }
    $profileSource = [string]$data.runtime_profile_source
    $profileStatus = [string]$data.runtime_profile_status
    $profilePath = [string]$data.runtime_profile_path
    $profileSha = [string]$data.runtime_profile_sha256
    $profileError = [string]$data.runtime_profile_error
    $observedProfile = [string]$data.observed_hub_runtime_profile
    $profileCaps = @{
        tiny = @{ MemoryGb = 3; Processors = 2 }
        small = @{ MemoryGb = 5; Processors = 4 }
        medium = @{ MemoryGb = 8; Processors = 6 }
        large = @{ MemoryGb = 12; Processors = 8 }
    }
    $plannedWslMemory = [double](Assert-RequiredJsonField -Data $data -Field "planned_wsl_memory_gb" -Label "WSL2 policy")
    $plannedWslProcessors = [int](Assert-RequiredJsonField -Data $data -Field "planned_wsl_processors" -Label "WSL2 policy")
    if ($plannedWslMemory -le 0) { throw "WSL2 planned_wsl_memory_gb must be positive." }
    if ($plannedWslProcessors -le 0) { throw "WSL2 planned_wsl_processors must be positive." }
    if ($profileError) { throw "WSL2 policy evidence has runtime profile error: $profileError" }
    if ($profileSource -ceq "machine_capacity") {
        if ($profileStatus -ne "missing") { throw "WSL2 machine-capacity policy must record runtime_profile_status=missing." }
        if ($profilePath -or $profileSha -or $observedProfile) { throw "WSL2 machine-capacity policy must not record runtime profile path/hash/profile." }
        $selectedHubRuntimeProfile = [string](Assert-RequiredJsonField -Data $data -Field "selected_hub_runtime_profile" -Label "WSL2 policy")
        if (-not (@("tiny", "small", "medium", "large") -ccontains $selectedHubRuntimeProfile)) {
            throw "WSL2 machine-capacity policy has invalid selected_hub_runtime_profile."
        }
        if ($plannedWslMemory -gt [double]$profileCaps[$selectedHubRuntimeProfile].MemoryGb) {
            throw "WSL2 machine-capacity planned_wsl_memory_gb exceeds selected_hub_runtime_profile cap for $selectedHubRuntimeProfile."
        }
        if ($plannedWslProcessors -gt [int]$profileCaps[$selectedHubRuntimeProfile].Processors) {
            throw "WSL2 machine-capacity planned_wsl_processors exceeds selected_hub_runtime_profile cap for $selectedHubRuntimeProfile."
        }
    }
    elseif (($profileSource -ceq "explicit_runtime_profile_json") -or ($profileSource -ceq "default_persisted_config")) {
        if ($profileStatus -ne "valid") { throw "WSL2 runtime profile evidence must record runtime_profile_status=valid." }
        if ([string]::IsNullOrWhiteSpace($profilePath)) { throw "WSL2 runtime profile evidence missing runtime_profile_path." }
        if ($profileSha -cnotmatch "^[0-9a-f]{64}$") { throw "WSL2 runtime profile evidence missing valid runtime_profile_sha256." }
        if (-not (@("tiny", "small", "medium", "large") -ccontains $observedProfile)) { throw "WSL2 runtime profile evidence has invalid observed_hub_runtime_profile." }
        $profileFullPath = [System.IO.Path]::GetFullPath($profilePath)
        if ($profileSource -ceq "default_persisted_config") {
            $expectedDefaultProfilePath = [System.IO.Path]::GetFullPath((Join-Path (Get-ImmoAppRuntimePaths).ConfigRoot "hub_runtime_profile.json"))
            if (-not $profileFullPath.Equals($expectedDefaultProfilePath, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "WSL2 default persisted runtime profile evidence must reference the active config root hub_runtime_profile.json."
            }
        }
        if (-not (Test-Path -LiteralPath $profilePath -PathType Leaf)) {
            throw "WSL2 runtime profile evidence references a missing local runtime_profile_path: $profilePath"
        }
        if (Get-Command -Name Test-ImmoAppPathHasReparsePoint -ErrorAction SilentlyContinue) {
            if (Test-ImmoAppPathHasReparsePoint -Path $profilePath) {
                throw "WSL2 runtime profile evidence path contains a reparse point, symlink, or junction: $profilePath"
            }
        }
        else {
            $current = (Get-Item -LiteralPath $profilePath -Force).FullName
            while (-not [string]::IsNullOrWhiteSpace($current)) {
                if (Test-Path -LiteralPath $current) {
                    $item = Get-Item -LiteralPath $current -Force
                    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                        throw "WSL2 runtime profile evidence path contains a reparse point, symlink, or junction: $profilePath"
                    }
                }
                $parent = Split-Path -Parent $current
                if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) { break }
                $current = $parent
            }
        }
        $actualProfileSha = (Get-FileHash -LiteralPath $profilePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualProfileSha -cne $profileSha) {
            throw "WSL2 runtime profile evidence SHA mismatch for runtime_profile_path: expected $profileSha but found $actualProfileSha"
        }
        try {
            $runtimeProfile = Get-Content -LiteralPath $profilePath -Raw | ConvertFrom-Json
        }
        catch {
            throw "WSL2 runtime profile JSON is invalid: $profilePath"
        }
        $actualProfile = [string](Get-JsonPropertyValue -Data $runtimeProfile -Name "selected_profile")
        if ([string]::IsNullOrWhiteSpace($actualProfile)) {
            $actualProfile = [string](Get-JsonPropertyValue -Data $runtimeProfile -Name "profile_name")
        }
        if ([string]::IsNullOrWhiteSpace($actualProfile)) {
            throw "WSL2 runtime profile JSON missing selected_profile/profile_name."
        }
        if (-not (@("tiny", "small", "medium", "large") -ccontains $actualProfile)) {
            throw "WSL2 runtime profile JSON has unsupported selected profile: $actualProfile"
        }
        if ($actualProfile -cne $observedProfile) {
            throw "WSL2 runtime profile evidence observed_hub_runtime_profile mismatch: expected $actualProfile from profile file but evidence recorded $observedProfile"
        }
        if ($plannedWslMemory -gt [double]$profileCaps[$actualProfile].MemoryGb) {
            throw "WSL2 planned_wsl_memory_gb exceeds observed runtime profile cap for $actualProfile."
        }
        if ($plannedWslProcessors -gt [int]$profileCaps[$actualProfile].Processors) {
            throw "WSL2 planned_wsl_processors exceeds observed runtime profile cap for $actualProfile."
        }
    }
    else {
        throw "WSL2 policy evidence has invalid runtime_profile_source: $profileSource"
    }
    return $data
}

function Resolve-WslPolicyPhaseEvidence {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("desktop_only", "hub_only", "desktop_and_hub")]
        [string]$ValidationScope,
        [string]$WslPolicyEvidenceJson = ""
    )

    if ($ValidationScope -eq "desktop_only") {
        return [ordered]@{
            status = "N/A"
            reason = "Desktop-only validation does not require Hub WSL policy evidence."
            evidence = $null
            planned_wsl_memory_gb = $null
            planned_wsl_processors = $null
            agency_install_status = ""
        }
    }
    if ([string]::IsNullOrWhiteSpace($WslPolicyEvidenceJson)) {
        return [ordered]@{
            status = "NO-GO"
            reason = "WSL2 policy evidence was not provided."
            evidence = $null
            planned_wsl_memory_gb = $null
            planned_wsl_processors = $null
            agency_install_status = "NO_GO"
        }
    }

    try {
        $evidence = Assert-WslPolicyEvidence -Path $WslPolicyEvidenceJson
        return [ordered]@{
            status = "GO"
            reason = ""
            evidence = $evidence
            planned_wsl_memory_gb = [int]$evidence.planned_wsl_memory_gb
            planned_wsl_processors = [int]$evidence.planned_wsl_processors
            agency_install_status = [string]$evidence.agency_install_status
        }
    }
    catch {
        return [ordered]@{
            status = "NO-GO"
            reason = $_.Exception.Message
            evidence = $null
            planned_wsl_memory_gb = $null
            planned_wsl_processors = $null
            agency_install_status = "NO_GO"
        }
    }
}

function Test-LocalhostUrl {
    param([string]$Url)
    if ([string]::IsNullOrWhiteSpace($Url)) { return $false }
    try {
        $uri = [Uri]$Url
    }
    catch {
        return $false
    }
    $hostName = $uri.Host.Trim().ToLowerInvariant()
    return $hostName -in @("localhost", "127.0.0.1", "::1")
}

function Test-CanonicalProviderConfigPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    $canonical = [System.IO.Path]::GetFullPath((Get-ImmoAppCanonicalHubRuntimeProviderConfigPath))
    $actual = [System.IO.Path]::GetFullPath($Path)
    return $actual.Equals($canonical, [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-LocalEvidencePath {
    param(
        [Parameter(Mandatory = $true)]$Data,
        [Parameter(Mandatory = $true)][string]$Field,
        [Parameter(Mandatory = $true)][string]$Label,
        [string]$HashField = ""
    )
    $value = [string](Assert-RequiredJsonField -Data $Data -Field $Field -Label $Label)
    if (-not (Test-Path -LiteralPath $value)) {
        throw "$Label local evidence path does not exist on this machine: $Field=$value."
    }
    if ($HashField) {
        $expectedHash = [string](Get-JsonPropertyValue -Data $Data -Name $HashField)
        if ([string]::IsNullOrWhiteSpace($expectedHash)) {
            throw "$Label local evidence missing hash field $HashField for $Field."
        }
        $actualHash = (Get-FileHash -LiteralPath $value -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash.ToLowerInvariant()) {
            throw "$Label local evidence hash mismatch for $Field. expected=$expectedHash actual=$actualHash"
        }
    }
}

function Assert-RemoteEvidenceHash {
    param(
        [Parameter(Mandatory = $true)]$Data,
        [Parameter(Mandatory = $true)][string]$Field,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $value = [string](Get-JsonPropertyValue -Data $Data -Name $Field)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "$Label remote evidence must include $Field."
    }
}

function Assert-LocalOrRemoteSupportBundleProof {
    param(
        [Parameter(Mandatory = $true)]$Data,
        [Parameter(Mandatory = $true)][string]$PathField,
        [Parameter(Mandatory = $true)][string]$HashField,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $remoteEvidence = Convert-JsonBoolean -Value (Get-JsonPropertyValue -Data $Data -Name "remote_evidence")
    if ($remoteEvidence) {
        Assert-RemoteEvidenceHash -Data $Data -Field $HashField -Label $Label
    }
    else {
        Assert-LocalEvidencePath -Data $Data -Field $PathField -HashField $HashField -Label $Label
    }
}

function Assert-EvidenceEnvelope {
    param(
        [Parameter(Mandatory = $true)]$Data,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $remoteEvidence = Convert-JsonBoolean -Value (Get-JsonPropertyValue -Data $Data -Name "remote_evidence")
    if ($remoteEvidence) {
        foreach ($field in @("evidence_file_sha256", "copied_from_machine", "copied_at_utc")) {
            Assert-RemoteEvidenceHash -Data $Data -Field $field -Label $Label
        }
    }
    return $remoteEvidence
}

function Assert-EmbeddedOrLocalReachabilityProof {
    param(
        [Parameter(Mandatory = $true)]$Data,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $remoteEvidence = Convert-JsonBoolean -Value (Get-JsonPropertyValue -Data $Data -Name "remote_evidence")
    if ($remoteEvidence) {
        $embedded = Get-JsonPropertyValue -Data $Data -Name "reachability_proof"
        if (-not $embedded) {
            throw "$Label remote evidence must embed reachability_proof generated by verify_lan_workstation_reachability.ps1."
        }
        return $embedded
    }
    $path = [string](Assert-RequiredJsonField -Data $Data -Field "reachability_proof_path" -Label $Label)
    if (-not (Test-Path -LiteralPath $path)) {
        throw "$Label reachability_proof_path does not exist on this machine: $path"
    }
    return (Get-Content -LiteralPath $path -Raw | ConvertFrom-Json)
}

function Assert-NoUnverifiedDesktopEndpointSource {
    param(
        [Parameter(Mandatory = $true)]$Data,
        [Parameter(Mandatory = $true)][string]$Label
    )
    foreach ($field in @("connection_source", "desktop_connection_source", "client_connection_source")) {
        $value = [string](Get-JsonPropertyValue -Data $Data -Name $field)
        if ($value -eq "local_dev_unverified") {
            throw "$Label evidence cannot use local_dev_unverified endpoint source for agency, fresh-machine, or LAN GO."
        }
    }
}

function Assert-InstalledAppInventoryEvidence {
    param(
        [string]$Path,
        [string]$CommitSha
    )
    $label = "Installed app inventory"
    $data = Import-EvidenceJson -Path $Path -Label $label
    if ([string](Assert-RequiredJsonField -Data $data -Field "kind" -Label $label) -ne "immoapp_installed_app_inventory") {
        throw "$label evidence has wrong kind."
    }
    foreach ($field in @("schema_version", "created_at_utc", "install_location", "installed_exe_path", "installed_exe_sha256", "uninstall_exe_path", "uninstall_registry_entry", "installer_sha256_verification", "installer_sha256_verified", "installer_sha256_claimed_only", "build_identity_required", "debug_missing_build_identity_allowed")) {
        Assert-RequiredJsonField -Data $data -Field $field -Label $label | Out-Null
    }
    if ($null -eq (Get-JsonPropertyValue -Data $data -Name "forbidden_path_matches")) {
        throw "$label evidence missing required field: forbidden_path_matches"
    }
    if ([int]$data.schema_version -lt 1) {
        throw "$label evidence schema_version must be a positive integer."
    }
    if (Convert-JsonBoolean -Value (Get-JsonPropertyValue -Data $data -Name "debug_missing_build_identity_allowed")) {
        throw "$label evidence used debug missing build identity allowance and cannot be GO."
    }
    $identity = Get-JsonPropertyValue -Data $data -Name "build_identity"
    $installerIdentity = Get-JsonPropertyValue -Data $data -Name "installer_build_identity"
    if (-not $identity -and -not $installerIdentity) {
        throw "$label evidence missing required installed build identity."
    }
    if ($CommitSha) {
        $identityMatches = ($identity -and [string]$identity.git_sha -eq $CommitSha)
        $installerIdentityMatches = ($installerIdentity -and [string]$installerIdentity.source_commit_sha -eq $CommitSha)
        if (-not ($identityMatches -or $installerIdentityMatches)) {
            throw "$label build identity does not match wrapper commit SHA."
        }
    }
    if (@($data.forbidden_path_matches).Count -gt 0) {
        throw "$label evidence contains forbidden packaged paths."
    }
    if ([string](Get-JsonPropertyValue -Data $data -Name "installer_sha256_verification") -ne "verified_from_installer_file") {
        throw "$label must verify installer SHA from the installer file."
    }
    if (-not (Convert-JsonBoolean -Value (Get-JsonPropertyValue -Data $data -Name "installer_sha256_verified"))) {
        throw "$label must set installer_sha256_verified=true."
    }
    if (Convert-JsonBoolean -Value (Get-JsonPropertyValue -Data $data -Name "installer_sha256_claimed_only")) {
        throw "$label cannot use claimed-only installer SHA evidence."
    }
    Assert-LocalEvidencePath -Data $data -Field "installed_exe_path" -Label $label
    Assert-LocalEvidencePath -Data $data -Field "uninstall_exe_path" -Label $label
    return $data
}

function Assert-InstallLifecycleEvidence {
    param(
        [string]$Path,
        [string]$CommitSha,
        [string]$InstallerSha256
    )
    $label = "Install lifecycle"
    $data = Import-EvidenceJson -Path $Path -Label $label
    if ([string](Assert-RequiredJsonField -Data $data -Field "kind" -Label $label) -ne "immoapp_install_lifecycle_evidence") {
        throw "$label evidence has wrong kind."
    }
    $remoteEvidence = Assert-EvidenceEnvelope -Data $data -Label $label
    foreach ($field in @("schema_version", "created_at_utc", "installer_path", "installer_sha256", "source_commit_sha", "backend_url_is_localhost", "phases", "lifecycle_status", "install_mechanics_status", "uninstall_status", "reinstall_status", "installed_app_front_door_connectivity_status", "desktop_installer_release_proof_status")) {
        Assert-RequiredJsonField -Data $data -Field $field -Label $label | Out-Null
    }
    if ($null -eq (Get-JsonPropertyValue -Data $data -Name "backend_url")) {
        throw "$label evidence missing required field: backend_url"
    }
    if ([int]$data.schema_version -ne 3) {
        throw "$label evidence schema_version must be 3; older lifecycle schemas prove mechanics only and are not accepted for release proof."
    }
    if ([string]$data.install_mechanics_status -ne "GO") {
        throw "$label evidence install_mechanics_status must be GO."
    }
    if ([string]$data.uninstall_status -ne "GO") {
        throw "$label evidence uninstall_status must be GO."
    }
    if ([string]$data.reinstall_status -ne "GO") {
        throw "$label evidence reinstall_status must be GO."
    }
    if ($CommitSha -and [string]$data.source_commit_sha -ne $CommitSha) {
        throw "$label evidence source_commit_sha does not match wrapper commit SHA."
    }
    if ($InstallerSha256 -and ([string]$data.installer_sha256).ToLowerInvariant() -ne $InstallerSha256.ToLowerInvariant()) {
        throw "$label evidence installer_sha256 does not match wrapper installer hash."
    }
    foreach ($phaseName in @("post_install", "post_uninstall", "post_reinstall")) {
        if (-not ($data.phases.PSObject.Properties.Name -contains $phaseName)) {
            throw "$label evidence missing required phase: $phaseName."
        }
    }
    $postInstall = $data.phases.post_install
    $postUninstall = $data.phases.post_uninstall
    $postReinstall = $data.phases.post_reinstall
    if (-not (Convert-JsonBoolean -Value $postInstall.uninstall_registry_present) -or -not (Convert-JsonBoolean -Value $postInstall.installed_exe_present)) {
        throw "$label post_install phase must prove registry and installed exe present."
    }
    if ((Convert-JsonBoolean -Value $postUninstall.uninstall_registry_present) -or (Convert-JsonBoolean -Value $postUninstall.installed_exe_present)) {
        throw "$label post_uninstall phase must prove registry and installed exe absent."
    }
    if (-not (Convert-JsonBoolean -Value $postReinstall.uninstall_registry_present) -or -not (Convert-JsonBoolean -Value $postReinstall.installed_exe_present)) {
        throw "$label post_reinstall phase must prove registry and installed exe present again."
    }
    if (-not $remoteEvidence) {
        Assert-LocalEvidencePath -Data $data -Field "installer_path" -Label $label
    }
    if ($remoteEvidence -or -not [string]::IsNullOrWhiteSpace([string](Get-JsonPropertyValue -Data $data -Name "support_bundle_path"))) {
        Assert-LocalOrRemoteSupportBundleProof -Data $data -PathField "support_bundle_path" -HashField "support_bundle_sha256" -Label $label
    }
    return $data
}

function Assert-SetupWizardFrontDoorE2eEvidence {
    param(
        [string]$Path,
        [string]$CommitSha
    )
    $label = "Setup-wizard front-door E2E"
    $data = Import-EvidenceJson -Path $Path -Label $label
    if ([string](Assert-RequiredJsonField -Data $data -Field "kind" -Label $label) -ne "immoapp_setup_wizard_front_door_e2e_evidence") {
        throw "$label evidence has wrong kind."
    }
    foreach ($field in @("schema_version", "source_commit_sha", "front_door_url", "backend_internal_url", "health_status", "identity_status", "front_door_header", "identity_kind", "identity_schema_version", "persisted_client_base_url", "connection_source", "proof_result")) {
        Assert-RequiredJsonField -Data $data -Field $field -Label $label | Out-Null
    }
    if ([int]$data.schema_version -ne 1) { throw "$label evidence schema_version must be 1." }
    if ($CommitSha -and [string]$data.source_commit_sha -ne $CommitSha) { throw "$label evidence source_commit_sha does not match installer commit." }
    if ([string]$data.proof_result -ne "GO") { throw "$label evidence proof_result must be GO." }
    if ([int]$data.health_status -ne 200 -or [int]$data.identity_status -ne 200) { throw "$label evidence requires health and identity HTTP 200." }
    if (([string]$data.front_door_header).ToLowerInvariant() -ne "caddy") { throw "$label evidence requires X-ImmoApp-Front-Door=caddy." }
    if ([string]$data.identity_kind -ne "immoapp_hub_front_door_identity" -or [int]$data.identity_schema_version -ne 1) { throw "$label evidence has invalid Hub front-door identity." }
    if ([string]$data.connection_source -eq "local_dev_unverified") { throw "$label evidence cannot use local_dev_unverified endpoint source." }
    if ([string]$data.persisted_client_base_url -ne [string]$data.front_door_url) { throw "$label evidence persisted client URL must match front-door URL." }
    if ([string]$data.persisted_client_base_url -eq [string]$data.backend_internal_url) { throw "$label evidence persisted client URL must not be direct backend URL." }
    return $data
}

function Assert-InstalledDesktopFrontDoorEvidence {
    param(
        [string]$Path,
        [string]$CommitSha,
        [string]$InstallerSha256
    )
    $label = "Installed desktop front-door connectivity"
    $data = Import-EvidenceJson -Path $Path -Label $label
    if ([string](Assert-RequiredJsonField -Data $data -Field "kind" -Label $label) -ne "immoapp_installed_desktop_front_door_evidence") {
        throw "$label evidence has wrong kind."
    }
    foreach ($field in @("schema_version", "created_at_utc", "machine_name", "source_commit_sha", "installer_sha256", "installed_exe_path", "installed_exe_sha256", "front_door_url", "health_status", "identity_status", "front_door_header", "identity_kind", "identity_schema_version", "persisted_config_status", "persisted_client_base_url", "connection_source", "proof_result")) {
        Assert-RequiredJsonField -Data $data -Field $field -Label $label | Out-Null
    }
    if ([int]$data.schema_version -ne 1) { throw "$label evidence schema_version must be 1." }
    if ($CommitSha -and [string]$data.source_commit_sha -ne $CommitSha) { throw "$label evidence source_commit_sha does not match wrapper commit SHA." }
    if ($InstallerSha256 -and ([string]$data.installer_sha256).ToLowerInvariant() -ne $InstallerSha256.ToLowerInvariant()) { throw "$label evidence installer_sha256 does not match wrapper installer hash." }
    if ([string]$data.proof_result -ne "GO") { throw "$label evidence proof_result must be GO." }
    if ([int]$data.health_status -ne 200 -or [int]$data.identity_status -ne 200) { throw "$label evidence requires health and identity HTTP 200." }
    if (([string]$data.front_door_header).ToLowerInvariant() -ne "caddy") { throw "$label evidence requires X-ImmoApp-Front-Door=caddy." }
    if ([string]$data.identity_kind -ne "immoapp_hub_front_door_identity" -or [int]$data.identity_schema_version -ne 1) { throw "$label evidence has invalid Hub front-door identity." }
    if ([string]$data.persisted_config_status -ne "present") { throw "$label evidence requires persisted client config." }
    if ([string]$data.connection_source -eq "local_dev_unverified") { throw "$label evidence cannot use local_dev_unverified endpoint source." }
    if ([string]$data.persisted_client_base_url -ne [string]$data.front_door_url) { throw "$label evidence persisted client URL must match front-door URL." }
    Assert-LocalEvidencePath -Data $data -Field "installed_exe_path" -Label $label
    return $data
}

function Assert-ManualProductProofEvidence {
    param([string]$Path)
    $label = "Manual product proof"
    $data = Import-EvidenceJson -Path $Path -Label $label
    if ([string](Assert-RequiredJsonField -Data $data -Field "kind" -Label $label) -ne "immoapp_manual_product_proof_evidence") {
        throw "$label evidence has wrong kind."
    }
    foreach ($field in @("schema_version", "fresh_machine_evidence_path", "fresh_machine_evidence_sha256", "support_bundle_path", "support_bundle_sha256", "owner_login_proof", "create_read_update_proof", "offer_photo_thumbnail_proof")) {
        Assert-RequiredJsonField -Data $data -Field $field -Label $label | Out-Null
    }
    foreach ($field in @("owner_login_proof", "create_read_update_proof", "offer_photo_thumbnail_proof")) {
        if (-not (Convert-JsonBoolean -Value (Get-JsonPropertyValue -Data $data -Name $field))) {
            throw "$label evidence has $field=false."
        }
    }
    Assert-LocalOrRemoteSupportBundleProof -Data $data -PathField "support_bundle_path" -HashField "support_bundle_sha256" -Label $label
    return $data
}

function Assert-FreshMachineEvidence {
    param(
        [string]$Path,
        [string]$CommitSha,
        [string]$InstallerSha256
    )
    $label = "Fresh-machine install"
    $data = Import-EvidenceJson -Path $Path -Label $label
    if ([string](Assert-RequiredJsonField -Data $data -Field "kind" -Label $label) -ne "immoapp_fresh_machine_install_evidence") {
        throw "$label evidence has wrong kind."
    }
    $remoteEvidence = Assert-EvidenceEnvelope -Data $data -Label $label
    foreach ($field in @(
        "schema_version",
        "created_at_utc",
        "machine_name",
        "windows_user",
        "installer_path",
        "installer_sha256",
        "source_commit_sha",
        "installed_shortcut_path",
        "installed_app_launch_path",
        "desktop_backend_url",
        "support_bundle_path",
        "support_bundle_sha256",
        "backend_health_status",
        "installed_inventory_status",
        "installed_inventory_path",
        "installed_inventory_sha256",
        "install_lifecycle_status",
        "install_lifecycle_evidence_path",
        "install_lifecycle_evidence_sha256"
    )) {
        Assert-RequiredJsonField -Data $data -Field $field -Label $label | Out-Null
    }
    if ([int]$data.schema_version -ne 2) {
        throw "$label evidence schema_version must be 2."
    }
    if ($CommitSha -and [string]$data.source_commit_sha -ne $CommitSha) {
        throw "$label evidence source_commit_sha does not match wrapper commit SHA."
    }
    if ($InstallerSha256 -and ([string]$data.installer_sha256).ToLowerInvariant() -ne $InstallerSha256.ToLowerInvariant()) {
        throw "$label evidence installer_sha256 does not match wrapper installer hash."
    }
    if ([string]$data.installed_inventory_status -ne "verified") {
        throw "$label evidence requires installed_inventory_status=verified for GO."
    }
    $lifecycleStatus = [string]$data.install_lifecycle_status
    $desktopLifecycleStatus = [string](Get-JsonPropertyValue -Data $data -Name "desktop_installer_release_proof_status")
    if ($desktopLifecycleStatus) {
        if ($desktopLifecycleStatus -ne "GO") {
            throw "$label evidence requires desktop_installer_release_proof_status=GO for GO."
        }
    }
    elseif ($lifecycleStatus -ne "GO") {
        throw "$label evidence requires install_lifecycle_status=GO for GO."
    }
    if ([int]$data.backend_health_status -ne 200) {
        throw "$label evidence backend_health_status must be 200."
    }
    Assert-NoUnverifiedDesktopEndpointSource -Data $data -Label $label
    if ($remoteEvidence) {
        Assert-RemoteEvidenceHash -Data $data -Field "support_bundle_sha256" -Label $label
        $embeddedInventory = Get-JsonPropertyValue -Data $data -Name "installed_inventory"
        $embeddedLifecycle = Get-JsonPropertyValue -Data $data -Name "install_lifecycle"
        if (-not $embeddedInventory -and -not (Get-JsonPropertyValue -Data $data -Name "installed_inventory_sha256")) {
            throw "$label remote evidence must embed installed_inventory or record installed_inventory_sha256."
        }
        if ($embeddedInventory -and [string]$embeddedInventory.kind -ne "immoapp_installed_app_inventory") {
            throw "$label remote embedded installed_inventory has wrong kind."
        }
        if (-not $embeddedLifecycle -and -not (Get-JsonPropertyValue -Data $data -Name "install_lifecycle_evidence_sha256")) {
            throw "$label remote evidence must embed install_lifecycle or record install_lifecycle_evidence_sha256."
        }
        if ($embeddedLifecycle -and [string]$embeddedLifecycle.kind -ne "immoapp_install_lifecycle_evidence") {
            throw "$label remote embedded install_lifecycle has wrong kind."
        }
    }
    else {
        foreach ($pathField in @("installer_path", "installed_shortcut_path", "installed_app_launch_path")) {
            Assert-LocalEvidencePath -Data $data -Field $pathField -Label $label
        }
        Assert-LocalOrRemoteSupportBundleProof -Data $data -PathField "support_bundle_path" -HashField "support_bundle_sha256" -Label $label
        Assert-LocalEvidencePath -Data $data -Field "installed_inventory_path" -HashField "installed_inventory_sha256" -Label $label
        Assert-LocalEvidencePath -Data $data -Field "install_lifecycle_evidence_path" -HashField "install_lifecycle_evidence_sha256" -Label $label
    }
    return $data
}

function Assert-LanEvidence {
    param(
        [string]$Path,
        [string]$CommitSha,
        [string]$InstallerSha256
    )
    $label = "LAN Hub/workstation"
    $data = Import-EvidenceJson -Path $Path -Label $label
    if ([string](Assert-RequiredJsonField -Data $data -Field "kind" -Label $label) -ne "immoapp_lan_hub_workstation_evidence") {
        throw "$label evidence has wrong kind."
    }
    $remoteEvidence = Assert-EvidenceEnvelope -Data $data -Label $label
    foreach ($field in @(
        "schema_version",
        "created_at_utc",
        "source_commit_sha",
        "installer_sha256",
        "hub_machine_name",
        "workstation_machine_or_profile_name",
        "hub_base_url",
        "desktop_backend_url",
        "backend_url_is_localhost",
        "reachability_proof_path",
        "reachability_proof",
        "health_status",
        "network_type",
        "windows_firewall_rule_status",
        "owner_login_proof",
        "workstation_create_read_update_proof",
        "workstation_offer_photo_thumbnail_proof",
        "workstation_support_bundle_path",
        "workstation_support_bundle_sha256",
        "hub_backup_restore_proof",
        "uninstall_reinstall_behavior"
    )) {
        Assert-RequiredJsonField -Data $data -Field $field -Label $label | Out-Null
    }
    if ([int]$data.schema_version -lt 2) {
        throw "$label evidence schema_version must be 2 or newer."
    }
    if ($CommitSha -and [string]$data.source_commit_sha -ne $CommitSha) {
        throw "$label evidence source_commit_sha does not match wrapper commit SHA."
    }
    if ($InstallerSha256 -and ([string]$data.installer_sha256).ToLowerInvariant() -ne $InstallerSha256.ToLowerInvariant()) {
        throw "$label evidence installer_sha256 does not match wrapper installer hash."
    }
    if ((Convert-JsonBoolean -Value $data.backend_url_is_localhost) -or (Test-LocalhostUrl -Url ([string]$data.desktop_backend_url))) {
        throw "$label evidence cannot use localhost desktop_backend_url for workstation proof."
    }
    if (Test-LocalhostUrl -Url ([string]$data.hub_base_url)) {
        throw "$label evidence cannot use localhost hub_base_url for workstation proof."
    }
    if ([int]$data.health_status -ne 200) {
        throw "$label evidence health_status must be 200."
    }
    Assert-NoUnverifiedDesktopEndpointSource -Data $data -Label $label
    foreach ($field in @("owner_login_proof", "workstation_create_read_update_proof", "workstation_offer_photo_thumbnail_proof", "hub_backup_restore_proof")) {
        if (-not (Convert-JsonBoolean -Value (Get-JsonPropertyValue -Data $data -Name $field))) {
            throw "$label evidence has $field=false."
        }
    }
    if ([string]$data.uninstall_reinstall_behavior -ne "confirmed") {
        throw "$label evidence requires uninstall_reinstall_behavior=confirmed for GO."
    }
    $reachabilityProof = Assert-EmbeddedOrLocalReachabilityProof -Data $data -Label $label
    if ([string]$reachabilityProof.kind -ne "immoapp_lan_workstation_reachability_proof") {
        throw "$label reachability proof was not generated by verify_lan_workstation_reachability.ps1."
    }
    if ([int]$reachabilityProof.health_status -ne 200) {
        throw "$label reachability proof health_status must be 200."
    }
    if ([string]$reachabilityProof.hub_base_url -ne [string]$data.hub_base_url) {
        throw "$label reachability proof hub_base_url does not match LAN evidence."
    }
    Assert-LocalOrRemoteSupportBundleProof -Data $data -PathField "workstation_support_bundle_path" -HashField "workstation_support_bundle_sha256" -Label $label
    return $data
}

function Assert-HubStatusEvidence {
    param(
        [string]$Path,
        [string]$CommitSha,
        [string]$InstallerSha256
    )
    $label = "Hub status"
    $data = Import-EvidenceJson -Path $Path -Label $label
    if ([string](Assert-RequiredJsonField -Data $data -Field "kind" -Label $label) -ne "immoapp_hub_status_evidence") {
        throw "$label evidence has wrong kind."
    }
    foreach ($field in @(
        "schema_version",
        "created_at_utc",
        "machine_name",
        "windows_user",
        "source_commit_sha",
        "installer_sha256",
        "installed_version",
        "installed_build_identity",
        "proof_result",
        "failure_reason",
        "hub_status",
        "runtime_state",
        "compose_state",
        "status_reason_code",
        "hub_base_url",
        "hub_address",
        "runtime_dependency_mode",
        "agency_install_status",
        "internal_proof_status",
        "runtime_user_visible",
        "runtime_detection",
        "runtime_provider_proof",
        "missing_services",
        "starting_services",
        "failing_services",
        "transport_security",
        "api_health",
        "database_health",
        "storage_photos_health",
        "worker_health",
        "backup_status",
        "runtime_profile",
        "data_path",
        "windows_firewall_rule_status"
    )) {
        Assert-RequiredJsonField -Data $data -Field $field -Label $label | Out-Null
    }
    if ($CommitSha -and [string]$data.source_commit_sha -ne $CommitSha) {
        throw "$label evidence source_commit_sha does not match wrapper commit SHA."
    }
    if ($InstallerSha256 -and ([string]$data.installer_sha256).ToLowerInvariant() -ne $InstallerSha256.ToLowerInvariant()) {
        throw "$label evidence installer_sha256 does not match wrapper installer hash."
    }
    if ([string]$data.proof_result -ne "GO") {
        throw "$label evidence proof_result must be GO."
    }
    if ([string]$data.hub_status -ne "Online") {
        throw "$label evidence requires hub_status=Online."
    }
    if ([string]$data.runtime_detection.kind -ne "immoapp_hub_runtime_detection") {
        throw "$label evidence must embed runtime_detection from detect_hub_runtime.ps1."
    }
    if (
        [string]$data.runtime_dependency_mode -eq "managed_wsl2_container_runtime_candidate" -or
        [string]$data.runtime_detection.runtime_dependency_mode -eq "managed_wsl2_container_runtime_candidate" -or
        [string]$data.runtime_dependency_mode -eq "managed_wsl2_container_runtime_artifact" -or
        [string]$data.runtime_detection.runtime_dependency_mode -eq "managed_wsl2_container_runtime_artifact"
    ) {
        $runtimeArtifactStatus = [string](Get-JsonPropertyValue -Data $data -Name "runtime_artifact_status")
        $runtimeStartStatus = [string](Get-JsonPropertyValue -Data $data -Name "runtime_start_status")
        if ($runtimeArtifactStatus -ne "GO" -or $runtimeStartStatus -ne "GO") {
            throw "$label evidence cannot use managed WSL2 candidate/artifact proof for managed runtime GO until runtime_artifact_status and runtime_start_status are both GO."
        }
    }
    if ([string]$data.runtime_detection.provider_validation_status -ne "valid" -or [string]$data.runtime_detection.reason_code -ne "managed_runtime_ready") {
        throw "$label evidence requires a production-ready managed runtime provider."
    }
    if ([string]$data.runtime_detection.runtime_dependency_mode -ne "managed_container_runtime") {
        throw "$label evidence requires runtime_dependency_mode=managed_container_runtime."
    }
    if (-not (Test-CanonicalProviderConfigPath -Path ([string]$data.runtime_detection.provider_config_path))) {
        throw "$label evidence requires the canonical Hub runtime provider config path."
    }
    if ([string]$data.runtime_provider_proof.proof_only -eq "True") {
        throw "$label evidence cannot use a proof-only runtime provider for agency GO."
    }
    if (Test-LocalhostUrl -Url ([string]$data.hub_base_url)) {
        throw "$label evidence requires a Hub IP/hostname URL, not localhost."
    }
    return $data
}

function Assert-HubInstallEvidence {
    param(
        [string]$Path,
        [string]$CommitSha,
        [string]$InstallerSha256
    )
    $label = "Hub install"
    $data = Import-EvidenceJson -Path $Path -Label $label
    if ([string](Assert-RequiredJsonField -Data $data -Field "kind" -Label $label) -ne "immoapp_hub_install_evidence") {
        throw "$label evidence has wrong kind."
    }
    foreach ($field in @(
        "schema_version",
        "created_at_utc",
        "machine_name",
        "windows_user",
        "source_commit_sha",
        "installer_sha256",
        "installed_version",
        "installed_build_identity",
        "proof_result",
        "failure_reason",
        "install_role",
        "hub_base_url",
        "backend_url_is_localhost",
        "data_path",
        "data_preserved_on_uninstall",
        "full_data_wipe_requires_separate_confirmation",
        "runtime_dependency_mode",
        "agency_install_status",
        "internal_proof_status",
        "runtime_user_visible",
        "hub_manager_script_path",
        "hub_manager_script_source",
        "desktop_exe_path",
        "desktop_exe_source",
        "runtime_detection",
        "runtime_provider_proof",
        "docker_compose_hidden_from_user",
        "transport_security"
    )) {
        Assert-RequiredJsonField -Data $data -Field $field -Label $label | Out-Null
    }
    if ($CommitSha -and [string]$data.source_commit_sha -ne $CommitSha) {
        throw "$label evidence source_commit_sha does not match wrapper commit SHA."
    }
    if ($InstallerSha256 -and ([string]$data.installer_sha256).ToLowerInvariant() -ne $InstallerSha256.ToLowerInvariant()) {
        throw "$label evidence installer_sha256 does not match wrapper installer hash."
    }
    if ([string]$data.proof_result -ne "GO") {
        throw "$label evidence proof_result must be GO."
    }
    if ([string]$data.runtime_dependency_mode -eq "manual_docker_desktop") {
        throw "$label evidence is NO-GO for real agency install while runtime_dependency_mode=manual_docker_desktop."
    }
    if ([string]$data.runtime_detection.kind -ne "immoapp_hub_runtime_detection") {
        throw "$label evidence must embed runtime_detection from detect_hub_runtime.ps1."
    }
    if (
        [string]$data.runtime_dependency_mode -eq "managed_wsl2_container_runtime_candidate" -or
        [string]$data.runtime_detection.runtime_dependency_mode -eq "managed_wsl2_container_runtime_candidate" -or
        [string]$data.runtime_dependency_mode -eq "managed_wsl2_container_runtime_artifact" -or
        [string]$data.runtime_detection.runtime_dependency_mode -eq "managed_wsl2_container_runtime_artifact"
    ) {
        $runtimeArtifactStatus = [string](Get-JsonPropertyValue -Data $data -Name "runtime_artifact_status")
        $runtimeStartStatus = [string](Get-JsonPropertyValue -Data $data -Name "runtime_start_status")
        if ($runtimeArtifactStatus -ne "GO" -or $runtimeStartStatus -ne "GO") {
            throw "$label evidence cannot use managed WSL2 candidate/artifact proof for managed runtime GO until runtime_artifact_status and runtime_start_status are both GO."
        }
    }
    if ([string]$data.agency_install_status -ne "GO") {
        throw "$label evidence requires agency_install_status=GO."
    }
    if ([string]$data.runtime_detection.provider_validation_status -ne "valid" -or [string]$data.runtime_detection.reason_code -ne "managed_runtime_ready") {
        throw "$label evidence requires a production-ready managed runtime provider."
    }
    if ([string]$data.runtime_detection.runtime_dependency_mode -ne "managed_container_runtime") {
        throw "$label evidence requires runtime_dependency_mode=managed_container_runtime."
    }
    if (-not (Test-CanonicalProviderConfigPath -Path ([string]$data.runtime_detection.provider_config_path))) {
        throw "$label evidence requires the canonical Hub runtime provider config path."
    }
    if ([string]$data.runtime_provider_proof.proof_only -eq "True") {
        throw "$label evidence cannot use a proof-only runtime provider for agency GO."
    }
    if (-not (Test-ImmoAppInstalledSource -Source ([string]$data.hub_manager_script_source))) {
        throw "$label evidence requires installed Hub Manager script path for agency GO."
    }
    $installMode = [string](Get-JsonPropertyValue -Data $data -Name "install_mode")
    if ([string]::IsNullOrWhiteSpace($installMode)) { $installMode = "desktop_and_hub" }
    if ($installMode -notin @("hub_only", "desktop_and_hub")) {
        throw "$label evidence install_mode must be hub_only or desktop_and_hub for Hub install proof."
    }
    if ($installMode -eq "desktop_and_hub" -and -not (Test-ImmoAppInstalledSource -Source ([string]$data.desktop_exe_source))) {
        throw "$label evidence requires installed Desktop executable path for agency GO."
    }
    if (Convert-JsonBoolean -Value $data.backend_url_is_localhost) {
        throw "$label evidence cannot use localhost hub_base_url for agency Hub proof."
    }
    return $data
}

function Assert-BundleInventoryEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][string]$CommitSha
    )
    $label = "Desktop installer package inventory"
    if (-not (Test-Path -LiteralPath $Path)) { throw "$label file not found: $Path" }
    $actualHash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "$label SHA-256 mismatch. expected=$ExpectedSha256 actual=$actualHash"
    }
    $data = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ([string]$data.kind -ne "immoapp_installer_package_inventory") { throw "$label has wrong kind." }
    if ([int]$data.schema_version -ne 1) { throw "$label schema_version must be 1." }
    if ([string]$data.source_commit_sha -ne $CommitSha) { throw "$label source_commit_sha does not match wrapper commit SHA." }
    if ([string]$data.installer_role_support -ne "desktop_and_or_hub") { throw "$label must support desktop_and_or_hub." }
    if (-not (Convert-JsonBoolean -Value $data.supports_desktop_only)) { throw "$label must support Desktop-only install mode." }
    if (-not (Convert-JsonBoolean -Value $data.supports_hub_only)) { throw "$label must support Hub-only install mode." }
    if (-not (Convert-JsonBoolean -Value $data.supports_desktop_and_hub)) { throw "$label must support Desktop + Hub install mode." }
    if ([string]$data.proof_result -ne "GO") { throw "$label proof_result must be GO." }
    if (@($data.forbidden_path_matches).Count -gt 0 -or @($data.detected_forbidden_paths).Count -gt 0) { throw "$label detected forbidden packaged paths." }
    if (@($data.missing_required_file_checks).Count -gt 0) { throw "$label is missing required installer role files." }
    foreach ($check in @($data.required_file_checks)) {
        if (-not (Convert-JsonBoolean -Value $check.present)) {
            throw "$label required file check failed: $($check.category) $($check.relative_path)"
        }
    }
    if ([int]$data.file_count -lt 1 -or [int]$data.total_file_count -lt 1) { throw "$label file_count must be positive." }
    return $data
}

function Get-InstallerSignatureStatus {
    param([string]$InstallerPath)
    if ([string]::IsNullOrWhiteSpace($InstallerPath) -or -not (Test-Path -LiteralPath $InstallerPath)) {
        return [ordered]@{
            installer_signed = "unknown"
            authenticode_status = "missing_installer"
        }
    }
    try {
        $signature = Get-AuthenticodeSignature -LiteralPath $InstallerPath
        return [ordered]@{
            installer_signed = if ($signature.Status -eq "Valid") { "true" } elseif ($signature.Status -eq "NotSigned") { "false" } else { "unknown" }
            authenticode_status = [string]$signature.Status
        }
    }
    catch {
        return [ordered]@{
            installer_signed = "unknown"
            authenticode_status = $_.Exception.Message
        }
    }
}

function Assert-SelfSignedInstallerSignatureEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceInstallerPath,
        [Parameter(Mandatory = $true)][string]$ExpectedUnsignedSha256,
        [Parameter(Mandatory = $true)][string]$ExpectedCommitSha
    )
    $label = "Self-signed installer signature evidence"
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$label file not found: $Path" }
    if (Test-ImmoAppPathHasReparsePoint -Path $Path) { throw "$label path contains a reparse point, symlink, or junction: $Path" }
    $data = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ([string]$data.kind -ne "immoapp_installer_self_signed_signature_evidence") { throw "$label has wrong kind." }
    if ([string]$data.proof_result -ne "GO") { throw "$label proof_result must be GO." }
    if ([string]$data.signature_type -ne "self_signed_local_internal") { throw "$label signature_type must be self_signed_local_internal." }
    if ([string]$data.local_internal_signed_status -ne "GO") { throw "$label local_internal_signed_status must be GO." }
    if ([string]$data.public_beta_distribution_status -notlike "NO-GO*") { throw "$label cannot claim public beta GO." }
    if ([string]$data.signer_subject -notlike "*Yacine Larbaoui*") { throw "$label signer_subject must include Yacine Larbaoui." }
    if ([string]$data.source_commit_sha -ne $ExpectedCommitSha) { throw "$label source_commit_sha does not match wrapper commit SHA." }
    if ((Get-FullPathString -Path ([string]$data.source_installer_path)) -ne (Get-FullPathString -Path $ExpectedSourceInstallerPath)) { throw "$label source_installer_path does not match selected installer." }
    if (([string]$data.unsigned_installer_sha256).ToLowerInvariant() -ne $ExpectedUnsignedSha256.ToLowerInvariant()) { throw "$label unsigned_installer_sha256 does not match selected installer SHA." }
    $signedInstallerPath = [string]$data.signed_installer_path
    if (-not (Test-Path -LiteralPath $signedInstallerPath -PathType Leaf)) { throw "$label signed_installer_path does not exist: $signedInstallerPath" }
    if (Test-ImmoAppPathHasReparsePoint -Path $signedInstallerPath) { throw "$label signed_installer_path contains a reparse point, symlink, or junction." }
    $signedSha = ([string]$data.signed_installer_sha256).ToLowerInvariant()
    if ($signedSha -cnotmatch "^[0-9a-f]{64}$") { throw "$label signed_installer_sha256 must be lowercase SHA-256." }
    $actualSignedSha = (Get-FileHash -LiteralPath $signedInstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSignedSha -ne $signedSha) { throw "$label signed_installer_sha256 does not match actual signed installer hash." }
    $thumbprint = [string]$data.certificate_thumbprint
    if ($thumbprint -notmatch "^[0-9A-Fa-f]{40,64}$") { throw "$label certificate_thumbprint is invalid." }
    $signature = Get-AuthenticodeSignature -LiteralPath $signedInstallerPath
    if ([string]$signature.Status -ne [string]$data.authenticode_status) { throw "$label authenticode_status does not match signed installer." }
    if ([string]$signature.SignerCertificate.Thumbprint -ne $thumbprint) { throw "$label certificate_thumbprint does not match signed installer." }
    if ([string]$signature.SignerCertificate.Subject -notlike "*Yacine Larbaoui*") { throw "$label signed installer subject must include Yacine Larbaoui." }
    return $data
}

function Assert-DesktopInstallerBuildSummary {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$CommitSha,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )
    $label = "Desktop installer build summary"
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$label file not found: $Path" }
    if (Test-ImmoAppPathHasReparsePoint -Path $Path) { throw "$label path contains a reparse point, symlink, or junction: $Path" }
    $data = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ([string]$data.kind -ne "immoapp_desktop_installer_build_summary") { throw "$label has wrong kind." }
    if ([string]$data.source_commit_sha -ne $CommitSha) { throw "$label source_commit_sha does not match wrapper commit SHA." }
    if (-not (Convert-JsonBoolean -Value $data.source_worktree_clean)) { throw "$label requires source_worktree_clean=true." }
    if ([string]$data.installer_role_support -ne "desktop_and_or_hub") { throw "$label must record desktop_and_or_hub role support." }
    if (-not (Convert-JsonBoolean -Value $data.supports_desktop_only)) { throw "$label must record Desktop-only support." }
    if (-not (Convert-JsonBoolean -Value $data.supports_hub_only)) { throw "$label must record Hub-only support." }
    if (-not (Convert-JsonBoolean -Value $data.supports_desktop_and_hub)) { throw "$label must record Desktop + Hub support." }
    $installerPath = [string]$data.installer_path
    $installerHash = ([string]$data.installer_sha256).ToLowerInvariant()
    if ($installerHash -notmatch "^[0-9a-f]{64}$") { throw "$label installer_sha256 must be a lowercase SHA-256." }
    if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) { throw "$label installer_path does not exist: $installerPath" }
    if (Test-ImmoAppPathHasReparsePoint -Path $installerPath) { throw "$label installer_path contains a reparse point, symlink, or junction: $installerPath" }
    Assert-PathOutsideRepo -RepoRoot $RepoRoot -Path $installerPath -Label "$label installer_path"
    $actualInstallerHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualInstallerHash -ne $installerHash) {
        throw "$label installer SHA-256 mismatch. expected=$installerHash actual=$actualInstallerHash"
    }
    $bundleInventoryPath = [string]$data.bundle_inventory_path
    $bundleInventoryHash = ([string]$data.bundle_inventory_sha256).ToLowerInvariant()
    if ($bundleInventoryHash -notmatch "^[0-9a-f]{64}$") { throw "$label bundle_inventory_sha256 must be a lowercase SHA-256." }
    if ([string]$data.package_inventory_path -ne $bundleInventoryPath) { throw "$label package_inventory_path must match bundle_inventory_path." }
    if (([string]$data.package_inventory_sha256).ToLowerInvariant() -ne $bundleInventoryHash) { throw "$label package_inventory_sha256 must match bundle_inventory_sha256." }
    Assert-PathOutsideRepo -RepoRoot $RepoRoot -Path $bundleInventoryPath -Label "$label bundle_inventory_path"
    $bundleInventory = Assert-BundleInventoryEvidence -Path $bundleInventoryPath -ExpectedSha256 $bundleInventoryHash -CommitSha $CommitSha
    $signatureStatus = Get-InstallerSignatureStatus -InstallerPath $installerPath
    return [ordered]@{
        summary = $data
        installer_path = $installerPath
        installer_sha256 = $installerHash
        installer_summary = (Resolve-Path -LiteralPath $Path).Path
        bundle_inventory_path = $bundleInventoryPath
        bundle_inventory_sha256 = $bundleInventoryHash
        bundle_inventory = $bundleInventory
        signature_status = $signatureStatus
    }
}

function New-BackupRestoreEvidenceSummary {
    param(
        [Parameter(Mandatory = $true)]$BackupPhase,
        [Parameter(Mandatory = $true)][string]$OutputPath
    )
    $backupBundlePath = [string]$BackupPhase.artifact_paths.backup_bundle
    $backupBundleSha = ""
    if (-not [string]::IsNullOrWhiteSpace($backupBundlePath) -and (Test-Path -LiteralPath $backupBundlePath)) {
        $backupBundleSha = (Get-FileHash -LiteralPath $backupBundlePath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $evidence = [ordered]@{
        kind = "immoapp_beta_release_backup_restore_evidence"
        schema_version = 1
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        status = $BackupPhase.status
        proof_result = $BackupPhase.status
        restore_database = $BackupPhase.artifact_paths.restore_database
        isolated_restore_bucket = $BackupPhase.artifact_paths.isolated_restore_bucket
        storage_objects_checked = $BackupPhase.artifact_paths.storage_objects_checked
        storage_objects_hash_verified = $BackupPhase.artifact_paths.storage_objects_hash_verified
        live_source_bucket_used_as_restore_target = $false
        backup_bundle_path = $backupBundlePath
        backup_bundle_sha256 = $backupBundleSha
        note = "DB dump and MinIO object mirror are intentionally not copied to the stable release artifact root."
    }
    foreach ($field in @(
        "source_commit_sha",
        "installer_sha256",
        "candidate_proof_run_id",
        "runtime_dependency_mode",
        "provider_config_sha256_at_backup",
        "provider_config_sha256_final",
        "provider_config_path",
        "hub_runtime_provider_mode",
        "backup_started_at_utc",
        "restore_verified_at_utc"
    )) {
        $value = Get-JsonPropertyValue -Data $BackupPhase.artifact_paths -Name $field
        if (-not [string]::IsNullOrWhiteSpace([string]$value)) {
            $evidence[$field] = $value
        }
    }
    $evidence | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    return $OutputPath
}

function Get-PhaseByName {
    param(
        [Parameter(Mandatory = $true)]$Summary,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $matches = @($Summary.phases | Where-Object { $_.name -eq $Name } | Select-Object -First 1)
    if ($matches.Count -eq 0) { return $null }
    return $matches[0]
}

function Set-BetaStatusFields {
    param([Parameter(Mandatory = $true)]$Summary)
    $backup = Get-PhaseByName -Summary $Summary -Name "backup_restore_proof"
    $gates = Get-PhaseByName -Summary $Summary -Name "e2e_repo_gates"
    $installer = Get-PhaseByName -Summary $Summary -Name "installer_build"
    $setupFrontDoorE2e = Get-PhaseByName -Summary $Summary -Name "setup_wizard_front_door_e2e"
    $installedInventory = Get-PhaseByName -Summary $Summary -Name "installed_app_inventory"
    $lifecycle = Get-PhaseByName -Summary $Summary -Name "install_lifecycle"
    $installedFrontDoor = Get-PhaseByName -Summary $Summary -Name "installed_app_front_door_connectivity"
    $desktopInstallerProof = Get-PhaseByName -Summary $Summary -Name "full_desktop_installer_release_proof"
    $fresh = Get-PhaseByName -Summary $Summary -Name "fresh_machine_install"
    $hubInstall = Get-PhaseByName -Summary $Summary -Name "hub_install"
    $hubStatus = Get-PhaseByName -Summary $Summary -Name "hub_status"
    $lan = Get-PhaseByName -Summary $Summary -Name "lan_hub_workstation"

    $Summary.installed_app_inventory_status = if ($installedInventory) { $installedInventory.status } else { "NOT_RUN" }
    $Summary.install_lifecycle_status = if ($lifecycle) { $lifecycle.status } else { "NOT_RUN" }
    $Summary.setup_wizard_front_door_e2e_status = if ($setupFrontDoorE2e) { $setupFrontDoorE2e.status } else { "NOT_RUN" }
    $Summary.installed_app_front_door_connectivity_status = if ($installedFrontDoor) { $installedFrontDoor.status } else { "NOT_RUN" }
    $Summary.desktop_installer_release_proof_status = if ($desktopInstallerProof) { $desktopInstallerProof.status } else { "NOT_RUN" }
    $Summary.fresh_machine_status = if ($fresh) { $fresh.status } else { "NOT_RUN" }
    $Summary.hub_install_status = if ($hubInstall) { $hubInstall.status } else { "NOT_RUN" }
    $Summary.hub_status_status = if ($hubStatus) { $hubStatus.status } else { "NOT_RUN" }
    $Summary.lan_hub_workstation_status = if ($lan) { $lan.status } else { "NOT_RUN" }
    $localRequiredGo = @(@($backup, $gates, $installer, $setupFrontDoorE2e) | Where-Object { -not $_ -or $_.status -ne "GO" })
    $Summary.local_internal_beta_status = if ($localRequiredGo.Count -eq 0) { "GO" } else { "NO-GO" }
    $completeRequiredGo = @(@($backup, $gates, $installer, $setupFrontDoorE2e, $installedInventory, $lifecycle, $installedFrontDoor, $desktopInstallerProof, $fresh, $hubInstall, $hubStatus, $lan) | Where-Object { -not $_ -or $_.status -ne "GO" })
    if ([string]$Summary.installer_signature_type -eq "self_signed_local_internal") {
        $Summary.public_beta_distribution_status = "NO-GO self-signed local/internal only"
    }
    elseif ([string]$Summary.installer_signed -ne "true") {
        $Summary.public_beta_distribution_status = "NO-GO unsigned installer"
    }
    elseif ($completeRequiredGo.Count -eq 0) {
        $Summary.public_beta_distribution_status = "GO"
    }
    else {
        $Summary.public_beta_distribution_status = "NO-GO missing complete beta evidence"
    }
    $Summary.overall_beta_status = if ($completeRequiredGo.Count -eq 0 -and [string]$Summary.installer_signed -eq "true" -and [string]$Summary.installer_signature_type -ne "self_signed_local_internal") { "GO" } else { "NO-GO" }
    $warnings = New-Object System.Collections.Generic.List[string]
    if ($fresh -and $fresh.status -ne "GO") { $warnings.Add("Fresh-machine install proof is NO-GO.") }
    if ($setupFrontDoorE2e -and $setupFrontDoorE2e.status -ne "GO") { $warnings.Add("Setup-wizard front-door E2E proof is NO-GO.") }
    if ($installedFrontDoor -and $installedFrontDoor.status -ne "GO") { $warnings.Add("Installed desktop front-door connectivity proof is NO-GO.") }
    if ($desktopInstallerProof -and $desktopInstallerProof.status -ne "GO") { $warnings.Add("Full desktop installer release proof is NO-GO.") }
    if ($hubInstall -and $hubInstall.status -ne "GO") { $warnings.Add("Hub install proof is NO-GO.") }
    if ($hubStatus -and $hubStatus.status -ne "GO") { $warnings.Add("Hub status proof is NO-GO.") }
    if ($lan -and $lan.status -ne "GO") { $warnings.Add("LAN Hub/workstation proof is NO-GO.") }
    if ([string]$Summary.installer_signature_type -eq "self_signed_local_internal") {
        $warnings.Add("Public beta distribution is NO-GO because the installer is self-signed for local/internal integrity only.")
    }
    elseif ([string]$Summary.installer_signed -ne "true") {
        $warnings.Add("Public beta distribution is NO-GO while the installer is unsigned.")
    }
    if (($fresh -and $fresh.status -ne "GO") -or ($hubInstall -and $hubInstall.status -ne "GO") -or ($hubStatus -and $hubStatus.status -ne "GO") -or ($lan -and $lan.status -ne "GO")) {
        $warnings.Add("NOT A COMPLETE BETA RELEASE. Installer artifact is available only for proof execution.")
    }
    $Summary.explicit_warnings = @($warnings.ToArray())
}

function Copy-StableReleaseArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$DestinationRoot,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Stable release artifact source does not exist: $Source"
    }
    $destination = Join-Path $DestinationRoot $Name
    if (Test-Path -LiteralPath $destination) {
        throw "Stable release artifact destination already exists: $destination"
    }
    Copy-Item -LiteralPath $Source -Destination $destination
    $hash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
    return [ordered]@{
        path = $destination
        sha256 = $hash
    }
}

function Publish-StableReleaseArtifacts {
    param(
        [Parameter(Mandatory = $true)]$Summary,
        [Parameter(Mandatory = $true)]$InstallerPhase,
        $SetupFrontDoorE2ePhase = $null,
        $InstalledInventoryPhase = $null,
        $InstallLifecyclePhase = $null,
        $InstalledFrontDoorPhase = $null,
        [Parameter(Mandatory = $true)]$BackupPhase,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$ValidationRoot,
        [Parameter(Mandatory = $true)][string]$JsonSummary,
        [Parameter(Mandatory = $true)][string]$TextSummary,
        [Parameter(Mandatory = $true)][string]$ReleaseRoot,
        [switch]$AllowReplace
    )
    if ($InstallerPhase.status -ne "GO") { return $null }
    $commitSha = [string]$Summary.commit_sha
    if ([string]::IsNullOrWhiteSpace($commitSha) -or $commitSha.Length -lt 12) {
        throw "Cannot publish stable release artifacts without a resolved commit SHA."
    }
    $releaseRootFull = Get-FullPathString -Path $ReleaseRoot
    Assert-PathOutsideRepo -RepoRoot $RepoRoot -Path $releaseRootFull -Label "Stable release artifact root"
    $commitRoot = Join-Path $releaseRootFull $commitSha.Substring(0, 12)
    if (Test-Path -LiteralPath $commitRoot) {
        if (-not $AllowReplace.IsPresent) {
            throw "Stable release artifact folder already exists: $commitRoot. Re-run with -AllowReplaceReleaseArtifacts to replace only this commit-specific folder."
        }
        Assert-PathUnderRoot -Root $releaseRootFull -Path $commitRoot -Label "Stable release artifact replacement"
        Write-Host "Deleting existing commit-specific release artifact folder: $commitRoot"
        Remove-Item -LiteralPath $commitRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $commitRoot | Out-Null
    $Summary.stable_release_artifact_path = $commitRoot
    $manifestPath = Join-Path $commitRoot "stable_artifacts_manifest.json"
    $Summary.stable_release_artifacts_manifest = $manifestPath
    Set-BetaStatusFields -Summary $Summary
    Save-BetaSummary -Summary $Summary -JsonPath $JsonSummary -TextPath $TextSummary

    $backupEvidencePath = Join-Path $ValidationRoot "backup_restore_evidence.summary.json"
    New-BackupRestoreEvidenceSummary -BackupPhase $BackupPhase -OutputPath $backupEvidencePath | Out-Null

    $installerPath = [string]$InstallerPhase.artifact_paths.installer_path
    $installerSummary = [string]$InstallerPhase.artifact_paths.installer_summary
    $bundleInventoryPath = [string]$InstallerPhase.artifact_paths.bundle_inventory_path
    $copied = [ordered]@{}
    $copied.installer = Copy-StableReleaseArtifact -Source $installerPath -DestinationRoot $commitRoot -Name (Split-Path -Leaf $installerPath)
    if ($installerSummary) {
        $copied.installer_summary = Copy-StableReleaseArtifact -Source $installerSummary -DestinationRoot $commitRoot -Name (Split-Path -Leaf $installerSummary)
    }
    if ($bundleInventoryPath) {
        $copied.bundle_inventory = Copy-StableReleaseArtifact -Source $bundleInventoryPath -DestinationRoot $commitRoot -Name (Split-Path -Leaf $bundleInventoryPath)
    }
    foreach ($entry in @(
            @{ key = "setup_wizard_front_door_e2e"; phase = $SetupFrontDoorE2ePhase; name = "setup_wizard_front_door_e2e_evidence.json" },
            @{ key = "installed_inventory"; phase = $InstalledInventoryPhase; name = "installed_inventory_evidence.json" },
            @{ key = "install_lifecycle"; phase = $InstallLifecyclePhase; name = "install_lifecycle_evidence.json" },
            @{ key = "installed_desktop_front_door"; phase = $InstalledFrontDoorPhase; name = "installed_desktop_front_door_evidence.json" }
        )) {
        $phase = $entry.phase
        if ($phase -and $phase.artifact_paths -and $phase.artifact_paths.Contains("evidence_json")) {
            $source = [string]$phase.artifact_paths.evidence_json
            if ($source -and (Test-Path -LiteralPath $source -PathType Leaf)) {
                $copied[$entry.key] = Copy-StableReleaseArtifact -Source $source -DestinationRoot $commitRoot -Name $entry.name
            }
        }
    }
    $copied.backup_restore_evidence_summary = Copy-StableReleaseArtifact -Source $backupEvidencePath -DestinationRoot $commitRoot -Name "backup_restore_evidence.summary.json"
    $copied.wrapper_summary_json = Copy-StableReleaseArtifact -Source $JsonSummary -DestinationRoot $commitRoot -Name "beta_release_validation.summary.json"
    $copied.wrapper_summary_text = Copy-StableReleaseArtifact -Source $TextSummary -DestinationRoot $commitRoot -Name "beta_release_validation.summary.txt"

    Set-BetaStatusFields -Summary $Summary
    $artifactManifest = [ordered]@{
        kind = "immoapp_stable_beta_release_artifacts"
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        overall_beta_status = $Summary.overall_beta_status
        local_internal_beta_status = $Summary.local_internal_beta_status
        public_beta_distribution_status = $Summary.public_beta_distribution_status
        fresh_machine_status = $Summary.fresh_machine_status
        lan_hub_workstation_status = $Summary.lan_hub_workstation_status
        installed_app_inventory_status = $Summary.installed_app_inventory_status
        install_lifecycle_status = $Summary.install_lifecycle_status
        setup_wizard_front_door_e2e_status = $Summary.setup_wizard_front_door_e2e_status
        installed_app_front_door_connectivity_status = $Summary.installed_app_front_door_connectivity_status
        desktop_installer_release_proof_status = $Summary.desktop_installer_release_proof_status
        installer_signed = $Summary.installer_signed
        authenticode_status = $InstallerPhase.artifact_paths.authenticode_status
        source_commit_sha = $commitSha
        installer_sha256 = $InstallerPhase.artifact_paths.installer_sha256
        bundle_inventory_path = if ($copied.Contains("bundle_inventory")) { $copied.bundle_inventory.path } else { $null }
        bundle_inventory_sha256 = if ($copied.Contains("bundle_inventory")) { $copied.bundle_inventory.sha256 } else { $null }
        bundle_inventory_file_count = $InstallerPhase.artifact_paths.bundle_inventory_file_count
        bundle_inventory_total_byte_size = $InstallerPhase.artifact_paths.bundle_inventory_total_byte_size
        installer_summary_path = if ($copied.Contains("installer_summary")) { $copied.installer_summary.path } else { $null }
        internal_validation_artifact_path = $ValidationRoot
        stable_release_artifact_path = $commitRoot
        copied_artifacts = $copied
        explicit_warnings = $Summary.explicit_warnings
        release_label = if ($Summary.fresh_machine_status -eq "GO" -and $Summary.lan_hub_workstation_status -eq "GO") { "complete_beta_release_candidate" } else { "NOT A COMPLETE BETA RELEASE. Installer artifact is available only for proof execution." }
        excluded_from_stable_artifacts = @(
            "secrets",
            "environment files",
            "database dumps",
            "MinIO object mirrors",
            "raw logs",
            "local support bundles"
        )
    }
    $artifactManifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    return $commitRoot
}

$repoRoot = (Get-ImmoAppRepoRoot).Path
$paths = Get-ImmoAppRuntimePaths
if ($CleanPreviousValidationArtifacts.IsPresent) {
    Clear-PreviousValidationArtifacts -RepoRoot $repoRoot
}
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss_ffff")
$validationRoot = Join-Path $repoRoot ".tmp\beta_release_validation\$timestamp"
if (Test-Path -LiteralPath $validationRoot) {
    throw "Validation artifact directory already exists: $validationRoot"
}
New-Item -ItemType Directory -Path $validationRoot | Out-Null
$logRoot = Join-Path $validationRoot "logs"
New-Item -ItemType Directory -Path $logRoot | Out-Null
$jsonSummary = Join-Path $validationRoot "summary.json"
$textSummary = Join-Path $validationRoot "summary.txt"

$summary = [ordered]@{
    kind = "immoapp_beta_release_validation_summary"
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    finished_at = $null
    machine_name = $env:COMPUTERNAME
    repo_root = $repoRoot
    app_data_root = $paths.AppDataRoot
    artifact_root = $validationRoot
    internal_validation_artifact_path = $validationRoot
    requested_release_artifact_root = $ReleaseArtifactRoot
    validation_scope = $ValidationScope
    stable_release_artifact_path = $null
    stable_release_artifacts_manifest = $null
    commit_sha = $null
    git_path = $null
    iscc_path = $null
    iscc_version_text = $null
    iscc_product_version = $null
    iscc_file_version = $null
    iscc_version_source = $null
    docker_service_status = $null
    backend_health_status = $null
    hub_runtime_profile = $null
    hub_runtime_source = $null
    hub_runtime_profile_source = $null
    hub_runtime_detection_source = $null
    hub_runtime_reason = $null
    hub_runtime_capacity_fingerprint = $null
    hub_runtime_stale_config_regenerated = $null
    hub_runtime_cpu_count = $null
    hub_runtime_total_ram_gb = $null
    hub_runtime_effective_cpu_budget = $null
    hub_runtime_effective_memory_gb = $null
    hub_runtime_worker_concurrency = $null
    hub_runtime_import_concurrency = $null
    hub_runtime_match_concurrency = $null
    hub_runtime_db_pool_size = $null
    hub_runtime_pressure_state = $null
    hub_runtime_pressure_reason = $null
    hub_runtime_warnings = @()
    wsl2_runtime_policy_status = "NOT_RUN"
    wsl2_runtime_policy_reason = ""
    wsl2_runtime_policy_path = ""
    wsl2_planned_memory_gb = $null
    wsl2_planned_processors = $null
    installer_signed = "unknown"
    installer_signature_type = "unknown"
    local_internal_signed_status = "NOT_RUN"
    self_signed_signature_evidence_path = ""
    signed_installer_path = ""
    signed_installer_sha256 = ""
    signer_subject = ""
    certificate_thumbprint = ""
    public_beta_distribution = "NO-GO without code signing"
    overall_beta_status = "NO-GO"
    local_internal_beta_status = "NO-GO"
    public_beta_distribution_status = "NO-GO without code signing"
    runtime_artifact_status = "NOT_RUN"
    image_bundle_status = "NOT_RUN"
    rootfs_status = "NOT_RUN"
    distro_import_status = "NOT_RUN"
    provider_registration_status = "NOT_RUN"
    runtime_start_status = "NOT_RUN"
    front_door_health_status = "NOT_RUN"
    hub_runtime_readiness_summary_path = ""
    fresh_machine_status = "NOT_RUN"
    lan_hub_workstation_status = "NOT_RUN"
    hub_install_status = "NOT_RUN"
    hub_status_status = "NOT_RUN"
    installed_app_inventory_status = "NOT_RUN"
    install_lifecycle_status = "NOT_RUN"
    setup_wizard_front_door_e2e_status = "NOT_RUN"
    installed_app_front_door_connectivity_status = "NOT_RUN"
    desktop_installer_release_proof_status = "NOT_RUN"
    explicit_warnings = @()
    phases = @()
}

$phasePreflight = New-Phase -Name "environment_and_repo_preflight"
$phaseBackup = New-Phase -Name "backup_restore_proof"
$phaseGates = New-Phase -Name "e2e_repo_gates"
$phaseInstaller = New-Phase -Name "installer_build"
$phaseSetupFrontDoorE2e = New-Phase -Name "setup_wizard_front_door_e2e"
$phaseInstalledInventory = New-Phase -Name "installed_app_inventory"
$phaseInstallLifecycle = New-Phase -Name "install_lifecycle"
$phaseInstalledFrontDoor = New-Phase -Name "installed_app_front_door_connectivity"
$phaseDesktopInstallerProof = New-Phase -Name "full_desktop_installer_release_proof"
$phaseFresh = New-Phase -Name "fresh_machine_install"
$phaseHubInstall = New-Phase -Name "hub_install"
$phaseHubStatus = New-Phase -Name "hub_status"
$phaseHubIdentity = New-Phase -Name "hub_identity"
$phaseHubFrontDoor = New-Phase -Name "caddy_front_door"
$phaseHubDiscovery = New-Phase -Name "discovery"
$phaseFirewallBoundary = New-Phase -Name "firewall_boundary"
$phaseInstallerRoleFlow = New-Phase -Name "installer_role_flow"
$phaseWslPolicy = New-Phase -Name "managed_wsl2_runtime_policy"
$phaseLan = New-Phase -Name "lan_hub_workstation"
$summary.phases = @($phasePreflight, $phaseBackup, $phaseGates, $phaseInstaller, $phaseSetupFrontDoorE2e, $phaseInstalledInventory, $phaseInstallLifecycle, $phaseInstalledFrontDoor, $phaseDesktopInstallerProof, $phaseFresh, $phaseHubInstall, $phaseHubStatus, $phaseHubIdentity, $phaseHubFrontDoor, $phaseHubDiscovery, $phaseFirewallBoundary, $phaseInstallerRoleFlow, $phaseWslPolicy, $phaseLan)

$exitCode = 0
$git = $null
$isccInfo = $null
$serverPython = $null

try {
    Start-Phase -Phase $phasePreflight
    try {
        $serverPython = Assert-ImmoAppVenvPython -Kind server -Purpose "beta release validation"
        $phasePreflight.artifact_paths.server_python = $serverPython
        $hubProfileText = Invoke-ImmoAppHubRuntimeProfile -Action "generate" -Format "json"
        $hubProfileJson = ($hubProfileText -join "`n")
        $hubProfileStart = $hubProfileJson.IndexOf("{")
        if ($hubProfileStart -lt 0) {
            throw "Hub runtime profile generation did not return JSON summary."
        }
        $hubProfile = $hubProfileJson.Substring($hubProfileStart) | ConvertFrom-Json
        $summary.hub_runtime_profile = [string]$hubProfile.selected_profile
        $summary.hub_runtime_source = [string]$hubProfile.source
        $summary.hub_runtime_profile_source = [string]$hubProfile.profile_source
        $summary.hub_runtime_detection_source = [string]$hubProfile.detection_source
        $summary.hub_runtime_reason = [string]$hubProfile.reason
        $summary.hub_runtime_capacity_fingerprint = [string]$hubProfile.capacity_fingerprint
        $summary.hub_runtime_stale_config_regenerated = [bool]$hubProfile.stale_config_regenerated
        $summary.hub_runtime_cpu_count = [int]$hubProfile.detected_cpu_count
        $summary.hub_runtime_total_ram_gb = [decimal]$hubProfile.detected_total_ram_gb
        $summary.hub_runtime_effective_cpu_budget = [int]$hubProfile.effective_cpu_budget
        $summary.hub_runtime_effective_memory_gb = [decimal]$hubProfile.effective_memory_gb
        $summary.hub_runtime_worker_concurrency = [int]$hubProfile.worker_concurrency
        $summary.hub_runtime_import_concurrency = [int]$hubProfile.import_concurrency
        $summary.hub_runtime_match_concurrency = [int]$hubProfile.match_concurrency
        $summary.hub_runtime_db_pool_size = [int]$hubProfile.db_pool_size
        if ($hubProfile.pressure) {
            $summary.hub_runtime_pressure_state = [string]$hubProfile.pressure.state
            $summary.hub_runtime_pressure_reason = [string]$hubProfile.pressure.reason
        }
        $summary.hub_runtime_warnings = @($hubProfile.warnings)
        $phasePreflight.artifact_paths.hub_runtime_profile = $summary.hub_runtime_profile
        Set-ImmoAppHubRuntimeProfileEnv

        if (Test-Truthy $env:IMMOAPP_PROD_CONFIG_STRICT) {
            throw "IMMOAPP_PROD_CONFIG_STRICT must not be enabled for local beta proof."
        }
        $djangoEnvValue = [string]$env:DJANGO_ENV
        $immoEnvValue = [string]$env:IMMOAPP_ENV
        $djangoEnvIsProdLike = (-not [string]::IsNullOrWhiteSpace($djangoEnvValue)) -and ($djangoEnvValue.Trim().ToLowerInvariant() -in @("production", "staging"))
        $immoEnvIsProdLike = (-not [string]::IsNullOrWhiteSpace($immoEnvValue)) -and ($immoEnvValue.Trim().ToLowerInvariant() -in @("production", "staging"))
        if ($djangoEnvIsProdLike -or $immoEnvIsProdLike) {
            throw "Production/staging environment flags are not allowed for local beta proof."
        }
        if (Test-Truthy $env:IMMOAPP_E2E_IDENTITY_BYPASS) {
            throw "Unsafe E2E backend identity bypass flag is enabled."
        }

        $git = Resolve-GitForValidation
        $summary.git_path = $git
        $summary.commit_sha = (& $git -C $repoRoot rev-parse HEAD).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $summary.commit_sha) {
            throw "Could not resolve commit SHA."
        }
        if (-not (Test-Path -LiteralPath (Join-Path $repoRoot ".gitattributes"))) {
            throw ".gitattributes is missing."
        }
        $dirty = & $git -C $repoRoot status --short
        if ($LASTEXITCODE -ne 0) { throw "git status --short failed." }
        if ($dirty) {
            throw "Git worktree is dirty: $($dirty -join '; ')"
        }
        $releaseRootFull = Get-FullPathString -Path $ReleaseArtifactRoot
        Assert-PathOutsideRepo -RepoRoot $repoRoot -Path $releaseRootFull -Label "Stable release artifact root"
        $releaseCommitRoot = Join-Path $releaseRootFull $summary.commit_sha.Substring(0, 12)
        $summary.stable_release_artifact_path = $releaseCommitRoot
        if ((Test-Path -LiteralPath $releaseCommitRoot) -and -not $AllowReplaceReleaseArtifacts.IsPresent) {
            throw "Stable release artifact folder already exists: $releaseCommitRoot. Re-run with -AllowReplaceReleaseArtifacts to replace only this commit-specific folder."
        }
        $residue = @(Get-GeneratedResidue -RepoRoot $repoRoot -ValidationRoot $validationRoot)
        if ($residue.Count -gt 0) {
            throw "Generated residue exists before beta validation: $($residue -join '; ')"
        }

        $isccInfo = Resolve-IsccForValidation
        if ($isccInfo) {
            $summary.iscc_path = $isccInfo.executable
            $summary.iscc_version_text = $isccInfo.version_text
            $summary.iscc_product_version = $isccInfo.product_version
            $summary.iscc_file_version = $isccInfo.file_version
            $summary.iscc_version_source = $isccInfo.version_source
        }
        if (-not $isccInfo) {
            $phasePreflight.artifact_paths.inno_setup_prerequisite = "NO-GO: Inno Setup compiler not found through PATH or INNO_SETUP_ISCC."
        }

        $runtimeDetectionPath = Join-Path $validationRoot "hub_runtime_detection.json"
        Invoke-LoggedCommand -Phase $phasePreflight -Label "detect hub runtime" -Command "powershell" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts\detect_hub_runtime.ps1", "-OutputJson", $runtimeDetectionPath) -LogDirectory $logRoot | Out-Null
        $runtimeDetection = Get-Content -LiteralPath $runtimeDetectionPath -Raw | ConvertFrom-Json
        $readinessPath = if ($HubRuntimeReadinessSummaryJson) { $HubRuntimeReadinessSummaryJson } else { Join-Path $validationRoot "hub_runtime_readiness_summary.json" }
        if (-not $HubRuntimeReadinessSummaryJson) {
            Invoke-LoggedCommand -Phase $phasePreflight -Label "collect hub runtime readiness summary" -Command "powershell" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts\collect_hub_runtime_readiness_summary.ps1", "-RuntimeDetectionJson", $runtimeDetectionPath, "-OutputJson", $readinessPath) -LogDirectory $logRoot | Out-Null
        }
        if (Test-Path -LiteralPath $readinessPath -PathType Leaf) {
            $runtimeReadiness = Get-Content -LiteralPath $readinessPath -Raw | ConvertFrom-Json
            if ([string]$runtimeReadiness.kind -ne "immoapp_hub_runtime_readiness_summary") {
                throw "Hub runtime readiness summary has wrong kind."
            }
            $summary.hub_runtime_readiness_summary_path = (Resolve-Path -LiteralPath $readinessPath).Path
            $summary.runtime_artifact_status = [string]$runtimeReadiness.runtime_artifact_status
            $summary.image_bundle_status = [string]$runtimeReadiness.image_bundle_status
            $summary.rootfs_status = [string]$runtimeReadiness.rootfs_status
            $summary.distro_import_status = [string]$runtimeReadiness.distro_import_status
            $summary.provider_registration_status = [string]$runtimeReadiness.provider_registration_status
            $summary.runtime_start_status = [string]$runtimeReadiness.runtime_start_status
            $summary.front_door_health_status = [string]$runtimeReadiness.front_door_health_status
            $phasePreflight.artifact_paths.hub_runtime_readiness_summary_json = $summary.hub_runtime_readiness_summary_path
        }
        $runtimeInvocation = Get-ImmoAppHubRuntimeEngineInvocation -RuntimeDetection $runtimeDetection
        $composeInvocation = Get-ImmoAppHubComposeInvocation -RuntimeDetection $runtimeDetection
        Invoke-LoggedCommand -Phase $phasePreflight -Label "hub runtime version" -Command $runtimeInvocation.Command -Arguments @("version") -LogDirectory $logRoot | Out-Null
        $summary.hub_runtime_detection = $runtimeDetection
        $phasePreflight.artifact_paths.hub_runtime_detection_json = $runtimeDetectionPath
        $phasePreflight.artifact_paths.runtime_dependency_mode = [string]$runtimeDetection.runtime_dependency_mode
        $phasePreflight.artifact_paths.agency_install_status = [string]$runtimeDetection.agency_install_status

        $composeArgs = (Get-ImmoAppComposeArgs -Names @("compose.yml")) + (Get-ImmoAppComposeProjectArgs)
        Invoke-LoggedCommand -Phase $phasePreflight -Label "hub compose ps" -Command $composeInvocation.Command -Arguments (@($composeInvocation.PrefixArguments) + $composeArgs + @("ps")) -LogDirectory $logRoot | Out-Null
        $stackHealth = Test-BetaDockerStackHealth -ComposeInvocation $composeInvocation -ComposeArgs $composeArgs
        $summary.docker_service_status = $stackHealth.service_status
        $phasePreflight.artifact_paths.docker_service_status = $stackHealth.service_status
        if ($stackHealth.unhealthy_or_missing.Count -gt 0) {
            $phasePreflight.artifact_paths.docker_stack_start_attempted = $true
            $phasePreflight.artifact_paths.docker_stack_initial_unhealthy_or_missing = @($stackHealth.unhealthy_or_missing)
            Invoke-LoggedCommand -Phase $phasePreflight -Label "start Hub app stack" -Command "powershell" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts\stack.ps1", "-Action", "up") -LogDirectory $logRoot | Out-Null
            Invoke-LoggedCommand -Phase $phasePreflight -Label "hub compose ps after stack start" -Command $composeInvocation.Command -Arguments (@($composeInvocation.PrefixArguments) + $composeArgs + @("ps")) -LogDirectory $logRoot | Out-Null
            $stackHealth = Test-BetaDockerStackHealth -ComposeInvocation $composeInvocation -ComposeArgs $composeArgs
            $summary.docker_service_status = $stackHealth.service_status
            $phasePreflight.artifact_paths.docker_service_status = $stackHealth.service_status
            if ($stackHealth.unhealthy_or_missing.Count -gt 0) {
                throw "Hub app stack is not healthy after start attempt: $($stackHealth.unhealthy_or_missing -join '; ')"
            }
        }
        try {
            $healthResponse = Invoke-WebRequest -Method Get -Uri "http://127.0.0.1:8000/api/v1/health/" -TimeoutSec 30 -UseBasicParsing
        }
        catch {
            throw "Backend health endpoint did not return 200: $($_.Exception.Message)"
        }
        $summary.backend_health_status = [int]$healthResponse.StatusCode
        $phasePreflight.artifact_paths.backend_health_status = [int]$healthResponse.StatusCode
        if ([int]$healthResponse.StatusCode -ne 200) {
            throw "Backend health endpoint returned $([int]$healthResponse.StatusCode), expected 200."
        }
        Complete-Phase -Phase $phasePreflight -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phasePreflight -Status "NO-GO" -Reason $_.Exception.Message
        throw
    }

    Start-Phase -Phase $phaseBackup
    try {
        $backupRoot = Join-Path $validationRoot "backup"
        New-Item -ItemType Directory -Path $backupRoot | Out-Null
        $integrityOutput = Invoke-LoggedCommand -Phase $phaseBackup -Label "verify release backup integrity" -Command $serverPython -Arguments @("scripts\verify_release_backup_integrity.py") -LogDirectory $logRoot -ReturnOutput
        if ($integrityOutput -notmatch "release_backup_integrity=ok") {
            throw "Release backup integrity did not report ok."
        }
        Invoke-LoggedCommand -Phase $phaseBackup -Label "backup release bundle" -Command "powershell" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts\backup_release_bundle.ps1", "-OutputRoot", $backupRoot, "-BundleName", "release_validation") -LogDirectory $logRoot | Out-Null
        $bundlePath = Join-Path $backupRoot "release_validation.zip"
        if (-not (Test-Path -LiteralPath $bundlePath)) {
            throw "Backup bundle not found after backup command: $bundlePath"
        }
        $restoreOutput = Invoke-LoggedCommand -Phase $phaseBackup -Label "restore release bundle" -Command "powershell" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts\restore_release_bundle.ps1", "-BundlePath", $bundlePath) -LogDirectory $logRoot -ReturnOutput
        if ($restoreOutput -notmatch "storage_objects_checked=(\d+)") {
            throw "Restore verification did not report storage_objects_checked."
        }
        $checked = [int]$Matches[1]
        if ($restoreOutput -notmatch "storage_objects_hash_verified=(\d+)") {
            throw "Restore verification did not report storage_objects_hash_verified."
        }
        $hashVerified = [int]$Matches[1]
        if ($hashVerified -lt 1 -or $hashVerified -ne $checked) {
            throw "Restore object hash verification count is invalid: checked=$checked verified=$hashVerified."
        }
        if ($restoreOutput -notmatch "Release restore database: ([^\r\n]+)") {
            throw "Restore database name was not printed."
        }
        $restoreDb = $Matches[1].Trim()
        if ($restoreOutput -notmatch "Release restore object bucket: (immoapp-restore-drill-[0-9]{14}-[0-9a-f]{8})") {
            throw "Isolated restore bucket was not printed."
        }
        $restoreBucket = $Matches[1].Trim()
        if ($restoreOutput -notmatch "Source bucket '([^']+)' was not used as the restore target.") {
            throw "Restore output did not confirm source bucket isolation."
        }
        $sourceBucket = $Matches[1]
        if ($sourceBucket -eq $restoreBucket) {
            throw "Live source bucket was used as restore target."
        }
        $phaseBackup.artifact_paths.backup_bundle = $bundlePath
        $phaseBackup.artifact_paths.restore_database = $restoreDb
        $phaseBackup.artifact_paths.isolated_restore_bucket = $restoreBucket
        $phaseBackup.artifact_paths.storage_objects_checked = $checked
        $phaseBackup.artifact_paths.storage_objects_hash_verified = $hashVerified
        Complete-Phase -Phase $phaseBackup -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseBackup -Status "NO-GO" -Reason $_.Exception.Message
        throw
    }

    Start-Phase -Phase $phaseGates
    try {
        Invoke-LoggedCommand -Phase $phaseGates -Label "run e2e release validation" -Command "powershell" -Arguments @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts\run_e2e_release_validation.ps1",
            "-WarnFreeMemoryGb",
            "$WarnFreeMemoryGb",
            "-MinCriticalFreeMemoryGb",
            "$MinCriticalFreeMemoryGb",
            "-MinCommitHeadroomGb",
            "$MinCommitHeadroomGb"
        ) -LogDirectory $logRoot | Out-Null
        Invoke-LoggedCommand -Phase $phaseGates -Label "checks pr" -Command "powershell" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "checks.ps1", "-Stage", "pr") -LogDirectory $logRoot | Out-Null
        Invoke-LoggedCommand -Phase $phaseGates -Label "checks full" -Command "powershell" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "checks.ps1", "-Stage", "full") -LogDirectory $logRoot | Out-Null
        $phaseGates.artifact_paths.desktop_e2e_artifacts = (Join-Path $repoRoot ".tmp\desktop_e2e_artifacts")
        Complete-Phase -Phase $phaseGates -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseGates -Status "NO-GO" -Reason $_.Exception.Message
        throw
    }

    Start-Phase -Phase $phaseInstaller
    try {
        if ($DesktopInstallerBuildSummaryJson) {
            $existingBuild = Assert-DesktopInstallerBuildSummary -Path $DesktopInstallerBuildSummaryJson -CommitSha ([string]$summary.commit_sha) -RepoRoot $repoRoot
            $installerPath = [string]$existingBuild.installer_path
            $installerHash = [string]$existingBuild.installer_sha256
            $installerSummary = [string]$existingBuild.installer_summary
            $bundleInventoryPath = [string]$existingBuild.bundle_inventory_path
            $bundleInventoryHash = [string]$existingBuild.bundle_inventory_sha256
            $bundleInventory = $existingBuild.bundle_inventory
            $signatureStatus = $existingBuild.signature_status
        }
        else {
            if (-not $git) { throw "Git is unavailable for installer build proof." }
            if (-not $isccInfo) { throw "Inno Setup compiler not found through PATH or INNO_SETUP_ISCC." }
            $installerOutputRoot = Join-Path $validationRoot "installer"
            $installerOutput = Invoke-LoggedCommand -Phase $phaseInstaller -Label "build desktop installer" -Command "powershell" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts\build_desktop_installer.ps1", "-GitExe", $git, "-InnoSetupCompiler", $isccInfo.executable, "-OutputRoot", $installerOutputRoot) -LogDirectory $logRoot -ReturnOutput
            if ($installerOutput -notmatch "Desktop installer created: ([^\r\n]+)") {
                throw "Installer build output did not include installer path."
            }
            $installerPath = $Matches[1].Trim()
            if ($installerOutput -notmatch "Desktop installer SHA-256: ([0-9a-f]{64})") {
                throw "Installer build output did not include installer SHA-256."
            }
            $installerHash = $Matches[1].Trim()
            if ($installerOutput -notmatch "Build summary: ([^\r\n]+)") {
                throw "Installer build output did not include build summary path."
            }
            $installerSummary = $Matches[1].Trim()
            if ($installerOutput -notmatch "Desktop bundle inventory created: ([^\r\n]+)") {
                throw "Installer build output did not include desktop bundle inventory path."
            }
            $bundleInventoryPath = $Matches[1].Trim()
            if ($installerOutput -notmatch "Desktop bundle inventory SHA-256: ([0-9a-f]{64})") {
                throw "Installer build output did not include desktop bundle inventory SHA-256."
            }
            $bundleInventoryHash = $Matches[1].Trim()
            $bundleInventory = Assert-BundleInventoryEvidence -Path $bundleInventoryPath -ExpectedSha256 $bundleInventoryHash -CommitSha ([string]$summary.commit_sha)
            $signatureStatus = Get-InstallerSignatureStatus -InstallerPath $installerPath
        }
        $summary.installer_signed = $signatureStatus.installer_signed
        $summary.installer_signature_type = if ([string]$signatureStatus.installer_signed -eq "true") { "trusted_or_machine_valid_authenticode" } elseif ([string]$signatureStatus.installer_signed -eq "false") { "unsigned" } else { "unknown" }
        $phaseInstaller.artifact_paths.authenticode_status = $signatureStatus.authenticode_status
        $phaseInstaller.artifact_paths.installer_path = $installerPath
        $phaseInstaller.artifact_paths.installer_sha256 = $installerHash
        $phaseInstaller.artifact_paths.installer_summary = $installerSummary
        $phaseInstaller.artifact_paths.bundle_inventory_path = $bundleInventoryPath
        $phaseInstaller.artifact_paths.bundle_inventory_sha256 = $bundleInventoryHash
        $phaseInstaller.artifact_paths.bundle_inventory_file_count = [int]$bundleInventory.total_file_count
        $phaseInstaller.artifact_paths.bundle_inventory_total_byte_size = [int64]$bundleInventory.total_byte_size
        if ($SelfSignedSignatureEvidenceJson) {
            $selfSignedEvidence = Assert-SelfSignedInstallerSignatureEvidence -Path $SelfSignedSignatureEvidenceJson -ExpectedSourceInstallerPath $installerPath -ExpectedUnsignedSha256 $installerHash -ExpectedCommitSha ([string]$summary.commit_sha)
            $summary.installer_signed = "self_signed_local_internal"
            $summary.installer_signature_type = "self_signed_local_internal"
            $summary.local_internal_signed_status = "GO"
            $summary.self_signed_signature_evidence_path = (Resolve-Path -LiteralPath $SelfSignedSignatureEvidenceJson).Path
            $summary.signed_installer_path = [string]$selfSignedEvidence.signed_installer_path
            $summary.signed_installer_sha256 = [string]$selfSignedEvidence.signed_installer_sha256
            $summary.signer_subject = [string]$selfSignedEvidence.signer_subject
            $summary.certificate_thumbprint = [string]$selfSignedEvidence.certificate_thumbprint
            $phaseInstaller.artifact_paths.self_signed_signature_evidence = $summary.self_signed_signature_evidence_path
            $phaseInstaller.artifact_paths.signed_installer_path = $summary.signed_installer_path
            $phaseInstaller.artifact_paths.signed_installer_sha256 = $summary.signed_installer_sha256
            $phaseInstaller.artifact_paths.signature_type = "self_signed_local_internal"
        }
        Complete-Phase -Phase $phaseInstaller -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseInstaller -Status "NO-GO" -Reason $_.Exception.Message
    }

    Start-Phase -Phase $phaseSetupFrontDoorE2e
    try {
        $setupEvidence = Assert-SetupWizardFrontDoorE2eEvidence -Path $SetupWizardFrontDoorE2eEvidenceJson -CommitSha ([string]$summary.commit_sha)
        $phaseSetupFrontDoorE2e.artifact_paths.evidence_json = $SetupWizardFrontDoorE2eEvidenceJson
        $phaseSetupFrontDoorE2e.artifact_paths.front_door_url = [string]$setupEvidence.front_door_url
        $phaseSetupFrontDoorE2e.artifact_paths.persisted_client_base_url = [string]$setupEvidence.persisted_client_base_url
        Complete-Phase -Phase $phaseSetupFrontDoorE2e -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseSetupFrontDoorE2e -Status "NO-GO" -Reason $_.Exception.Message
    }

    Start-Phase -Phase $phaseInstalledInventory
    try {
        Assert-InstalledAppInventoryEvidence -Path $InstalledInventoryEvidenceJson -CommitSha ([string]$summary.commit_sha) | Out-Null
        $phaseInstalledInventory.artifact_paths.evidence_json = $InstalledInventoryEvidenceJson
        Complete-Phase -Phase $phaseInstalledInventory -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseInstalledInventory -Status "NO-GO" -Reason $_.Exception.Message
    }

    Start-Phase -Phase $phaseInstallLifecycle
    try {
        $installerHashForEvidence = ""
        if ($phaseInstaller.artifact_paths.Contains("installer_sha256")) {
            $installerHashForEvidence = [string]$phaseInstaller.artifact_paths.installer_sha256
        }
        Assert-InstallLifecycleEvidence -Path $InstallLifecycleEvidenceJson -CommitSha ([string]$summary.commit_sha) -InstallerSha256 $installerHashForEvidence | Out-Null
        $phaseInstallLifecycle.artifact_paths.evidence_json = $InstallLifecycleEvidenceJson
        Complete-Phase -Phase $phaseInstallLifecycle -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseInstallLifecycle -Status "NO-GO" -Reason $_.Exception.Message
    }

    Start-Phase -Phase $phaseInstalledFrontDoor
    try {
        $installerHashForEvidence = ""
        if ($phaseInstaller.artifact_paths.Contains("installer_sha256")) {
            $installerHashForEvidence = [string]$phaseInstaller.artifact_paths.installer_sha256
        }
        $frontDoorEvidence = Assert-InstalledDesktopFrontDoorEvidence -Path $InstalledDesktopFrontDoorEvidenceJson -CommitSha ([string]$summary.commit_sha) -InstallerSha256 $installerHashForEvidence
        $phaseInstalledFrontDoor.artifact_paths.evidence_json = $InstalledDesktopFrontDoorEvidenceJson
        $phaseInstalledFrontDoor.artifact_paths.front_door_url = [string]$frontDoorEvidence.front_door_url
        $phaseInstalledFrontDoor.artifact_paths.persisted_client_base_url = [string]$frontDoorEvidence.persisted_client_base_url
        Complete-Phase -Phase $phaseInstalledFrontDoor -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseInstalledFrontDoor -Status "NO-GO" -Reason $_.Exception.Message
    }

    Start-Phase -Phase $phaseDesktopInstallerProof
    try {
        foreach ($requiredPhase in @($phaseInstaller, $phaseSetupFrontDoorE2e, $phaseInstalledInventory, $phaseInstallLifecycle, $phaseInstalledFrontDoor)) {
            if (-not $requiredPhase -or $requiredPhase.status -ne "GO") {
                throw "Full desktop installer release proof requires installer build, setup-wizard front-door E2E, installed inventory, install mechanics, and installed-app front-door connectivity all GO."
            }
        }
        Complete-Phase -Phase $phaseDesktopInstallerProof -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseDesktopInstallerProof -Status "NO-GO" -Reason $_.Exception.Message
    }

    Start-Phase -Phase $phaseFresh
    try {
        $installerHashForEvidence = ""
        if ($phaseInstaller.artifact_paths.Contains("installer_sha256")) {
            $installerHashForEvidence = [string]$phaseInstaller.artifact_paths.installer_sha256
        }
        $freshEvidence = Assert-FreshMachineEvidence -Path $FreshMachineEvidenceJson -CommitSha ([string]$summary.commit_sha) -InstallerSha256 $installerHashForEvidence
        $phaseFresh.artifact_paths.evidence_json = $FreshMachineEvidenceJson
        Assert-ManualProductProofEvidence -Path $ManualProductProofEvidenceJson | Out-Null
        $phaseFresh.artifact_paths.manual_product_proof_evidence_json = $ManualProductProofEvidenceJson
        $phaseFresh.artifact_paths.evidence_remote = Convert-JsonBoolean -Value (Get-JsonPropertyValue -Data $freshEvidence -Name "remote_evidence")
        Complete-Phase -Phase $phaseFresh -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseFresh -Status "NO-GO" -Reason $_.Exception.Message
    }

    Start-Phase -Phase $phaseHubInstall
    try {
        $installerHashForEvidence = ""
        if ($phaseInstaller.artifact_paths.Contains("installer_sha256")) {
            $installerHashForEvidence = [string]$phaseInstaller.artifact_paths.installer_sha256
        }
        $hubInstallEvidence = Assert-HubInstallEvidence -Path $HubInstallEvidenceJson -CommitSha ([string]$summary.commit_sha) -InstallerSha256 $installerHashForEvidence
        $phaseHubInstall.artifact_paths.evidence_json = $HubInstallEvidenceJson
        $phaseHubInstall.artifact_paths.runtime_dependency_mode = [string]$hubInstallEvidence.runtime_dependency_mode
        $phaseHubInstall.artifact_paths.agency_install_status = [string]$hubInstallEvidence.agency_install_status
        Complete-Phase -Phase $phaseHubInstall -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseHubInstall -Status "NO-GO" -Reason $_.Exception.Message
    }

    Start-Phase -Phase $phaseHubStatus
    try {
        $installerHashForEvidence = ""
        if ($phaseInstaller.artifact_paths.Contains("installer_sha256")) {
            $installerHashForEvidence = [string]$phaseInstaller.artifact_paths.installer_sha256
        }
        $hubStatusEvidence = Assert-HubStatusEvidence -Path $HubStatusEvidenceJson -CommitSha ([string]$summary.commit_sha) -InstallerSha256 $installerHashForEvidence
        $phaseHubStatus.artifact_paths.evidence_json = $HubStatusEvidenceJson
        $phaseHubStatus.artifact_paths.hub_base_url = [string]$hubStatusEvidence.hub_base_url
        $phaseHubStatus.artifact_paths.hub_status = [string]$hubStatusEvidence.hub_status
        Complete-Phase -Phase $phaseHubStatus -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseHubStatus -Status "NO-GO" -Reason $_.Exception.Message
    }

    Start-Phase -Phase $phaseHubIdentity
    try {
        $identityEvidence = Assert-HubIdentityEvidence -Path $HubIdentityEvidenceJson
        $phaseHubIdentity.artifact_paths.evidence_json = $HubIdentityEvidenceJson
        $phaseHubIdentity.artifact_paths.hub_display_name = [string]$identityEvidence.hub_display_name
        Complete-Phase -Phase $phaseHubIdentity -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseHubIdentity -Status "NO-GO" -Reason $_.Exception.Message
    }

    Start-Phase -Phase $phaseHubFrontDoor
    try {
        $frontDoorEvidence = Assert-HubFrontDoorEvidence -Path $HubNetworkBoundaryEvidenceJson
        $phaseHubFrontDoor.artifact_paths.evidence_json = $HubNetworkBoundaryEvidenceJson
        $phaseHubFrontDoor.artifact_paths.front_door_url = [string]$frontDoorEvidence.front_door_url
        Complete-Phase -Phase $phaseHubFrontDoor -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseHubFrontDoor -Status "NO-GO" -Reason $_.Exception.Message
    }

    Start-Phase -Phase $phaseHubDiscovery
    try {
        $discoveryEvidence = Assert-HubDiscoveryEvidence -Path $HubDiscoveryEvidenceJson
        $phaseHubDiscovery.artifact_paths.evidence_json = $HubDiscoveryEvidenceJson
        $phaseHubDiscovery.artifact_paths.advertised_display_name = [string]$discoveryEvidence.advertised_display_name
        Complete-Phase -Phase $phaseHubDiscovery -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseHubDiscovery -Status "NO-GO" -Reason $_.Exception.Message
    }

    Start-Phase -Phase $phaseFirewallBoundary
    try {
        $frontDoorEvidence = Assert-HubFrontDoorEvidence -Path $HubNetworkBoundaryEvidenceJson
        if ([string]$frontDoorEvidence.firewall_status -notin @("configured", "already_present")) {
            throw "Firewall boundary evidence must show configured/already_present Caddy front-door rule."
        }
        Complete-Phase -Phase $phaseFirewallBoundary -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseFirewallBoundary -Status "NO-GO" -Reason $_.Exception.Message
    }

    Start-Phase -Phase $phaseInstallerRoleFlow
    try {
        $installerRolePath = if ($InstallerRoleEvidenceJson) { $InstallerRoleEvidenceJson } else { $HubInstallEvidenceJson }
        $installerRoleEvidence = Assert-InstallerRoleEvidence -Path $installerRolePath
        Complete-Phase -Phase $phaseInstallerRoleFlow -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseInstallerRoleFlow -Status "NO-GO" -Reason $_.Exception.Message
    }

    Start-Phase -Phase $phaseWslPolicy
    try {
        $wslPolicyDecision = Resolve-WslPolicyPhaseEvidence -ValidationScope $ValidationScope -WslPolicyEvidenceJson $WslPolicyEvidenceJson
        if ([string]$wslPolicyDecision.status -eq "GO") {
            $wslPolicyEvidence = $wslPolicyDecision.evidence
            $phaseWslPolicy.artifact_paths.evidence_json = $WslPolicyEvidenceJson
            $phaseWslPolicy.artifact_paths.planned_wsl_memory_gb = [int]$wslPolicyDecision.planned_wsl_memory_gb
            $phaseWslPolicy.artifact_paths.planned_wsl_processors = [int]$wslPolicyDecision.planned_wsl_processors
            $phaseWslPolicy.artifact_paths.agency_install_status = [string]$wslPolicyDecision.agency_install_status
            $summary.wsl2_runtime_policy_status = "GO"
            $summary.wsl2_runtime_policy_path = $WslPolicyEvidenceJson
            $summary.wsl2_planned_memory_gb = [int]$wslPolicyDecision.planned_wsl_memory_gb
            $summary.wsl2_planned_processors = [int]$wslPolicyDecision.planned_wsl_processors
            Complete-Phase -Phase $phaseWslPolicy -Status "GO"
        }
        elseif ([string]$wslPolicyDecision.status -eq "N/A") {
            $summary.wsl2_runtime_policy_status = "N/A"
            $summary.wsl2_runtime_policy_reason = [string]$wslPolicyDecision.reason
            Complete-Phase -Phase $phaseWslPolicy -Status "N/A" -Reason ([string]$wslPolicyDecision.reason)
        }
        else {
            throw ([string]$wslPolicyDecision.reason)
        }
    }
    catch {
        $summary.wsl2_runtime_policy_status = "NO-GO"
        $summary.wsl2_runtime_policy_reason = $_.Exception.Message
        Complete-Phase -Phase $phaseWslPolicy -Status "NO-GO" -Reason $_.Exception.Message
    }

    Start-Phase -Phase $phaseLan
    try {
        $installerHashForEvidence = ""
        if ($phaseInstaller.artifact_paths.Contains("installer_sha256")) {
            $installerHashForEvidence = [string]$phaseInstaller.artifact_paths.installer_sha256
        }
        $lanEvidence = Assert-LanEvidence -Path $LanEvidenceJson -CommitSha ([string]$summary.commit_sha) -InstallerSha256 $installerHashForEvidence
        $phaseLan.artifact_paths.evidence_json = $LanEvidenceJson
        $phaseLan.artifact_paths.evidence_remote = Convert-JsonBoolean -Value (Get-JsonPropertyValue -Data $lanEvidence -Name "remote_evidence")
        Complete-Phase -Phase $phaseLan -Status "GO"
    }
    catch {
        Complete-Phase -Phase $phaseLan -Status "NO-GO" -Reason $_.Exception.Message
    }
}
catch {
    $exitCode = 1
    Write-Host "BETA RELEASE VALIDATION NO-GO: $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    foreach ($phase in $summary.phases) {
        if ($phase.status -eq "RUNNING") {
            Complete-Phase -Phase $phase -Status "NO-GO" -Reason "Phase terminated before completion."
        }
    }
    if ($summary.phases | Where-Object { $_.status -eq "NO-GO" -or $_.status -eq "NOT_RUN" }) {
        $exitCode = 1
    }
    Set-BetaStatusFields -Summary $summary
    Save-BetaSummary -Summary $summary -JsonPath $jsonSummary -TextPath $textSummary
    try {
        Publish-StableReleaseArtifacts `
            -Summary $summary `
            -InstallerPhase $phaseInstaller `
            -SetupFrontDoorE2ePhase $phaseSetupFrontDoorE2e `
            -InstalledInventoryPhase $phaseInstalledInventory `
            -InstallLifecyclePhase $phaseInstallLifecycle `
            -InstalledFrontDoorPhase $phaseInstalledFrontDoor `
            -BackupPhase $phaseBackup `
            -RepoRoot $repoRoot `
            -ValidationRoot $validationRoot `
            -JsonSummary $jsonSummary `
            -TextSummary $textSummary `
            -ReleaseRoot $ReleaseArtifactRoot `
            -AllowReplace:($AllowReplaceReleaseArtifacts.IsPresent) | Out-Null
        Save-BetaSummary -Summary $summary -JsonPath $jsonSummary -TextPath $textSummary
    }
    catch {
        $exitCode = 1
        Write-Host "Stable release artifact publication NO-GO: $($_.Exception.Message)" -ForegroundColor Red
        $summary.stable_release_artifact_path = $null
        $summary.stable_release_artifacts_manifest = $null
        Save-BetaSummary -Summary $summary -JsonPath $jsonSummary -TextPath $textSummary
    }
    Write-Host "Beta release validation JSON summary: $jsonSummary"
    Write-Host "Beta release validation text summary: $textSummary"
    if ($summary.stable_release_artifact_path) {
        Write-Host "Stable release artifact path: $($summary.stable_release_artifact_path)"
    }
}

exit $exitCode
