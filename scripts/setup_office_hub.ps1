param(
    [ValidateSet("HubDesktop", "WorkstationOnly", "HubOnly")]
    [string]$Role = "HubDesktop",
    [string]$HubBaseUrl = "",
    [string]$HubDisplayName = "",
    [string]$HubName = "",
    [string]$DataRoot = "C:\ProgramData\ImmoApp",
    [switch]$NoAutoStart,
    [switch]$NoLanAccess,
    [switch]$CreateFirewallRule,
    [switch]$StartHub,
    [switch]$NoStartHub,
    [switch]$ConfigureWslRuntimeCandidate,
    [switch]$NoShortcuts,
    [switch]$ValidateOnly,
    [string]$OwnerAuthorizationEvidenceJson = "",
    [string]$SetupRunId = "",
    [object]$SelectedInstallDesktop = $false,
    [object]$SelectedInstallHub = $true,
    [ValidateSet("", "desktop_only", "hub_only", "desktop_and_hub")]
    [string]$InstallMode = "",
    [double]$MachineTotalMemoryGb = 0,
    [int]$MachineLogicalProcessors = 0,
    [string]$RuntimeProfileJson = "",
    [string]$OutputJson = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "common.ps1")

$selectedInstallDesktopValue = Convert-ImmoAppBoolean -Value $SelectedInstallDesktop
$selectedInstallHubValue = Convert-ImmoAppBoolean -Value $SelectedInstallHub
if (-not $PSBoundParameters.ContainsKey("SelectedInstallDesktop")) {
    $selectedInstallDesktopValue = ($Role -eq "HubDesktop")
}
if (-not $PSBoundParameters.ContainsKey("SelectedInstallHub")) {
    $selectedInstallHubValue = ($Role -ne "WorkstationOnly")
}

function Invoke-HubRuntimeDetection {
    param([string]$OutputJson = "")
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "detect_hub_runtime.ps1"))
    if ($OutputJson) { $args += @("-OutputJson", $OutputJson) }
    $output = & powershell @args
    if ($LASTEXITCODE -ne 0) { throw "Hub runtime detection failed." }
    return (($output | Out-String) | ConvertFrom-Json)
}

function New-HubManagerShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [string]$Action = "",
        [string]$ManagerAppPath = "",
        [string[]]$ExtraArguments = @()
    )
    $shortcutRoot = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\ImmoApp Beta"
    if (-not (Test-Path -LiteralPath $shortcutRoot)) {
        New-Item -ItemType Directory -Path $shortcutRoot -Force | Out-Null
    }
    $path = Join-Path $shortcutRoot "$Name.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($path)
    if (-not [string]::IsNullOrWhiteSpace($ManagerAppPath) -and (Test-Path -LiteralPath $ManagerAppPath -PathType Leaf)) {
        $shortcut.TargetPath = $ManagerAppPath
        $shortcut.Arguments = if ([string]::IsNullOrWhiteSpace($Action)) { "" } else { "--action $Action" }
        $shortcut.WorkingDirectory = Split-Path -Parent $ManagerAppPath
    }
    else {
        $fallbackAction = if ([string]::IsNullOrWhiteSpace($Action)) { "status" } else { $Action }
        $shortcut.TargetPath = "powershell.exe"
        $shortcut.Arguments = ("-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" -Action $fallbackAction " + ($ExtraArguments -join " ")).Trim()
        $shortcut.WorkingDirectory = Split-Path -Parent $ScriptPath
    }
    $shortcut.Save()
    return $path
}

function Resolve-HubManagerAppPath {
    param([Parameter(Mandatory = $true)][string]$HubManagerScriptPath)
    $scriptRoot = Split-Path -Parent $HubManagerScriptPath
    $appRoot = Split-Path -Parent $scriptRoot
    $candidate = Join-Path $appRoot "ImmoApp Hub Manager.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        return (Resolve-Path -LiteralPath $candidate).Path
    }
    return ""
}

function Register-HubAutoStart {
    param([switch]$ValidateOnly)
    $taskName = "ImmoApp Office Hub"
    $manager = (Resolve-ImmoAppHubManagerScript).path
    $command = "powershell.exe"
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$manager`" -Action start -UseWindowsVolumes"
    if ($ValidateOnly) {
        return [ordered]@{ enabled = $true; task_name = $taskName; validate_only = $true }
    }
    $action = New-ScheduledTaskAction -Execute $command -Argument $arguments
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
    try {
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
        return [ordered]@{ enabled = $true; task_name = $taskName; validate_only = $false; status = "registered" }
    }
    catch {
        return [ordered]@{ enabled = $false; task_name = $taskName; validate_only = $false; status = "failed"; error = $_.Exception.Message }
    }
}

function Convert-HubProfileOutputToJson {
    param([Parameter(Mandatory = $true)][object[]]$Lines)
    $text = ($Lines | Out-String)
    $start = $text.IndexOf("{")
    if ($start -lt 0) {
        throw "Hub runtime profile output did not contain a JSON object."
    }
    return $text.Substring($start) | ConvertFrom-Json
}

function Test-CurrentProcessElevated {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if ($Role -eq "WorkstationOnly") {
    if ([string]::IsNullOrWhiteSpace($HubBaseUrl)) {
        throw "WorkstationOnly setup requires -HubBaseUrl."
    }
    if (Test-ImmoAppLocalhostUrl -Url $HubBaseUrl) {
        throw "WorkstationOnly setup requires a Hub front-door URL, not localhost."
    }
    if (-not $ValidateOnly) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify_lan_workstation_reachability.ps1") -HubBaseUrl $HubBaseUrl -RequireWorkstationUrl
        if ($LASTEXITCODE -ne 0) { throw "Workstation Hub reachability check failed." }
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "set_client_api_endpoint.ps1") -BaseUrl $HubBaseUrl -Username owner
        if ($LASTEXITCODE -ne 0) { throw "Desktop Hub URL configuration failed." }
    }
    $result = [ordered]@{
        kind = "immoapp_hub_setup_result"
        schema_version = 1
        role = "workstation_only"
        created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        hub_base_url = $HubBaseUrl.TrimEnd("/")
        starts_backend_services = $false
        requires_backend_runtime = $false
        proof_result = "GO"
    }
}
else {
    $oldRoot = $env:IMMOAPP_APPDATA_ROOT
    try {
        $env:IMMOAPP_APPDATA_ROOT = $DataRoot
        $paths = Get-ImmoAppRuntimePaths
        $directoryEvidence = Get-ImmoAppHubFoundationDirectoryEvidence -Create:(!$ValidateOnly.IsPresent)
        if (-not $ValidateOnly) {
            $paths = Ensure-ImmoAppRuntimeLayout
        }
        if ([string]::IsNullOrWhiteSpace($HubDisplayName) -and -not [string]::IsNullOrWhiteSpace($HubName)) {
            $HubDisplayName = $HubName
        }
        $existingIdentity = $null
        try { $existingIdentity = Read-ImmoAppHubIdentity -Optional } catch { $existingIdentity = $null }
        if ([string]::IsNullOrWhiteSpace($HubDisplayName)) {
            if ($existingIdentity) {
                $HubDisplayName = [string]$existingIdentity.hub_display_name
            }
            else {
                throw "HubDesktop setup requires -HubDisplayName. $(Get-ImmoAppHubIdentityDisplayNameHelp)"
            }
        }
        $HubDisplayName = Assert-ImmoAppHubDisplayName -HubDisplayName $HubDisplayName
        $wslRuntimeCandidateInstall = $null
        if ((-not $ValidateOnly) -and $ConfigureWslRuntimeCandidate) {
            $candidateInstallPath = Join-Path $paths.LogsRoot "managed_wsl2_runtime_candidate_install.json"
            $managerArgs = @(
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                (Join-Path $PSScriptRoot "hub_manager.ps1"),
                "-Action",
                "install-runtime-candidate",
                "-ConfirmInstallRuntimeCandidate",
                "-OutputJson",
                $candidateInstallPath
            )
            if ($MachineTotalMemoryGb -gt 0) { $managerArgs += @("-MachineTotalMemoryGb", ([string]$MachineTotalMemoryGb)) }
            if ($MachineLogicalProcessors -gt 0) { $managerArgs += @("-MachineLogicalProcessors", ([string]$MachineLogicalProcessors)) }
            if (-not [string]::IsNullOrWhiteSpace($RuntimeProfileJson)) { $managerArgs += @("-RuntimeProfileJson", $RuntimeProfileJson) }
            if (-not [string]::IsNullOrWhiteSpace($OwnerAuthorizationEvidenceJson)) {
                $managerArgs += @("-OwnerAuthorizationEvidenceJson", $OwnerAuthorizationEvidenceJson)
            }
            & powershell @managerArgs | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Hub managed WSL2 runtime candidate setup failed."
            }
            $wslRuntimeCandidateInstall = Get-Content -LiteralPath $candidateInstallPath -Raw | ConvertFrom-Json
        }
        $identity = if ($ValidateOnly) {
            [ordered]@{
                proof_result = "GO"
                validate_only = $true
                hub_identity = [ordered]@{
                    kind = "immoapp_hub_identity"
                    schema_version = 1
                    hub_id = if ($existingIdentity -and -not [string]::IsNullOrWhiteSpace([string]$existingIdentity.hub_id)) { [string]$existingIdentity.hub_id } else { "validate_only_planned_hub_id" }
                    hub_display_name = $HubDisplayName
                    friendly_name = $HubDisplayName
                    machine_hostname_readonly = $env:COMPUTERNAME
                    source = if ($existingIdentity) { [string]$existingIdentity.data.source } else { "installer_setup" }
                }
                path = Get-ImmoAppHubIdentityPath
                hub_id = if ($existingIdentity -and -not [string]::IsNullOrWhiteSpace([string]$existingIdentity.hub_id)) { [string]$existingIdentity.hub_id } else { "validate_only_planned_hub_id" }
                hostname_mutated = $false
            }
        }
        else {
            Write-ImmoAppHubIdentity -HubDisplayName $HubDisplayName -Source "installer_setup"
        }
        $stateManifest = if ($ValidateOnly) {
            [ordered]@{
                kind = "immoapp_hub_state_manifest_write_result"
                schema_version = 1
                proof_result = "GO"
                validate_only = $true
                path = Get-ImmoAppHubStateManifestPath
                hub_id = [string]$identity.hub_id
                hub_state_manifest = [ordered]@{
                    kind = "immoapp_hub_state_manifest"
                    schema_version = 1
                    hub_id = [string]$identity.hub_id
                    hub_display_name = $HubDisplayName
                    friendly_name = $HubDisplayName
                    appdata_root = [string]$paths.AppDataRoot
                    config_root = [string]$paths.ConfigRoot
                    data_root = [string]$paths.DataRoot
                    runtime_root = [string]$paths.RuntimeRoot
                    logs_root = [string]$paths.LogsRoot
                    install_lineage = "validate_only_planned_install_lineage"
                    machine_hostname_readonly = $env:COMPUTERNAME
                }
            }
        }
        else {
            Write-ImmoAppHubStateManifest -Source "installer_setup"
        }
        $envFile = Get-ImmoAppDefaultEnvFile
        $runtimeDetectionPath = if ($ValidateOnly) { "" } else { Join-Path $paths.LogsRoot "hub_runtime_detection.json" }
        $runtimeDetection = Invoke-HubRuntimeDetection -OutputJson $runtimeDetectionPath
        if (-not $ValidateOnly -and -not (Test-Path -LiteralPath $envFile)) {
            Initialize-ImmoAppEnvFileFromTemplate | Out-Null
        }
        $hubManagerScript = Resolve-ImmoAppHubManagerScript
        $hubManagerAppPath = Resolve-HubManagerAppPath -HubManagerScriptPath ([string]$hubManagerScript.path)
        $desktopExe = Resolve-ImmoAppDesktopExecutable
        $lanAccess = -not $NoLanAccess.IsPresent
        $effectiveInstallMode = if (-not [string]::IsNullOrWhiteSpace($InstallMode)) {
            $InstallMode
        }
        elseif ($Role -eq "HubOnly") {
            "hub_only"
        }
        elseif ($selectedInstallDesktopValue -and $selectedInstallHubValue) {
            "desktop_and_hub"
        }
        elseif ($selectedInstallHubValue) {
            "hub_only"
        }
        elseif ($selectedInstallDesktopValue) {
            "desktop_only"
        }
        else {
            "desktop_and_hub"
        }
        $elevatedSetupRequired = ((-not $ValidateOnly) -and $lanAccess -and $CreateFirewallRule.IsPresent)
        $elevatedSetupObserved = Test-CurrentProcessElevated
        if ($ValidateOnly) {
            $lanAddress = Get-ImmoAppPreferredLanAddress
            $frontDoorPort = Get-ImmoAppHubPort
            $frontDoorUrl = if ($lanAccess) { "http://${lanAddress}:$frontDoorPort" } else { "http://127.0.0.1:$frontDoorPort" }
            $lan = [ordered]@{
                hub_display_name = $HubDisplayName
                machine_hostname_readonly = $env:COMPUTERNAME
                lan_ip = $lanAddress
                hub_url = $frontDoorUrl
                front_door_url = $frontDoorUrl
                front_door_port = $frontDoorPort
                front_door_service = "caddy"
                backend_internal_host_port = "18000"
                web_bind_host = "127.0.0.1"
                caddy_bind_host = if ($lanAccess) { "0.0.0.0" } else { "127.0.0.1" }
                allowed_hosts = @("localhost", "127.0.0.1", $env:COMPUTERNAME, $lanAddress)
                local_http_private_lan = $true
                lan_access_enabled = [bool]$lanAccess
            }
            $profile = [ordered]@{ validation_only = $true; generated = $false }
        }
        else {
            $lan = Set-ImmoAppHubLanRuntimeEnv -EnvFilePath $envFile -HubHostName $HubDisplayName -LanAccess:$lanAccess
            $profileText = Invoke-ImmoAppHubRuntimeProfile -Action "generate" -Format "json"
            $profile = Convert-HubProfileOutputToJson -Lines $profileText
        }
        $firewall = Ensure-ImmoAppHubFirewallRule -ValidateOnly:$ValidateOnly -LanAccess:$lanAccess -Requested:$CreateFirewallRule
        $autostart = if ($NoAutoStart) { [ordered]@{ enabled = $false } } else { Register-HubAutoStart -ValidateOnly:$ValidateOnly }
        $shortcuts = @()
        if ((-not $ValidateOnly) -and (-not $NoShortcuts)) {
            $shortcuts += New-HubManagerShortcut -Name "ImmoApp Hub Manager" -ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath
            $shortcuts += New-HubManagerShortcut -Name "ImmoApp Hub Status" -ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath -Action "status"
            $shortcuts += New-HubManagerShortcut -Name "Start ImmoApp Hub" -ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath -Action "start" -ExtraArguments @("-UseWindowsVolumes")
            $shortcuts += New-HubManagerShortcut -Name "Stop ImmoApp Hub" -ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath -Action "stop" -ExtraArguments @("-UseWindowsVolumes")
            $shortcuts += New-HubManagerShortcut -Name "Restart ImmoApp Hub" -ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath -Action "restart" -ExtraArguments @("-UseWindowsVolumes")
            $shortcuts += New-HubManagerShortcut -Name "Rename ImmoApp Hub" -ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath -Action "rename-hub"
            $shortcuts += New-HubManagerShortcut -Name "ImmoApp Hub Connection Details" -ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath -Action "connection-details"
            $shortcuts += New-HubManagerShortcut -Name "ImmoApp Hub Runtime Status" -ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath -Action "runtime-status"
            $shortcuts += New-HubManagerShortcut -Name "ImmoApp Hub Firewall Status" -ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath -Action "firewall-status"
            $shortcuts += New-HubManagerShortcut -Name "Copy ImmoApp Hub Connection URL" -ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath -Action "copy-url"
            $shortcuts += New-HubManagerShortcut -Name "Backup ImmoApp Hub Now" -ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath -Action "backup-now"
            $shortcuts += New-HubManagerShortcut -Name "Open ImmoApp Desktop" -ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath -Action "open-desktop"
            $shortcuts += New-HubManagerShortcut -Name "Collect ImmoApp Support Bundle" -ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath -Action "support"
            $shortcuts += New-HubManagerShortcut -Name "Open ImmoApp Hub Logs" -ScriptPath $hubManagerScript.path -ManagerAppPath $hubManagerAppPath -Action "logs"
        }
        $shouldStartHub = (-not $ValidateOnly) -and (-not $NoStartHub.IsPresent)
        if ($StartHub -and $NoStartHub) {
            throw "StartHub and NoStartHub cannot both be set."
        }
        if ($shouldStartHub) {
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "hub_manager.ps1") -Action start -UseWindowsVolumes
            if ($LASTEXITCODE -ne 0) {
                throw "Office Hub start failed. Runtime mode=$($runtimeDetection.runtime_dependency_mode) agency_status=$($runtimeDetection.agency_install_status) reason=$($runtimeDetection.reason)"
            }
        }
        $frontDoorStatus = if (
            -not [string]::IsNullOrWhiteSpace([string]$lan.front_door_url) -and
            [string]$lan.front_door_service -eq "caddy" -and
            [int]$lan.front_door_port -gt 0
        ) { "GO" } else { "NO-GO" }
        $foundationPlanNoGoReasons = New-Object System.Collections.Generic.List[string]
        if ([string]$directoryEvidence.status -ne "GO") { $foundationPlanNoGoReasons.Add("hub_directories_not_safe") | Out-Null }
        if ([string]$identity.proof_result -ne "GO") { $foundationPlanNoGoReasons.Add("hub_identity_not_valid") | Out-Null }
        if ([string]$stateManifest.proof_result -ne "GO") { $foundationPlanNoGoReasons.Add("hub_state_manifest_not_valid") | Out-Null }
        if ($frontDoorStatus -ne "GO") { $foundationPlanNoGoReasons.Add("front_door_not_configured") | Out-Null }
        if ($lanAccess -and [string]$firewall.status -eq "skipped_no_lan_requested") { $foundationPlanNoGoReasons.Add("firewall_rule_not_requested_for_lan") | Out-Null }
        if ($lanAccess -and [string]$firewall.status -eq "already_present_invalid") { $foundationPlanNoGoReasons.Add("firewall_rule_already_present_invalid") | Out-Null }
        if ([string]$firewall.status -eq "failed") { $foundationPlanNoGoReasons.Add("firewall_rule_failed") | Out-Null }
        $foundationPlanStatus = if ($foundationPlanNoGoReasons.Count -eq 0) { "GO" } else { "NO-GO" }

        $foundationAppliedNoGoReasons = New-Object System.Collections.Generic.List[string]
        if ($ValidateOnly) {
            $foundationAppliedStatus = "NOT_APPLICABLE"
        }
        else {
            if ([string]$directoryEvidence.status -ne "GO") { $foundationAppliedNoGoReasons.Add("hub_directories_not_safe") | Out-Null }
            if ([string]$identity.proof_result -ne "GO") { $foundationAppliedNoGoReasons.Add("hub_identity_not_written") | Out-Null }
            if ([string]$stateManifest.proof_result -ne "GO") { $foundationAppliedNoGoReasons.Add("hub_state_manifest_not_written") | Out-Null }
            if ($frontDoorStatus -ne "GO") { $foundationAppliedNoGoReasons.Add("front_door_not_configured") | Out-Null }
            if ($CreateFirewallRule.IsPresent -and [string]::IsNullOrWhiteSpace($SetupRunId)) {
                $foundationAppliedNoGoReasons.Add("setup_run_id_required_for_elevated_hub_setup") | Out-Null
            }
            if ($elevatedSetupRequired -and -not $elevatedSetupObserved) {
                $foundationAppliedNoGoReasons.Add("hub_setup_requires_elevation") | Out-Null
            }
            if ($lanAccess) {
                if ([string]$firewall.status -notin @("created", "updated", "already_present_valid")) {
                    $foundationAppliedNoGoReasons.Add("firewall_rule_not_applied_or_invalid_for_lan") | Out-Null
                }
                if (-not (Convert-ImmoAppBoolean $firewall.verified)) {
                    $foundationAppliedNoGoReasons.Add("firewall_rule_not_verified") | Out-Null
                }
            }
            elseif ([string]$firewall.status -ne "skipped_local_only") {
                $foundationAppliedNoGoReasons.Add("local_only_firewall_status_invalid") | Out-Null
            }
            $foundationAppliedStatus = if ($foundationAppliedNoGoReasons.Count -eq 0) { "GO" } else { "NO-GO" }
        }
        $runtimeMode = [string]$runtimeDetection.runtime_dependency_mode
        $runtimeUserVisible = [bool]$runtimeDetection.runtime_is_user_visible
        $runtimeHiddenFromOperator = (
            $runtimeMode -eq "managed_container_runtime" -and
            -not $runtimeUserVisible -and
            [string]$runtimeDetection.provider_validation_status -eq "valid" -and
            [string]$runtimeDetection.agency_install_status -eq "GO"
        )
        $dockerDesktopDetected = Convert-ImmoAppBoolean (Get-ImmoAppObjectValue -Data $runtimeDetection -Name "docker_desktop_detected")
        $manualDockerInternalOnly = ($runtimeMode -eq "manual_docker_desktop" -or $dockerDesktopDetected)
        $hubManagerInstalledSource = Test-ImmoAppInstalledSource -Source ([string]$hubManagerScript.source)
        $desktopInstalledSource = Test-ImmoAppInstalledSource -Source ([string]$desktopExe.source)
        $agencyNoGoReasons = New-Object System.Collections.Generic.List[string]
        if ([string]$runtimeDetection.agency_install_status -ne "GO") { $agencyNoGoReasons.Add("managed_runtime_not_agency_ready") | Out-Null }
        if (-not $hubManagerInstalledSource) { $agencyNoGoReasons.Add("hub_manager_not_installed_path") | Out-Null }
        if ($effectiveInstallMode -eq "desktop_and_hub" -and -not $desktopInstalledSource) { $agencyNoGoReasons.Add("desktop_not_installed_path") | Out-Null }
        $agencyNoGoReasons.Add("public_beta_requires_signing_and_https_cert_policy") | Out-Null

        $result = [ordered]@{
            kind = "immoapp_hub_installer_foundation_evidence"
            schema_version = 1
            setup_result_kind = "immoapp_hub_setup_result"
            validate_only = [bool]$ValidateOnly
            setup_run_id = $SetupRunId
            role = if ($Role -eq "HubOnly" -or $effectiveInstallMode -eq "hub_only") { "hub_only" } else { "hub_desktop" }
            selected_role = if ($Role -eq "HubOnly" -or $effectiveInstallMode -eq "hub_only") { "hub_only" } else { "hub_desktop" }
            selected_install_desktop = [bool]$selectedInstallDesktopValue
            selected_install_hub = [bool]$selectedInstallHubValue
            install_mode = $effectiveInstallMode
            setup_source = if ([string]::IsNullOrWhiteSpace($SetupRunId)) { "manual" } else { "installer_or_hub_manager" }
            created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            data_path = $paths.AppDataRoot
            env_file = $envFile
            hub_display_name = $HubDisplayName
            hub_name = $HubDisplayName
            hub_identity_status = if ([string]$identity.proof_result -eq "GO") { "GO" } else { "NO-GO" }
            hub_identity_written = (-not $ValidateOnly)
            hub_identity_path = [string]$identity.path
            hub_identity = $identity
            hub_id = [string]$identity.hub_id
            hub_state_manifest_status = if ([string]$stateManifest.proof_result -eq "GO") { "GO" } else { "NO-GO" }
            hub_state_manifest_written = (-not $ValidateOnly)
            hub_state_manifest_path = [string]$stateManifest.path
            hub_state_manifest = $stateManifest
            directories_status = [string]$directoryEvidence.status
            directories = $directoryEvidence
            hub_base_url = $lan.hub_url
            hub_front_door_url = $lan.front_door_url
            front_door_status = $frontDoorStatus
            front_door_url = $lan.front_door_url
            front_door_port = [int]$lan.front_door_port
            front_door_service = "caddy"
            lan = $lan
            lan_access_enabled = [bool]$lanAccess
            elevated_setup_required = [bool]$elevatedSetupRequired
            elevated_setup_observed = [bool]$elevatedSetupObserved
            auto_start = $autostart
            firewall = $firewall
            firewall_status = [string]$firewall.status
            firewall_rule_name = [string]$firewall.rule_name
            runtime_profile = $profile
            wsl_runtime_candidate_requested = [bool]$ConfigureWslRuntimeCandidate
            wsl_runtime_candidate_install = $wslRuntimeCandidateInstall
            candidate_registration_status = if ($wslRuntimeCandidateInstall) { [string](Get-ImmoAppObjectValue -Data $wslRuntimeCandidateInstall -Name "candidate_registration_status") } else { "not_requested" }
            runtime_artifact_status = if ($wslRuntimeCandidateInstall) { [string](Get-ImmoAppObjectValue -Data $wslRuntimeCandidateInstall -Name "runtime_artifact_status") } else { "not_requested" }
            runtime_start_status = if ($wslRuntimeCandidateInstall) { [string](Get-ImmoAppObjectValue -Data $wslRuntimeCandidateInstall -Name "runtime_start_status") } else { "not_requested" }
            runtime_detection_path = $runtimeDetectionPath
            runtime_detection = $runtimeDetection
            runtime_provider_proof = [ordered]@{
                provider_config_path = [string]$runtimeDetection.provider_config_path
                provider_config_present = [bool]$runtimeDetection.provider_config_present
                provider_config_valid = [bool]$runtimeDetection.provider_config_valid
                provider_mode = [string](Get-ImmoAppObjectValue -Data $runtimeDetection.provider -Name "provider_mode")
                runtime_user_visible = [bool]$runtimeDetection.runtime_is_user_visible
                internal_proof_status = [string]$runtimeDetection.internal_proof_status
                reason_code = [string]$runtimeDetection.reason_code
                package_inventory_path = [string](Get-ImmoAppObjectValue -Data $runtimeDetection.provider -Name "package_inventory_path")
                package_sha256 = [string](Get-ImmoAppObjectValue -Data $runtimeDetection.provider -Name "package_sha256")
            }
            manager_shortcuts = @($shortcuts)
            hub_manager_app_path = [string]$hubManagerAppPath
            hub_manager_app_present = (-not [string]::IsNullOrWhiteSpace($hubManagerAppPath))
            runtime_is_user_visible = $runtimeUserVisible
            runtime_dependency_mode = $runtimeMode
            runtime_hidden_from_operator = $runtimeHiddenFromOperator
            docker_desktop_detected = $dockerDesktopDetected
            manual_docker_desktop_internal_only = $manualDockerInternalOnly
            docker_compose_hidden_from_user = $runtimeHiddenFromOperator
            agency_install_status = [string]$runtimeDetection.agency_install_status
            internal_proof_status = [string]$runtimeDetection.internal_proof_status
            public_beta_status = "NO_GO"
            transport_security = "local_http_private_lan"
            private_lan_http_only = $true
            hub_manager_script_path = [string]$hubManagerScript.path
            hub_manager_script_source = [string]$hubManagerScript.source
            desktop_exe_path = [string]$desktopExe.path
            desktop_exe_source = [string]$desktopExe.source
            repo_dev_paths_internal_only = (
                [string]$hubManagerScript.source -eq "repo_dev" -or
                ($effectiveInstallMode -eq "desktop_and_hub" -and [string]$desktopExe.source -eq "repo_dev")
            )
            proof_scope = if ($hubManagerInstalledSource -and ($effectiveInstallMode -eq "hub_only" -or $desktopInstalledSource)) { "installed" } else { "dev_internal" }
            starts_backend_services = [bool]$shouldStartHub
            foundation_plan_status = $foundationPlanStatus
            foundation_applied_status = $foundationAppliedStatus
            hub_foundation_status = $foundationAppliedStatus
            no_go_reasons = @($agencyNoGoReasons.ToArray())
            foundation_plan_no_go_reasons = @($foundationPlanNoGoReasons.ToArray())
            foundation_no_go_reasons = @($foundationAppliedNoGoReasons.ToArray())
            dry_run_reason = if ($ValidateOnly) { "validate_only_is_planning_evidence_not_applied_setup_proof" } else { "" }
            proof_result = if ($ValidateOnly) { "NO-GO" } else { $foundationAppliedStatus }
            failure_reason = if ($ValidateOnly) {
                "Validate-only is planning evidence, not applied Hub setup proof."
            } elseif ($foundationAppliedNoGoReasons.Count -gt 0) {
                $foundationAppliedNoGoReasons.ToArray() -join "; "
            } else {
                ""
            }
        }
    }
    finally {
        if ($null -ne $oldRoot) { $env:IMMOAPP_APPDATA_ROOT = $oldRoot } else { Remove-Item Env:IMMOAPP_APPDATA_ROOT -ErrorAction SilentlyContinue }
    }
}

if ($OutputJson) {
    $outputPaths = New-ImmoAppRuntimePaths -AppDataRoot $DataRoot
    Write-ImmoAppSafeJson -Path $OutputJson -Payload $result -ApprovedRoots @($outputPaths.LogsRoot, $outputPaths.ConfigRoot, $outputPaths.TmpRoot) | Out-Null
    Write-Host "Hub setup result JSON: $OutputJson"
}

Write-Host "ImmoApp Hub setup role=$($result.role)"
Write-Host "Hub URL: $($result.hub_base_url)"
Write-Host "Proof result: $($result.proof_result)"
