#define MyAppName "ImmoApp Beta"
#define MyAppPublisher "ImmoApp"
#define MyAppExeName "ImmoApp.exe"
#define MyHubManagerExeName "ImmoApp Hub Manager.exe"
#define MyAppVersion GetEnv("IMMOAPP_INSTALLER_VERSION")
#define MyAppSourceDir GetEnv("IMMOAPP_INSTALLER_SOURCE_DIR")
#define MyAppOutputDir GetEnv("IMMOAPP_INSTALLER_OUTPUT_DIR")
#define MyAppOutputBase GetEnv("IMMOAPP_INSTALLER_OUTPUT_BASE")

[Setup]
AppId={{B8325FD1-B776-4E4D-8D43-7F0869574A10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\ImmoApp Beta
DefaultGroupName=ImmoApp Beta
DisableProgramGroupPage=yes
OutputDir={#MyAppOutputDir}
OutputBaseFilename={#MyAppOutputBase}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[CustomMessages]
HubRolePageTitle=Choose what to install
HubRolePageDescription=Install the desktop app, prepare this computer as the office Hub, or both.
HubRoleDesktop=Install ImmoApp Desktop
HubRoleHub=Set up this computer as Office Hub
HubRoleSelectOne=Choose at least one option: Desktop, Office Hub, or both.
HubNamePageTitle=Name this office Hub
HubNamePageDescription=Choose a simple name your team will recognize, like Main Office. You can change it later in Hub Manager.
HubNamePagePrompt=Hub name:
HubNamePageHelp=Choose a simple name your team will recognize, like Main Office or Reception PC.
HubNamePageExample=Example: Main Office
HubSetupFinishLater=Office Hub setup was not completed. Open Hub Manager and choose Finish ImmoApp Office Hub Setup. Technical evidence:

[Tasks]
; No Flags: unchecked here: Inno checks this Desktop shortcut task initially by default.
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove build-machine runtime builders left by older Hub-capable installers.
Type: files; Name: "{app}\scripts\build_managed_wsl2_runtime_artifact.ps1"
Type: files; Name: "{app}\scripts\build_managed_wsl2_runtime_rootfs.ps1"
Type: files; Name: "{app}\scripts\build_managed_wsl2_runtime_image_bundle.ps1"
Type: files; Name: "{app}\scripts\backup_release_bundle.ps1"
Type: files; Name: "{app}\scripts\verify_release_backup_integrity.py"
Type: files; Name: "{app}\scripts\verify_release_bundle_manifest.py"
Type: files; Name: "{app}\deployment\compose\compose.yml"
Type: files; Name: "{app}\deployment\compose\compose.windows.yml"
Type: files; Name: "{app}\deployment\compose\compose.app.yml"
Type: files; Name: "{app}\deployment\proxy\Caddyfile"
Type: files; Name: "{app}\deployment\managed-runtime\bin\immoapp-runtime-identity"
Type: files; Name: "{app}\deployment\managed-runtime\bin\managed-hub-common"
Type: files; Name: "{app}\deployment\managed-runtime\bin\start-managed-hub"
Type: files; Name: "{app}\deployment\managed-runtime\bin\status-managed-hub"
Type: files; Name: "{app}\deployment\managed-runtime\bin\health-managed-hub"
Type: files; Name: "{app}\deployment\managed-runtime\bin\logs-managed-hub"
Type: files; Name: "{app}\deployment\managed-runtime\bin\backup-managed-hub"
Type: files; Name: "{app}\deployment\managed-runtime\bin\stop-managed-hub"
Type: files; Name: "{app}\deployment\managed-runtime\bin\restart-managed-hub"
Type: files; Name: "{app}\deployment\managed-runtime\compose\compose.yaml"
Type: files; Name: "{app}\deployment\managed-runtime\proxy\Caddyfile"
; Remove generated cache/transient files that can survive install-over-existing.
Type: filesandordirs; Name: "{app}\core\__pycache__"
Type: filesandordirs; Name: "{app}\core\runtime\__pycache__"
Type: files; Name: "{app}\core\*.pyc"
Type: files; Name: "{app}\core\runtime\*.pyc"
Type: files; Name: "{app}\is-*.tmp"
Type: files; Name: "{app}\deployment\managed-runtime\images\is-*.tmp"

[UninstallDelete]
; Inno can leave transient replacement files when binaries were recently used.
Type: files; Name: "{app}\is-*.tmp"
Type: files; Name: "{app}\_internal\PySide6\is-*.tmp"
Type: files; Name: "{app}\deployment\managed-runtime\images\is-*.tmp"

[Icons]
Name: "{autoprograms}\ImmoApp Beta"; Filename: "{app}\{#MyAppExeName}"; Check: IsDesktopSelected
Name: "{autodesktop}\ImmoApp Beta"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Check: IsDesktopSelected
Name: "{autoprograms}\ImmoApp Hub\ImmoApp Hub Manager"; Filename: "{app}\{#MyHubManagerExeName}"; Check: IsHubSelected
Name: "{autoprograms}\ImmoApp Hub\Finish ImmoApp Office Hub Setup"; Filename: "{app}\{#MyHubManagerExeName}"; Parameters: "--action finish-hub-setup"; Check: IsHubSelected
Name: "{autoprograms}\ImmoApp Hub\ImmoApp Hub Status"; Filename: "{app}\{#MyHubManagerExeName}"; Parameters: "--action status"; Check: IsHubSelected
Name: "{autoprograms}\ImmoApp Hub\Start ImmoApp Hub"; Filename: "{app}\{#MyHubManagerExeName}"; Parameters: "--action start"; Check: IsHubSelected
Name: "{autoprograms}\ImmoApp Hub\Stop ImmoApp Hub"; Filename: "{app}\{#MyHubManagerExeName}"; Parameters: "--action stop"; Check: IsHubSelected
Name: "{autoprograms}\ImmoApp Hub\Restart ImmoApp Hub"; Filename: "{app}\{#MyHubManagerExeName}"; Parameters: "--action restart"; Check: IsHubSelected
Name: "{autoprograms}\ImmoApp Hub\Rename ImmoApp Hub"; Filename: "{app}\{#MyHubManagerExeName}"; Parameters: "--action rename-hub"; Check: IsHubSelected
Name: "{autoprograms}\ImmoApp Hub\ImmoApp Hub Connection Details"; Filename: "{app}\{#MyHubManagerExeName}"; Parameters: "--action connection-details"; Check: IsHubSelected
Name: "{autoprograms}\ImmoApp Hub\ImmoApp Hub Runtime Status"; Filename: "{app}\{#MyHubManagerExeName}"; Parameters: "--action runtime-status"; Check: IsHubSelected
Name: "{autoprograms}\ImmoApp Hub\ImmoApp Hub Firewall Status"; Filename: "{app}\{#MyHubManagerExeName}"; Parameters: "--action firewall-status"; Check: IsHubSelected
Name: "{autoprograms}\ImmoApp Hub\Copy ImmoApp Hub Connection URL"; Filename: "{app}\{#MyHubManagerExeName}"; Parameters: "--action copy-url"; Check: IsHubSelected
Name: "{autoprograms}\ImmoApp Hub\Backup ImmoApp Hub Now"; Filename: "{app}\{#MyHubManagerExeName}"; Parameters: "--action backup-now"; Check: IsHubSelected
Name: "{autoprograms}\ImmoApp Hub\Collect ImmoApp Support Bundle"; Filename: "{app}\{#MyHubManagerExeName}"; Parameters: "--action support"; Check: IsHubSelected
Name: "{autoprograms}\ImmoApp Hub\Open ImmoApp Hub Logs"; Filename: "{app}\{#MyHubManagerExeName}"; Parameters: "--action logs"; Check: IsHubSelected
Name: "{autoprograms}\ImmoApp Hub\Open ImmoApp Desktop"; Filename: "{app}\{#MyHubManagerExeName}"; Parameters: "--action open-desktop"; Check: IsHubAndDesktopSelected

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch ImmoApp Beta"; Flags: nowait postinstall skipifsilent; Check: IsDesktopSelected

[Code]
var
  HubRolePage: TInputOptionWizardPage;
  HubNamePage: TInputQueryWizardPage;
  SelectedHubDisplayName: String;
  CurrentSetupRunId: String;

function IsDesktopSelected(): Boolean;
begin
  Result := Assigned(HubRolePage) and HubRolePage.Values[0];
end;

function IsHubSelected(): Boolean;
begin
  Result := Assigned(HubRolePage) and HubRolePage.Values[1];
end;

function IsHubAndDesktopSelected(): Boolean;
begin
  Result := IsHubSelected() and IsDesktopSelected();
end;

function GetSelectedInstallMode(): String;
begin
  if IsDesktopSelected() and IsHubSelected() then begin
    Result := 'desktop_and_hub';
  end else if IsHubSelected() then begin
    Result := 'hub_only';
  end else begin
    Result := 'desktop_only';
  end;
end;

function GetSelectedHubSetupRole(): String;
begin
  if IsHubSelected() and (not IsDesktopSelected()) then begin
    Result := 'HubOnly';
  end else begin
    Result := 'HubDesktop';
  end;
end;

function LooksLikeIpAddress(Value: String): Boolean;
var
  I: Integer;
  Ch: String;
  HasDigit: Boolean;
begin
  Result := False;
  HasDigit := False;
  for I := 1 to Length(Value) do begin
    Ch := Copy(Value, I, 1);
    if Pos(Ch, '0123456789.:') = 0 then begin
      exit;
    end;
    if Pos(Ch, '0123456789') > 0 then begin
      HasDigit := True;
    end;
  end;
  Result := HasDigit and ((Pos('.', Value) > 0) or (Pos(':', Value) > 0));
end;

function LooksLikeMachineHostname(Value: String): Boolean;
var
  LowerValue: String;
begin
  LowerValue := Lowercase(Value);
  Result :=
    (Pos('desktop-', LowerValue) = 1) or
    (Pos('laptop-', LowerValue) = 1) or
    (Pos('win-', LowerValue) = 1) or
    (LowerValue = Lowercase(GetComputerNameString()));
end;

function IsHubDisplayNameValid(Value: String): Boolean;
var
  I: Integer;
  Ch: String;
  LowerValue: String;
begin
  Value := Trim(Value);
  LowerValue := Lowercase(Value);
  Result := False;
  if (Length(Value) < 3) or (Length(Value) > 60) then begin
    exit;
  end;
  if (LowerValue = 'localhost') or (LowerValue = '127.0.0.1') or (LowerValue = '::1') then begin
    exit;
  end;
  if (Pos('://', LowerValue) > 0) or (Pos('www.', LowerValue) = 1) or LooksLikeIpAddress(Value) or LooksLikeMachineHostname(Value) then begin
    exit;
  end;
  for I := 1 to Length(Value) do begin
    Ch := Copy(Value, I, 1);
    if Pos(Ch, 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ''-') = 0 then begin
      exit;
    end;
  end;
  Result := True;
end;

function QuotePowerShell(Value: String): String;
var
  Escaped: String;
begin
  Escaped := Value;
  StringChange(Escaped, '"', '\"');
  Result := '"' + Escaped + '"';
end;

function JsonContainsStringField(JsonText: String; FieldName: String; ExpectedValue: String): Boolean;
var
  Compact: String;
begin
  Compact := JsonText;
  StringChange(Compact, #13, '');
  StringChange(Compact, #10, '');
  StringChange(Compact, #9, '');
  StringChange(Compact, ' ', '');
  Result := Pos('"' + FieldName + '":"' + ExpectedValue + '"', Compact) > 0;
end;

function JsonContainsBooleanField(JsonText: String; FieldName: String; ExpectedValue: Boolean): Boolean;
var
  Compact: String;
  ExpectedText: String;
begin
  Compact := JsonText;
  StringChange(Compact, #13, '');
  StringChange(Compact, #10, '');
  StringChange(Compact, #9, '');
  StringChange(Compact, ' ', '');
  if ExpectedValue then begin
    ExpectedText := 'true';
  end else begin
    ExpectedText := 'false';
  end;
  Result := Pos('"' + FieldName + '":' + ExpectedText, Compact) > 0;
end;

function JsonContainsIntegerField(JsonText: String; FieldName: String; ExpectedValue: Integer): Boolean;
var
  Compact: String;
begin
  Compact := JsonText;
  StringChange(Compact, #13, '');
  StringChange(Compact, #10, '');
  StringChange(Compact, #9, '');
  StringChange(Compact, ' ', '');
  Result := Pos('"' + FieldName + '":' + IntToStr(ExpectedValue), Compact) > 0;
end;

function HubSetupEvidenceAppliedGo(EvidencePath: String; SetupRunId: String): Boolean;
var
  EvidenceText: AnsiString;
  JsonText: String;
begin
  Result := False;
  if not FileExists(EvidencePath) then begin
    exit;
  end;
  if not LoadStringFromFile(EvidencePath, EvidenceText) then begin
    exit;
  end;
  JsonText := String(EvidenceText);
  Result :=
    JsonContainsStringField(JsonText, 'kind', 'immoapp_hub_installer_foundation_evidence') and
    JsonContainsStringField(JsonText, 'setup_run_id', SetupRunId) and
    JsonContainsBooleanField(JsonText, 'validate_only', False) and
    JsonContainsBooleanField(JsonText, 'selected_install_hub', True) and
    JsonContainsBooleanField(JsonText, 'selected_install_desktop', IsDesktopSelected()) and
    (
      JsonContainsStringField(JsonText, 'install_mode', 'hub_only') or
      JsonContainsStringField(JsonText, 'install_mode', 'desktop_and_hub')
    ) and
    JsonContainsStringField(JsonText, 'foundation_applied_status', 'GO') and
    JsonContainsStringField(JsonText, 'hub_foundation_status', 'GO') and
    JsonContainsStringField(JsonText, 'proof_result', 'GO') and
    JsonContainsStringField(JsonText, 'hub_identity_status', 'GO') and
    JsonContainsStringField(JsonText, 'directories_status', 'GO') and
    JsonContainsStringField(JsonText, 'front_door_status', 'GO') and
    JsonContainsBooleanField(JsonText, 'lan_access_enabled', True) and
    JsonContainsBooleanField(JsonText, 'elevated_setup_required', True) and
    JsonContainsBooleanField(JsonText, 'elevated_setup_observed', True) and
    JsonContainsIntegerField(JsonText, 'front_door_port', 8000) and
    (
      JsonContainsStringField(JsonText, 'firewall_status', 'created') or
      JsonContainsStringField(JsonText, 'firewall_status', 'already_present_valid')
    ) and
    JsonContainsBooleanField(JsonText, 'verified', True) and
    JsonContainsStringField(JsonText, 'direction', 'Inbound') and
    JsonContainsStringField(JsonText, 'action', 'Allow') and
    JsonContainsStringField(JsonText, 'protocol', 'TCP') and
    JsonContainsStringField(JsonText, 'profile', 'Private') and
    JsonContainsStringField(JsonText, 'local_port', '8000');
end;

function NewSetupRunId(): String;
begin
  Result := Lowercase(GetDateTimeString('yyyymmddhhnnss', '-', ':'));
end;

function JsonBoolean(Value: Boolean): String;
begin
  if Value then begin
    Result := 'true';
  end else begin
    Result := 'false';
  end;
end;

function PowerShellBoolean(Value: Boolean): String;
begin
  if Value then begin
    Result := '1';
  end else begin
    Result := '0';
  end;
end;

procedure WriteHubSetupLaunchMarker(EvidencePath: String; SetupRunId: String);
var
  MarkerPath: String;
  MarkerText: AnsiString;
begin
  MarkerPath := AddBackslash(ExtractFileDir(EvidencePath)) + 'hub_setup_launch_requested.json';
  MarkerText :=
    '{"kind":"immoapp_hub_setup_launch_requested","schema_version":1,' +
    '"setup_run_id":"' + SetupRunId + '",' +
    '"setup_mode":"elevated_hub_role_firewall",' +
    '"hub_display_name":"' + SelectedHubDisplayName + '",' +
    '"selected_install_desktop":' + JsonBoolean(IsDesktopSelected()) + ',' +
    '"selected_install_hub":' + JsonBoolean(IsHubSelected()) + ',' +
    '"install_mode":"' + GetSelectedInstallMode() + '",' +
    '"proof_result":"NO-GO"}';
  ForceDirectories(ExtractFileDir(EvidencePath));
  SaveStringToFile(MarkerPath, MarkerText, False);
end;

procedure WriteHubSetupDeferredEvidence(EvidencePath: String; SetupRunId: String);
var
  EvidenceText: AnsiString;
begin
  EvidenceText :=
    '{"kind":"immoapp_hub_installer_foundation_evidence","schema_version":1,' +
    '"setup_result_kind":"immoapp_hub_setup_result",' +
    '"validate_only":false,' +
    '"setup_run_id":"' + SetupRunId + '",' +
    '"role":"' + GetSelectedInstallMode() + '",' +
    '"selected_install_desktop":' + JsonBoolean(IsDesktopSelected()) + ',' +
    '"selected_install_hub":' + JsonBoolean(IsHubSelected()) + ',' +
    '"install_mode":"' + GetSelectedInstallMode() + '",' +
    '"setup_source":"installer_silent_deferred",' +
    '"hub_display_name":"' + SelectedHubDisplayName + '",' +
    '"hub_name":"' + SelectedHubDisplayName + '",' +
    '"foundation_applied_status":"NO-GO",' +
    '"hub_foundation_status":"NO-GO",' +
    '"proof_result":"NO-GO",' +
    '"reason_code":"silent_install_defers_elevated_hub_setup",' +
    '"setup_deferred":true,' +
    '"finish_later_required":true,' +
    '"hub_identity_status":"not_run",' +
    '"hub_state_manifest_status":"not_run",' +
    '"directories_status":"not_run",' +
    '"front_door_status":"not_run",' +
    '"front_door_port":8000,' +
    '"lan_access_enabled":true,' +
    '"elevated_setup_required":true,' +
    '"elevated_setup_observed":false,' +
    '"firewall_status":"deferred",' +
    '"agency_install_status":"NO_GO",' +
    '"public_beta_status":"NO_GO"}';
  ForceDirectories(ExtractFileDir(EvidencePath));
  SaveStringToFile(EvidencePath, EvidenceText, False);
end;

procedure ApplyCommandLineRoleSelection();
var
  InstallMode: String;
  HubNameParam: String;
begin
  InstallMode := Lowercase(Trim(ExpandConstant('{param:IMMOAPPINSTALLMODE|}')));
  HubNameParam := Trim(ExpandConstant('{param:IMMOAPPHUBNAME|}'));
  if InstallMode = '' then begin
    HubRolePage.Values[0] := True;
    HubRolePage.Values[1] := False;
  end else if InstallMode = 'desktop_only' then begin
    HubRolePage.Values[0] := True;
    HubRolePage.Values[1] := False;
  end else if InstallMode = 'hub_only' then begin
    HubRolePage.Values[0] := False;
    HubRolePage.Values[1] := True;
  end else if InstallMode = 'desktop_and_hub' then begin
    HubRolePage.Values[0] := True;
    HubRolePage.Values[1] := True;
  end else begin
    RaiseException('Invalid /IMMOAPPINSTALLMODE. Use desktop_only, hub_only, or desktop_and_hub.');
  end;

  if HubNameParam <> '' then begin
    SelectedHubDisplayName := HubNameParam;
    HubNamePage.Values[0] := HubNameParam;
  end;
  if ((InstallMode = 'hub_only') or (InstallMode = 'desktop_and_hub')) and (not IsHubDisplayNameValid(SelectedHubDisplayName)) then begin
    RaiseException('Hub installs require /IMMOAPPHUBNAME with a friendly Hub name, for example /IMMOAPPHUBNAME="Main Office".');
  end;
end;

procedure InitializeWizard();
begin
  HubRolePage :=
    CreateInputOptionPage(
      wpSelectDir,
      CustomMessage('HubRolePageTitle'),
      CustomMessage('HubRolePageDescription'),
      '',
      False,
      False
    );
  HubRolePage.Add(CustomMessage('HubRoleDesktop'));
  HubRolePage.Add(CustomMessage('HubRoleHub'));
  HubRolePage.Values[0] := True;
  HubRolePage.Values[1] := False;

  HubNamePage :=
    CreateInputQueryPage(
      HubRolePage.ID,
      CustomMessage('HubNamePageTitle'),
      CustomMessage('HubNamePageDescription'),
      CustomMessage('HubNamePageExample')
    );
  HubNamePage.Add(CustomMessage('HubNamePagePrompt'), False);
  ApplyCommandLineRoleSelection();
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = wpSelectTasks then begin
    Result := not IsDesktopSelected();
  end;
  if Assigned(HubNamePage) and (PageID = HubNamePage.ID) then begin
    Result := not IsHubSelected();
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if Assigned(HubRolePage) and (CurPageID = HubRolePage.ID) then begin
    if not IsDesktopSelected() and not IsHubSelected() then begin
      MsgBox(CustomMessage('HubRoleSelectOne'), mbError, MB_OK);
      Result := False;
    end;
  end;
  if Assigned(HubNamePage) and (CurPageID = HubNamePage.ID) then begin
    SelectedHubDisplayName := Trim(HubNamePage.Values[0]);
    if not IsHubDisplayNameValid(SelectedHubDisplayName) then begin
      MsgBox(CustomMessage('HubNamePageHelp'), mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure RunHubDesktopFoundationSetup();
var
  PowerShellExe: String;
  SetupScript: String;
  EvidencePath: String;
  Args: String;
  ResultCode: Integer;
  SetupLaunched: Boolean;
begin
  if not IsHubSelected() then begin
    exit;
  end;
  SetupScript := ExpandConstant('{app}\scripts\setup_office_hub.ps1');
  EvidencePath := ExpandConstant('{commonappdata}\ImmoApp\logs\hub_installer_foundation_evidence.json');
  PowerShellExe := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  CurrentSetupRunId := NewSetupRunId();
  DeleteFile(EvidencePath);
  WriteHubSetupLaunchMarker(EvidencePath, CurrentSetupRunId);
  if WizardSilent() then begin
    WriteHubSetupDeferredEvidence(EvidencePath, CurrentSetupRunId);
    exit;
  end;
  Args :=
    '-NoProfile -ExecutionPolicy Bypass -File ' + QuotePowerShell(SetupScript) +
    ' -Role ' + GetSelectedHubSetupRole() +
    ' -HubDisplayName ' + QuotePowerShell(SelectedHubDisplayName) +
    ' -SetupRunId ' + QuotePowerShell(CurrentSetupRunId) +
    ' -SelectedInstallDesktop ' + PowerShellBoolean(IsDesktopSelected()) +
    ' -SelectedInstallHub ' + PowerShellBoolean(IsHubSelected()) +
    ' -InstallMode ' + QuotePowerShell(GetSelectedInstallMode()) +
    ' -CreateFirewallRule -NoAutoStart -NoStartHub' +
    ' -OutputJson ' + QuotePowerShell(EvidencePath);
  SetupLaunched := ShellExec('runas', PowerShellExe, Args, '', SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode);
  if (not SetupLaunched) or (ResultCode <> 0) or (not HubSetupEvidenceAppliedGo(EvidencePath, CurrentSetupRunId)) then begin
    if not WizardSilent() then begin
      MsgBox(CustomMessage('HubSetupFinishLater') + ' ' + EvidencePath, mbInformation, MB_OK);
    end;
  end;
end;

procedure DeleteInstallerTempFiles(Directory: String);
var
  FindRec: TFindRec;
  TempPath: String;
  ChildDir: String;
begin
  if not DirExists(Directory) then begin
    exit;
  end;

  if FindFirst(AddBackslash(Directory) + 'is-*.tmp', FindRec) then begin
    try
      repeat
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0 then begin
          TempPath := AddBackslash(Directory) + FindRec.Name;
          DeleteFile(TempPath);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;

  if FindFirst(AddBackslash(Directory) + '*', FindRec) then begin
    try
      repeat
        if ((FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) and
           (FindRec.Name <> '.') and (FindRec.Name <> '..') then begin
          ChildDir := AddBackslash(Directory) + FindRec.Name;
          DeleteInstallerTempFiles(ChildDir);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure CleanInstallRootGeneratedLeftovers();
begin
  DeleteInstallerTempFiles(ExpandConstant('{app}'));
end;

procedure ScheduleDelayedInstallRootCleanup();
var
  PowerShellExe: String;
  Args: String;
  ResultCode: Integer;
begin
  PowerShellExe := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  Args :=
    '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command ' +
    QuotePowerShell(
      '$root = ' + QuotePowerShell(ExpandConstant('{app}')) + '; ' +
      'for ($i = 0; $i -lt 30; $i++) { ' +
      'Start-Sleep -Seconds 2; ' +
      'if (Test-Path -LiteralPath $root) { ' +
      'Get-ChildItem -LiteralPath $root -Recurse -Force -Filter ''is-*.tmp'' -ErrorAction SilentlyContinue | ' +
      'Remove-Item -Force -ErrorAction SilentlyContinue; ' +
      'if (-not (Get-ChildItem -LiteralPath $root -Recurse -Force -Filter ''is-*.tmp'' -ErrorAction SilentlyContinue | Select-Object -First 1)) { break } } }'
    );
  ShellExec('', PowerShellExe, Args, '', SW_HIDE, ewNoWait, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    CleanInstallRootGeneratedLeftovers();
    RunHubDesktopFoundationSetup();
    CleanInstallRootGeneratedLeftovers();
    ScheduleDelayedInstallRootCleanup();
  end;
end;
