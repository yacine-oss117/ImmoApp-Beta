param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("check", "reset")]
    [string]$Mode,
    [int]$ArtifactRetentionDays = 7,
    [switch]$CleanArtifacts,
    [switch]$CleanPytestCache,
    [switch]$CleanDockerApp,
    [switch]$RestartDocker,
    [switch]$KillStaleDesktopProcesses,
    [switch]$KillStaleServerProcesses,
    [int]$WarnFreeMemoryGb = 6,
    [int]$MinCriticalFreeMemoryGb = 1,
    [int]$MinCommitHeadroomGb = 2,
    [int]$MinFreeMemoryGb = -1,
    [int]$MinFreeDiskGb = 20,
    [bool]$CheckClientQtImport = $true,
    [switch]$RequireDocker,
    [switch]$RequireInteractiveDesktop,
    [switch]$RequireBackend,
    [string]$BaseUrl = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

$warnings = New-Object System.Collections.Generic.List[string]
$failures = New-Object System.Collections.Generic.List[string]
$cleanupActions = New-Object System.Collections.Generic.List[object]
$staleProcesses = New-Object System.Collections.Generic.List[object]
$artifactsPruned = 0
$dockerAvailable = $false
$interactiveDesktop = [Environment]::UserInteractive
$freeMemoryGb = $null
$commitLimitGb = $null
$committedGb = $null
$commitHeadroomGb = $null
$freeDiskGb = $null
$spawnCanaries = [ordered]@{}

function Add-RunnerWarning {
    param([Parameter(Mandatory = $true)][string]$Message)
    $warnings.Add($Message) | Out-Null
}

function Add-RunnerFailure {
    param([Parameter(Mandatory = $true)][string]$Message)
    $failures.Add($Message) | Out-Null
}

function Add-CleanupAction {
    param(
        [Parameter(Mandatory = $true)][string]$Action,
        [Parameter(Mandatory = $true)][string]$Target
    )
    $cleanupActions.Add([pscustomobject]@{
            action = $Action
            target = $Target
    }) | Out-Null
}

function Write-RunnerStep {
    param([Parameter(Mandatory = $true)][string]$Message)
    if (-not $Json) {
        Write-Host "[runner-preflight] $Message"
    }
}

function Convert-ToSafeSummary {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ""
    }
    $cleaned = $Value -replace "[`r`n]+", " "
    $cleaned = $cleaned -replace "(?i)(password|token|secret|key)=\S+", '$1=<redacted>'
    $cleaned = $cleaned.Trim()
    if ($cleaned.Length -gt 500) {
        return $cleaned.Substring(0, 500)
    }
    return $cleaned
}

function Set-SpawnCanaryResult {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Result,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )
    $spawnCanaries[$Name] = [ordered]@{
        ok = [bool]$Result.ok
        exit_code = $Result.exit_code
        timeout_seconds = $TimeoutSeconds
        stderr_summary = Convert-ToSafeSummary -Value ([string]$Result.stderr)
    }
}

function Convert-ToGb {
    param([double]$Bytes)
    return [Math]::Round(($Bytes / 1GB), 2)
}

function Convert-KbToGb {
    param([double]$Kilobytes)
    return [Math]::Round(($Kilobytes / 1MB), 2)
}

function Get-CanonicalPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    try {
        return (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    }
    catch {
        return [System.IO.Path]::GetFullPath($Path)
    }
}

function Test-PathUnderRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )
    $full = (Get-CanonicalPath -Path $Path).TrimEnd("\", "/")
    $rootFull = (Get-CanonicalPath -Path $Root).TrimEnd("\", "/")
    if ($full.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    return $full.StartsWith("$rootFull\", [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-SafeCleanupTarget {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$AllowedRoots
    )
    foreach ($root in $AllowedRoots) {
        if (Test-PathUnderRoot -Path $Path -Root $root) {
            return
        }
    }
    throw "Refusing to clean path outside allowed E2E roots: $Path"
}

function Remove-SafePath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Reason,
        [Parameter(Mandatory = $true)][string[]]$AllowedRoots
    )
    Assert-SafeCleanupTarget -Path $Path -AllowedRoots $AllowedRoots
    if ($Mode -eq "check") {
        Add-CleanupAction -Action "would_remove:$Reason" -Target $Path
        return
    }
    Remove-Item -LiteralPath $Path -Recurse -Force
    Add-CleanupAction -Action "removed:$Reason" -Target $Path
    $script:artifactsPruned += 1
}

function Invoke-ChildCommandCapture {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Description,
        [int]$TimeoutSeconds = 15
    )
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $FilePath
        $escapedArguments = @()
        foreach ($argument in $Arguments) {
            $escapedArguments += '"' + ([string]$argument).Replace('"', '\"') + '"'
        }
        $psi.Arguments = $escapedArguments -join " "
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $psi
        $null = $process.Start()
        $completed = $process.WaitForExit($TimeoutSeconds * 1000)
        if (-not $completed) {
            try {
                $process.Kill()
            }
            catch {
                Add-RunnerWarning "Timed out $Description and could not kill probe process PID $($process.Id): $($_.Exception.Message)"
            }
            return [pscustomobject]@{
                ok = $false
                exit_code = $null
                stdout = ""
                stderr = "$Description timed out after $TimeoutSeconds seconds."
            }
        }
        return [pscustomobject]@{
            ok = ($process.ExitCode -eq 0)
            exit_code = $process.ExitCode
            stdout = $process.StandardOutput.ReadToEnd()
            stderr = $process.StandardError.ReadToEnd()
        }
    }
    catch {
        return [pscustomobject]@{
            ok = $false
            exit_code = $null
            stdout = ""
            stderr = "$Description failed: $($_.Exception.Message)"
        }
    }
}

function Test-ChildCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Description,
        [int]$TimeoutSeconds = 15
    )
    $result = Invoke-ChildCommandCapture -FilePath $FilePath -Arguments $Arguments -Description $Description -TimeoutSeconds $TimeoutSeconds
    if (-not $result.ok) {
        $exitText = if ($null -eq $result.exit_code) { "no exit code" } else { "exit code $($result.exit_code)" }
        Add-RunnerFailure "$Description failed with $exitText. Output: $($result.stdout.Trim()) $($result.stderr.Trim())"
        return $false
    }
    return $true
}

function Invoke-RequiredSpawnCanary {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Description,
        [int]$TimeoutSeconds = 15
    )
    $result = Invoke-ChildCommandCapture -FilePath $FilePath -Arguments $Arguments -Description $Description -TimeoutSeconds $TimeoutSeconds
    Set-SpawnCanaryResult -Name $Name -Result $result -TimeoutSeconds $TimeoutSeconds
    if (-not $result.ok) {
        $exitText = if ($null -eq $result.exit_code) { "no exit code" } else { "exit code $($result.exit_code)" }
        Add-RunnerFailure "$Description failed with $exitText. Output: $(Convert-ToSafeSummary -Value ([string]$result.stderr))"
        return $false
    }
    return $true
}

function Test-PythonExecutable {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$CanaryName
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        Add-RunnerFailure "$Label Python was not found at $Path."
        Set-SpawnCanaryResult -Name $CanaryName -Result ([pscustomobject]@{
            ok = $false
            exit_code = $null
            stdout = ""
            stderr = "$Label Python was not found at $Path."
        }) -TimeoutSeconds 0
        return
    }
    $null = Invoke-RequiredSpawnCanary -Name $CanaryName -FilePath $Path -Arguments @("-c", "print('ok')") -Description "$Label Python spawn check"
}

function Test-SystemResources {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][hashtable]$RuntimePaths
    )
    try {
        Add-Type -AssemblyName Microsoft.VisualBasic
        $computerInfo = New-Object Microsoft.VisualBasic.Devices.ComputerInfo
        $script:freeMemoryGb = Convert-ToGb -Bytes ([double]$computerInfo.AvailablePhysicalMemory)
        if ($script:freeMemoryGb -lt $WarnFreeMemoryGb) {
            Add-RunnerWarning "Free physical memory is $script:freeMemoryGb GB; warning threshold is $WarnFreeMemoryGb GB. This is diagnostic only unless below the critical threshold."
        }
        if ($script:freeMemoryGb -lt $MinCriticalFreeMemoryGb) {
            Add-RunnerFailure "Free physical memory is critically low at $script:freeMemoryGb GB; required critical minimum is $MinCriticalFreeMemoryGb GB."
        }
    }
    catch {
        Add-RunnerWarning "Could not read Windows physical memory information: $($_.Exception.Message)"
    }

    try {
        $committedCounter = New-Object System.Diagnostics.PerformanceCounter("Memory", "Committed Bytes")
        $limitCounter = New-Object System.Diagnostics.PerformanceCounter("Memory", "Commit Limit")
        $committedBytes = [double]$committedCounter.NextValue()
        $limitBytes = [double]$limitCounter.NextValue()
        $committedCounter.Close()
        $limitCounter.Close()
        if ($committedBytes -gt 0 -and $limitBytes -gt 0) {
            $script:committedGb = Convert-ToGb -Bytes $committedBytes
            $script:commitLimitGb = Convert-ToGb -Bytes $limitBytes
            $script:commitHeadroomGb = [Math]::Round(($script:commitLimitGb - $script:committedGb), 2)
        }
    }
    catch {
        $script:committedGb = $null
        $script:commitLimitGb = $null
        $script:commitHeadroomGb = $null
    }

    if ($null -eq $script:commitHeadroomGb) {
        try {
            $wmic = Get-Command wmic.exe -ErrorAction SilentlyContinue
            if ($null -ne $wmic) {
                $result = Invoke-ChildCommandCapture -FilePath $wmic.Source -Arguments @("os", "get", "FreeVirtualMemory,TotalVirtualMemorySize", "/FORMAT:LIST") -Description "wmic commit/page-file headroom inspection" -TimeoutSeconds 10
                if ($result.ok) {
                    $freeVirtualKb = $null
                    $totalVirtualKb = $null
                    foreach ($rawLine in ($result.stdout -split "`r?`n")) {
                        $line = $rawLine.Trim()
                        if ($line.StartsWith("FreeVirtualMemory=")) {
                            $freeVirtualKb = [double]$line.Substring("FreeVirtualMemory=".Length)
                        }
                        elseif ($line.StartsWith("TotalVirtualMemorySize=")) {
                            $totalVirtualKb = [double]$line.Substring("TotalVirtualMemorySize=".Length)
                        }
                    }
                    if ($null -ne $freeVirtualKb -and $null -ne $totalVirtualKb) {
                        $script:commitLimitGb = Convert-KbToGb -Kilobytes $totalVirtualKb
                        $script:commitHeadroomGb = Convert-KbToGb -Kilobytes $freeVirtualKb
                        $script:committedGb = [Math]::Round(($script:commitLimitGb - $script:commitHeadroomGb), 2)
                    }
                }
            }
        }
        catch {
            $script:committedGb = $null
            $script:commitLimitGb = $null
            $script:commitHeadroomGb = $null
        }
    }

    if ($null -eq $script:commitHeadroomGb) {
        Add-RunnerWarning "Windows commit/page-file headroom was unavailable; relying on process spawn canaries."
    }
    elseif ($script:commitHeadroomGb -lt $MinCommitHeadroomGb) {
        Add-RunnerFailure "Windows commit/page-file headroom is $script:commitHeadroomGb GB; required minimum is $MinCommitHeadroomGb GB."
    }

    try {
        $repoRootPath = Get-CanonicalPath -Path $RepoRoot
        $repoDriveRoot = [System.IO.Path]::GetPathRoot($repoRootPath)
        $repoDrive = New-Object System.IO.DriveInfo($repoDriveRoot)
        $repoDriveName = $repoDrive.Name
        $script:freeDiskGb = Convert-ToGb -Bytes ([double]$repoDrive.AvailableFreeSpace)
        if ($script:freeDiskGb -lt $MinFreeDiskGb) {
            Add-RunnerFailure "Free disk on repo drive $repoDriveName is $script:freeDiskGb GB; required minimum is $MinFreeDiskGb GB."
        }
    }
    catch {
        Add-RunnerFailure "Could not read free disk for the repo drive: $($_.Exception.Message)"
    }

    try {
        $dataRoot = [string]$RuntimePaths.DataRoot
        if (-not [string]::IsNullOrWhiteSpace($dataRoot)) {
            $dataRootPath = Get-CanonicalPath -Path $dataRoot
            $dataDriveRoot = [System.IO.Path]::GetPathRoot($dataRootPath)
            $dataDrive = New-Object System.IO.DriveInfo($dataDriveRoot)
            $dataDriveName = $dataDrive.Name
            $dataFreeGb = Convert-ToGb -Bytes ([double]$dataDrive.AvailableFreeSpace)
            if ($dataFreeGb -lt $MinFreeDiskGb) {
                Add-RunnerFailure "Free disk on Docker/data drive $dataDriveName is $dataFreeGb GB; required minimum is $MinFreeDiskGb GB."
            }
        }
    }
    catch {
        Add-RunnerWarning "Could not read free disk for the Docker/data drive: $($_.Exception.Message)"
    }
}

function Test-ArtifactRoot {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$ArtifactRoot
    )
    $tmpRoot = Join-Path $RepoRoot ".tmp"
    if ($Mode -eq "check") {
        if (-not (Test-Path -LiteralPath $tmpRoot)) {
            Add-RunnerWarning "Repo .tmp does not exist; reset/E2E will create it when mutation is allowed: $tmpRoot"
        }
        elseif (-not (Get-Item -LiteralPath $tmpRoot).PSIsContainer) {
            Add-RunnerFailure "Repo .tmp path exists but is not a directory: $tmpRoot"
        }
        if (Test-Path -LiteralPath $ArtifactRoot) {
            if (-not (Get-Item -LiteralPath $ArtifactRoot).PSIsContainer) {
                Add-RunnerFailure "Desktop E2E artifact root exists but is not a directory: $ArtifactRoot"
            }
        }
        else {
            Add-RunnerWarning "Desktop E2E artifact root does not exist yet; reset/E2E will create it when mutation is allowed: $ArtifactRoot"
        }
        return
    }

    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
    Add-CleanupAction -Action "ensured_directory" -Target $ArtifactRoot
    $probe = Join-Path $ArtifactRoot ".runner_writable_probe"
    try {
        Set-Content -Path $probe -Value "ok" -Encoding ASCII
        Remove-Item -LiteralPath $probe -Force
        Add-CleanupAction -Action "verified_writable" -Target $ArtifactRoot
    }
    catch {
        Add-RunnerFailure "Desktop E2E artifact root is not writable: $ArtifactRoot ($($_.Exception.Message))"
    }
}

function Remove-StaleArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$ArtifactRoot
    )
    if (-not $CleanArtifacts) {
        return
    }
    $tmpRoot = Join-Path $RepoRoot ".tmp"
    $allowed = @($ArtifactRoot, $tmpRoot)
    if (Test-Path -LiteralPath $ArtifactRoot) {
        $cutoff = (Get-Date).ToUniversalTime().AddDays(-1 * $ArtifactRetentionDays)
        foreach ($candidate in Get-ChildItem -LiteralPath $ArtifactRoot -Force) {
            if ($ArtifactRetentionDays -gt 0 -and $candidate.LastWriteTimeUtc -ge $cutoff) {
                continue
            }
            Remove-SafePath -Path $candidate.FullName -Reason "desktop_e2e_artifact" -AllowedRoots $allowed
        }
    }
    if (Test-Path -LiteralPath $tmpRoot) {
        foreach ($candidate in Get-ChildItem -LiteralPath $tmpRoot -Force) {
            if ($candidate.FullName.Equals((Get-CanonicalPath -Path $ArtifactRoot), [System.StringComparison]::OrdinalIgnoreCase)) {
                continue
            }
            if ($candidate.Name -eq "e2e-sync-marker.json" -or $candidate.Name -like "e2e-*" -or $candidate.Name -like "e2e_*" -or $candidate.Name -like "desktop-e2e-*" -or $candidate.Name -like "desktop_e2e_*") {
                Remove-SafePath -Path $candidate.FullName -Reason "repo_e2e_tmp" -AllowedRoots @($tmpRoot)
            }
        }
    }
}

function Remove-PytestCache {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    if (-not $CleanPytestCache) {
        return
    }
    $cacheRoot = Join-Path $RepoRoot ".cache"
    $pytestCache = Join-Path $cacheRoot "pytest"
    if (Test-Path -LiteralPath $pytestCache) {
        Remove-SafePath -Path $pytestCache -Reason "repo_pytest_cache" -AllowedRoots @($cacheRoot)
    }
}

function Remove-DockerAppE2ETmp {
    param([Parameter(Mandatory = $true)][hashtable]$RuntimePaths)
    if (-not $CleanDockerApp) {
        return
    }
    $tmpRoot = [string]$RuntimePaths.DataAppTmpRoot
    if ([string]::IsNullOrWhiteSpace($tmpRoot) -or -not (Test-Path -LiteralPath $tmpRoot)) {
        Add-RunnerWarning "Docker app tmp root was not found; no Docker app E2E tmp cleanup was performed."
        return
    }
    $matched = $false
    foreach ($candidate in Get-ChildItem -LiteralPath $tmpRoot -Force) {
        if ($candidate.Name -like "e2e-*" -or $candidate.Name -like "e2e_*" -or $candidate.Name -like "desktop-e2e-*" -or $candidate.Name -like "desktop_e2e_*" -or $candidate.Name -like "pytest-e2e-*") {
            $matched = $true
            Remove-SafePath -Path $candidate.FullName -Reason "docker_app_e2e_tmp" -AllowedRoots @($tmpRoot)
        }
    }
    if (-not $matched) {
        Add-RunnerWarning "No explicitly E2E-owned Docker app tmp children were found under $tmpRoot."
    }
}

function Get-E2EStaleProcesses {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$ArtifactRoot
    )
    if (-not ($KillStaleDesktopProcesses -or $KillStaleServerProcesses)) {
        return
    }
    $repoNeedle = (Get-CanonicalPath -Path $RepoRoot).ToLowerInvariant()
    $artifactNeedle = (Get-CanonicalPath -Path $ArtifactRoot).ToLowerInvariant()
    $repoNeedle = $repoNeedle.Replace("/", "\")
    $artifactNeedle = $artifactNeedle.Replace("/", "\")
    try {
        $wmic = Get-Command wmic.exe -ErrorAction SilentlyContinue
        if ($null -eq $wmic) {
            Add-RunnerWarning "wmic.exe is unavailable; stale E2E process ownership cannot be identified safely, so no process will be killed."
            return
        }
        else {
            $where = "Name='python.exe' or Name='pythonw.exe' or Name='powershell.exe' or Name='pwsh.exe'"
            $result = Invoke-ChildCommandCapture -FilePath $wmic.Source -Arguments @("process", "where", $where, "get", "ProcessId,Name,CommandLine", "/FORMAT:LIST") -Description "wmic process ownership inspection" -TimeoutSeconds 10
            if (-not $result.ok) {
                throw $result.stderr
            }
            $processes = New-Object System.Collections.Generic.List[object]
            $current = @{}
            foreach ($rawLine in ($result.stdout -split "`r?`n")) {
                $line = $rawLine.Trim()
                if ([string]::IsNullOrWhiteSpace($line)) {
                    if ($current.ContainsKey("ProcessId")) {
                        $recordName = if ($current.ContainsKey("Name")) { $current["Name"] } else { "" }
                        $recordCommandLine = if ($current.ContainsKey("CommandLine")) { $current["CommandLine"] } else { "" }
                        $processes.Add([pscustomobject]@{
                                ProcessId = $current["ProcessId"]
                                Name = $recordName
                                CommandLine = $recordCommandLine
                            }) | Out-Null
                    }
                    $current = @{}
                    continue
                }
                $eq = $line.IndexOf("=")
                if ($eq -le 0) {
                    continue
                }
                $key = $line.Substring(0, $eq)
                $value = $line.Substring($eq + 1)
                $current[$key] = $value
            }
            if ($current.ContainsKey("ProcessId")) {
                $recordName = if ($current.ContainsKey("Name")) { $current["Name"] } else { "" }
                $recordCommandLine = if ($current.ContainsKey("CommandLine")) { $current["CommandLine"] } else { "" }
                $processes.Add([pscustomobject]@{
                        ProcessId = $current["ProcessId"]
                        Name = $recordName
                        CommandLine = $recordCommandLine
                    }) | Out-Null
            }
        }
    }
    catch {
        if ($Mode -eq "reset") {
            Add-RunnerFailure "Could not enumerate processes for requested stale E2E ownership cleanup: $($_.Exception.Message)"
        }
        else {
            Add-RunnerWarning "Could not enumerate processes for stale E2E ownership checks: $($_.Exception.Message)"
        }
        return
    }
    foreach ($proc in $processes) {
        if ([int]$proc.ProcessId -eq $PID) {
            continue
        }
        $cmd = ([string]$proc.CommandLine).Replace("/", "\").ToLowerInvariant()
        $name = [string]$proc.Name
        $matchesRepo = $cmd.Contains($repoNeedle)
        $matchesArtifact = $cmd.Contains($artifactNeedle)
        $reason = ""
        $kind = ""
        if ($matchesRepo -and $cmd.Contains("\app\main.py")) {
            $reason = "repo_app_main"
            $kind = "desktop"
        }
        elseif ($matchesArtifact) {
            $reason = "desktop_e2e_artifact_root"
            $kind = "desktop"
        }
        elseif ($matchesRepo -and $cmd.Contains("\app\tests\e2e_desktop")) {
            $reason = "desktop_e2e_pytest"
            $kind = "server"
        }
        elseif ($matchesRepo -and $cmd.Contains("app.tests.e2e_desktop.preflight_cli")) {
            $reason = "desktop_e2e_preflight"
            $kind = "server"
        }
        if ([string]::IsNullOrWhiteSpace($reason)) {
            continue
        }
        $staleProcesses.Add([pscustomobject]@{
                pid = [int]$proc.ProcessId
                name = $name
                kind = $kind
                reason = $reason
                command_line = [string]$proc.CommandLine
            }) | Out-Null
    }
}

function Stop-E2EStaleProcesses {
    if ($Mode -ne "reset") {
        return
    }
    foreach ($proc in $staleProcesses) {
        if ($proc.kind -eq "desktop" -and -not $KillStaleDesktopProcesses) {
            continue
        }
        if ($proc.kind -eq "server" -and -not $KillStaleServerProcesses) {
            continue
        }
        Write-Host "Stopping stale E2E process PID=$($proc.pid) Name=$($proc.name) Reason=$($proc.reason)"
        Write-Host "CommandLine: $($proc.command_line)"
        try {
            Stop-Process -Id $proc.pid -Force -ErrorAction Stop
            Add-CleanupAction -Action "stopped_process:$($proc.reason)" -Target "PID $($proc.pid)"
        }
        catch {
            Add-RunnerFailure "Failed to stop stale E2E process PID $($proc.pid): $($_.Exception.Message)"
        }
    }
}

function Test-DockerAvailability {
    param([switch]$Required)
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        if ($Required) {
            Add-RunnerFailure "Docker CLI is required for the requested action but was not found on PATH."
        }
        return
    }
    $script:dockerAvailable = $true
    if ($Required) {
        $docker = Get-Command docker -ErrorAction SilentlyContinue
        $result = Invoke-ChildCommandCapture -FilePath $docker.Source -Arguments @("info") -Description "Docker daemon check" -TimeoutSeconds 20
        if (-not $result.ok) {
            Add-RunnerFailure "Docker daemon is not reachable. Output: $(Convert-ToSafeSummary -Value ([string]$result.stderr))"
        }
    }
}

function Invoke-BackendIdentityPreflight {
    param(
        [Parameter(Mandatory = $true)][string]$ServerPython,
        [Parameter(Mandatory = $true)][string]$Url
    )
    $healthReady = $false
    try {
        Invoke-WebRequest -Method Get -Uri "$($Url.TrimEnd('/'))/api/v1/health/ready/" -TimeoutSec 3 | Out-Null
        $healthReady = $true
    }
    catch {
        if ($RequireBackend) {
            Add-RunnerFailure "Backend health endpoint is not ready at $Url`: $($_.Exception.Message)"
        }
        else {
            Add-RunnerWarning "Backend health endpoint is not ready at $Url; backend identity preflight was skipped."
        }
    }
    if (-not $healthReady) {
        return
    }
    $args = @("-m", "app.tests.e2e_desktop.preflight_cli", "--base-url", $Url)
    $output = & $ServerPython @args 2>&1
    if ($LASTEXITCODE -ne 0) {
        $message = "Backend identity preflight failed with exit code $LASTEXITCODE. Output: $(($output | Out-String).Trim())"
        if ($RequireBackend) {
            Add-RunnerFailure $message
        }
        else {
            Add-RunnerWarning $message
        }
    }
}

function Restart-E2EAppStack {
    if (-not $RestartDocker) {
        return
    }
    if ($Mode -eq "check") {
        Add-CleanupAction -Action "would_restart_app_stack" -Target "scripts/stack.ps1 -Action restart-app"
        return
    }
    $stackScript = Join-Path $PSScriptRoot "stack.ps1"
    & powershell -NoProfile -ExecutionPolicy Bypass -File $stackScript -Action restart-app
    if ($LASTEXITCODE -ne 0) {
        Add-RunnerFailure "stack.ps1 -Action restart-app failed with exit code $LASTEXITCODE."
    }
    else {
        Add-CleanupAction -Action "restarted_app_stack" -Target $stackScript
    }
}

function Write-HumanSummary {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$ArtifactRoot
    )
    Write-Host "Native desktop E2E runner environment preflight"
    Write-Host "Mode:        $Mode"
    Write-Host "Repo:        $RepoRoot"
    Write-Host "Artifacts:   $ArtifactRoot"
    Write-Host "Interactive: $interactiveDesktop"
    Write-Host "Memory free: $freeMemoryGb GB (warn below $WarnFreeMemoryGb GB; critical below $MinCriticalFreeMemoryGb GB)"
    Write-Host "Committed:   $committedGb GB"
    Write-Host "Commit limit: $commitLimitGb GB"
    Write-Host "Commit headroom: $commitHeadroomGb GB (required $MinCommitHeadroomGb GB)"
    Write-Host "Disk free:   $freeDiskGb GB"
    Write-Host "Docker available: $dockerAvailable"
    Write-Host "Spawn canaries:"
    foreach ($entry in $spawnCanaries.GetEnumerator()) {
        Write-Host " - $($entry.Key): ok=$($entry.Value.ok) exit=$($entry.Value.exit_code)"
    }
    Write-Host "Stale E2E processes found: $($staleProcesses.Count)"
    if ($cleanupActions.Count -gt 0) {
        Write-Host "Cleanup actions:"
        foreach ($action in $cleanupActions) {
            Write-Host " - $($action.action): $($action.target)"
        }
    }
    if ($warnings.Count -gt 0) {
        Write-Host "Warnings:"
        foreach ($warning in $warnings) {
            Write-Host " - $warning"
        }
    }
    if ($failures.Count -gt 0) {
        Write-Host "Failures:"
        foreach ($failure in $failures) {
            Write-Host " - $failure"
        }
    }
}

$repoRoot = Get-ImmoAppRepoRoot
$runtimePaths = Get-ImmoAppRuntimePaths
$artifactRoot = Join-Path $repoRoot ".tmp\desktop_e2e_artifacts"
$serverPython = Get-ImmoAppVenvPython -Kind server
$clientPython = Get-ImmoAppVenvPython -Kind client
if ($MinFreeMemoryGb -ge 0) {
    $MinCriticalFreeMemoryGb = $MinFreeMemoryGb
}
if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    $BaseUrl = if ($env:IMMOAPP_E2E_BASE_URL) { $env:IMMOAPP_E2E_BASE_URL } else { "http://127.0.0.1:8000" }
}

Write-RunnerStep "checking host and interactive desktop"
if (-not (Test-ImmoAppHostWindows)) {
    Add-RunnerFailure "Native desktop E2E requires a Windows host."
}
if ($RequireInteractiveDesktop -and -not $interactiveDesktop) {
    Add-RunnerFailure "Native desktop E2E requires an interactive desktop session."
}

$powerShellCommand = Get-Command powershell -ErrorAction SilentlyContinue
if ($null -eq $powerShellCommand) {
    Add-RunnerFailure "powershell was not found on PATH."
}
else {
    Write-RunnerStep "checking PowerShell child process spawning"
    $null = Invoke-RequiredSpawnCanary -Name "powershell" -FilePath $powerShellCommand.Source -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "Write-Output ok") -Description "PowerShell child process spawn check"
}

Write-RunnerStep "checking Python executables"
Test-PythonExecutable -Path $serverPython -Label "Server" -CanaryName "server_python"
Test-PythonExecutable -Path $clientPython -Label "Client" -CanaryName "client_python"
if ($CheckClientQtImport -and (Test-Path -LiteralPath $clientPython)) {
    Write-RunnerStep "checking client Qt import"
    $null = Invoke-RequiredSpawnCanary -Name "client_qt_import" -FilePath $clientPython -Arguments @("-c", "from PySide6.QtWidgets import QApplication; print('ok')") -Description "Client PySide6 Qt import check" -TimeoutSeconds 20
}
Write-RunnerStep "checking memory and disk resources"
Test-SystemResources -RepoRoot $repoRoot -RuntimePaths $runtimePaths
Write-RunnerStep "checking artifact root"
Test-ArtifactRoot -RepoRoot $repoRoot -ArtifactRoot $artifactRoot
Write-RunnerStep "checking Docker availability when requested"
Test-DockerAvailability -Required:($CleanDockerApp -or $RestartDocker -or $RequireDocker)
Write-RunnerStep "checking stale E2E processes when requested"
Get-E2EStaleProcesses -RepoRoot $repoRoot -ArtifactRoot $artifactRoot

if ($Mode -eq "reset") {
    Write-RunnerStep "performing requested safe cleanup"
    Remove-StaleArtifacts -RepoRoot $repoRoot -ArtifactRoot $artifactRoot
    Remove-PytestCache -RepoRoot $repoRoot
    Remove-DockerAppE2ETmp -RuntimePaths $runtimePaths
    Stop-E2EStaleProcesses
    Restart-E2EAppStack
}

if ($RequireBackend) {
    Write-RunnerStep "checking backend identity"
    Invoke-BackendIdentityPreflight -ServerPython $serverPython -Url $BaseUrl
}

$summary = [ordered]@{
    ok = ($failures.Count -eq 0)
    mode = $Mode
    warnings = @($warnings.ToArray())
    failures = @($failures.ToArray())
    free_memory_gb = $freeMemoryGb
    warn_free_memory_gb = $WarnFreeMemoryGb
    min_critical_free_memory_gb = $MinCriticalFreeMemoryGb
    commit_limit_gb = $commitLimitGb
    committed_gb = $committedGb
    commit_headroom_gb = $commitHeadroomGb
    min_commit_headroom_gb = $MinCommitHeadroomGb
    free_disk_gb = $freeDiskGb
    interactive_desktop = $interactiveDesktop
    docker_available = $dockerAvailable
    spawn_canaries = $spawnCanaries
    stale_processes_found = @($staleProcesses.ToArray())
    artifacts_pruned = $artifactsPruned
    cleanup_actions_taken = @($cleanupActions.ToArray())
}

if ($Json) {
    $summary | ConvertTo-Json -Depth 6
}
else {
    Write-HumanSummary -RepoRoot $repoRoot -ArtifactRoot $artifactRoot
}

if ($failures.Count -gt 0) {
    if ($Json) {
        [Environment]::Exit(1)
    }
    throw "Native desktop E2E runner environment preflight failed."
}
